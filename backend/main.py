"""
Cloud Run API wrapper for ADK Trello Orders Agent

This FastAPI application wraps the existing ADK agent and provides a simple
HTTP API endpoint for chat interactions with session management.
"""

import logging
import os
from typing import Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from integrations.trello.config import TrelloSettings
from integrations.trello.router import get_trello_router
from integrations.trello.service import TrelloService

# In Docker container, agent.py is in same directory as main.py (/app/)
# In local development, agent.py is in parent directory
import sys
from pathlib import Path

# Check if agent.py is in current directory (Docker) or parent (local dev)
current_dir = Path(__file__).parent
if (current_dir / "agent.py").exists():
    # Docker: agent.py is in /app/ alongside main.py
    pass
else:
    # Local dev: agent.py is in project root
    project_root = current_dir.parent
    sys.path.insert(0, str(project_root))

from agent import root_agent
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment configuration
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
APP_NAME = os.environ.get("APP_NAME", "trello_orders_chat")

if not PROJECT_ID:
    raise ValueError(
        "BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable is required"
    )

# Initialize FastAPI app
app = FastAPI(
    title="Trello Orders Chat API",
    description="API wrapper for ADK Trello Orders Agent",
    version="1.0.0"
)

# Configure CORS - allow Firebase Hosting domains and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://maxprint-61206.web.app",
        "https://maxprint-61206.firebaseapp.com",
        "http://localhost:3000",  # For local frontend development
        "http://localhost:8080",  # For local backend testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ADK Runner with in-memory session service
# Note: Sessions are lost on container restart, but sufficient for MVP demos
session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)

# Request/Response models
class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


# In-memory session tracking (optional - for monitoring)
active_sessions: Dict[str, bool] = {}

# Trello webhook integration
bq_client = None  # Initialize as None, set below if Trello is configured
try:
    trello_settings = TrelloSettings()
    trello_service = TrelloService(trello_settings)
    
    # Initialize BigQuery client and extraction service for webhook processing
    from integrations.trello.bigquery_client import TrelloBigQueryClient
    from integrations.trello.publisher import BigQueryTrelloEventPublisher
    from extractionPipeline.extract_single_card import CardExtractionService
    
    bq_client = TrelloBigQueryClient(
        project_id=PROJECT_ID,
        dataset_id="trello_rag",
    )
    
    extraction_service = CardExtractionService(
        project_id=PROJECT_ID,
    )
    
    trello_publisher = BigQueryTrelloEventPublisher(
        bq_client=bq_client,
        trello_service=trello_service,
        extraction_service=extraction_service,
    )
    
    app.include_router(get_trello_router(publisher=trello_publisher))
    logger.info("Trello webhook route registered with BigQuery processing.")
except Exception as exc:
    logger.warning(
        "Trello settings not configured; Trello webhook route disabled.",
        exc_info=exc,
    )
    # Initialize bq_client even if Trello is not configured (for queue processing)
    try:
        from integrations.trello.bigquery_client import TrelloBigQueryClient
        bq_client = TrelloBigQueryClient(
            project_id=PROJECT_ID,
            dataset_id="trello_rag",
        )
        logger.info("BigQuery client initialized for queue processing.")
    except Exception as bq_exc:
        logger.warning(f"Could not initialize BigQuery client: {bq_exc}")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "trello_orders_chat",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    """Health check endpoint for Cloud Run."""
    return {"status": "healthy"}


@app.post("/process-queue")
async def process_queue(max_items: int = 50):
    """
    Process pending BigQuery operations from the retry queue.
    
    This endpoint is designed to be called by Cloud Scheduler every 5 minutes
    to retry operations that failed due to streaming buffer.
    
    Args:
        max_items: Maximum number of items to process in one run (default: 50)
    
    Returns:
        Dict with processing statistics
    """
    try:
        if not bq_client:
            raise HTTPException(
                status_code=503,
                detail="BigQuery client not initialized"
            )
        
        stats = bq_client.process_retry_queue(max_items=max_items)
        return {
            "status": "success",
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Error processing queue: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing queue: {str(e)}"
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat endpoint that processes user messages through the ADK agent.
    
    Each session_id maintains its own conversation history via Vertex AI
    session service.
    """
    try:
        # Validate input
        if not request.message or not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        if not request.session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        # Track session
        active_sessions[request.session_id] = True
        
        logger.info(f"Processing message for session: {request.session_id}")
        
        # Ensure session exists (create if not)
        try:
            existing_session = await session_service.get_session(
                app_name=APP_NAME,
                user_id=request.session_id,
                session_id=request.session_id
            )
            if existing_session is None:
                await session_service.create_session(
                    app_name=APP_NAME,
                    user_id=request.session_id,
                    session_id=request.session_id
                )
                logger.info(f"Created new session: {request.session_id}")
        except Exception as e:
            # Session doesn't exist, create it
            logger.info(f"Creating session (get failed): {request.session_id}")
            await session_service.create_session(
                app_name=APP_NAME,
                user_id=request.session_id,
                session_id=request.session_id
            )
        
        # Create content from user message
        # Note: In newer google-genai versions, use Part(text=...) instead of Part.from_text()
        user_content = types.Content(
            role="user",
            parts=[types.Part(text=request.message)]
        )
        
        # Run agent and collect response
        response_text = ""
        async for event in runner.run_async(
            user_id=request.session_id,
            session_id=request.session_id,
            new_message=user_content
        ):
            # Collect text from response events
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text += part.text
        
        # If no response text was collected, provide a default message
        if not response_text:
            response_text = "I received your message but didn't generate a response. Please try again."
            logger.warning(f"No response text collected for session: {request.session_id}")
        
        logger.info(f"Response generated for session: {request.session_id} ({len(response_text)} chars)")
        
        return ChatResponse(reply=response_text)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing chat request: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/sessions")
async def list_sessions():
    """List active sessions (for monitoring/debugging)."""
    return {
        "active_sessions": list(active_sessions.keys()),
        "count": len(active_sessions)
    }


if __name__ == "__main__":
    # For local development
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )

