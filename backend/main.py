"""
Cloud Run API wrapper for ADK Trello Orders Agent

This FastAPI application wraps the existing ADK agent and provides a simple
HTTP API endpoint for chat interactions with session management.
"""

import logging
import os
import time
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import bigquery
from integrations.trello.config import TrelloSettings
from integrations.trello.publisher import LoggingTrelloEventPublisher
from integrations.trello.router import get_trello_router

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

# BigQuery configuration
DATASET_ID = "trello_rag"
CARDS_TABLE = "bourquin_05122025_snapshot"
LINEITEMS_TABLE = "bourquin_05122025_snapshot_lineitems"

# Initialize BigQuery client
bigquery_client = bigquery.Client(project=PROJECT_ID)

# Simple in-memory cache for query results (5 minute TTL)
query_cache: Dict[str, tuple[Any, float]] = {}
CACHE_TTL = 300  # 5 minutes


def get_cached_or_query(cache_key: str, query_func):
    """Get result from cache or execute query function."""
    now = time.time()
    if cache_key in query_cache:
        result, timestamp = query_cache[cache_key]
        if now - timestamp < CACHE_TTL:
            logger.debug(f"Cache hit for {cache_key}")
            return result
    
    # Cache miss or expired, execute query
    logger.debug(f"Cache miss for {cache_key}, executing query")
    result = query_func()
    query_cache[cache_key] = (result, now)
    return result


def query_monthly_revenue_by_business_line() -> List[Dict[str, Any]]:
    """Query monthly revenue grouped by business line."""
    query = f"""
    SELECT 
        c.year_month,
        li.business_line,
        SUM(li.total_revenue) as revenue,
        COUNT(DISTINCT li.card_id) as order_count
    FROM `{PROJECT_ID}.{DATASET_ID}.{LINEITEMS_TABLE}` li
    JOIN `{PROJECT_ID}.{DATASET_ID}.{CARDS_TABLE}` c ON li.card_id = c.card_id
    WHERE li.business_line IS NOT NULL 
      AND li.total_revenue IS NOT NULL
      AND c.year_month IS NOT NULL
    GROUP BY c.year_month, li.business_line
    ORDER BY c.year_month DESC, li.business_line
    """
    
    results = bigquery_client.query(query).result()
    return [
        {
            "year_month": row.year_month,
            "business_line": row.business_line,
            "revenue": float(row.revenue) if row.revenue else 0.0,
            "order_count": row.order_count
        }
        for row in results
    ]


def query_top_customers(limit: int = 20) -> List[Dict[str, Any]]:
    """Query top customers by total revenue."""
    query = f"""
    SELECT 
        c.purchaser,
        SUM(li.total_revenue) as total_revenue,
        COUNT(DISTINCT li.card_id) as order_count,
        COUNT(li.card_id) as line_item_count
    FROM `{PROJECT_ID}.{DATASET_ID}.{LINEITEMS_TABLE}` li
    JOIN `{PROJECT_ID}.{DATASET_ID}.{CARDS_TABLE}` c ON li.card_id = c.card_id
    WHERE c.purchaser IS NOT NULL 
      AND c.purchaser != ''
      AND li.total_revenue IS NOT NULL
    GROUP BY c.purchaser
    ORDER BY total_revenue DESC
    LIMIT {limit}
    """
    
    results = bigquery_client.query(query).result()
    return [
        {
            "purchaser": row.purchaser,
            "total_revenue": float(row.total_revenue) if row.total_revenue else 0.0,
            "order_count": row.order_count,
            "line_item_count": row.line_item_count
        }
        for row in results
    ]


def query_revenue_trends() -> List[Dict[str, Any]]:
    """Query revenue trends over time (monthly)."""
    query = f"""
    SELECT 
        c.year_month,
        SUM(li.total_revenue) as total_revenue,
        COUNT(DISTINCT li.card_id) as order_count,
        COUNT(li.card_id) as line_item_count
    FROM `{PROJECT_ID}.{DATASET_ID}.{LINEITEMS_TABLE}` li
    JOIN `{PROJECT_ID}.{DATASET_ID}.{CARDS_TABLE}` c ON li.card_id = c.card_id
    WHERE li.total_revenue IS NOT NULL
      AND c.year_month IS NOT NULL
    GROUP BY c.year_month
    ORDER BY c.year_month DESC
    """
    
    results = bigquery_client.query(query).result()
    return [
        {
            "year_month": row.year_month,
            "total_revenue": float(row.total_revenue) if row.total_revenue else 0.0,
            "order_count": row.order_count,
            "line_item_count": row.line_item_count
        }
        for row in results
    ]


def query_order_status() -> List[Dict[str, Any]]:
    """Query order counts by status (using closed flag as proxy)."""
    query = f"""
    SELECT 
        IFNULL(CAST(closed AS STRING), 'unknown') AS status,
        COUNT(*) AS order_count
    FROM `{PROJECT_ID}.{DATASET_ID}.{CARDS_TABLE}`
    GROUP BY status
    ORDER BY order_count DESC
    """
    
    results = bigquery_client.query(query).result()
    return [
        {
            "status": row.status,
            "order_count": row.order_count
        }
        for row in results
    ]


def query_material_breakdown(limit: int = 20) -> List[Dict[str, Any]]:
    """Query revenue breakdown by material type."""
    query = f"""
    SELECT 
        li.material,
        SUM(li.total_revenue) as total_revenue,
        COUNT(DISTINCT li.card_id) as order_count,
        COUNT(li.card_id) as line_item_count
    FROM `{PROJECT_ID}.{DATASET_ID}.{LINEITEMS_TABLE}` li
    WHERE li.material IS NOT NULL 
      AND li.material != ''
      AND li.total_revenue IS NOT NULL
    GROUP BY li.material
    ORDER BY total_revenue DESC
    LIMIT {limit}
    """
    
    results = bigquery_client.query(query).result()
    return [
        {
            "material": row.material,
            "total_revenue": float(row.total_revenue) if row.total_revenue else 0.0,
            "order_count": row.order_count,
            "line_item_count": row.line_item_count
        }
        for row in results
    ]

# Trello webhook integration
try:
    trello_settings = TrelloSettings()
    trello_publisher = LoggingTrelloEventPublisher()
    app.include_router(get_trello_router(publisher=trello_publisher))
    logger.info("Trello webhook route registered.")
except Exception as exc:
    logger.warning(
        "Trello settings not configured; Trello webhook route disabled.",
        exc_info=exc,
    )


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


# Dashboard API endpoints
@app.get("/api/dashboard/monthly-revenue-by-business-line")
async def get_monthly_revenue_by_business_line():
    """Get monthly revenue grouped by business line."""
    try:
        data = get_cached_or_query(
            "monthly_revenue_by_business_line",
            query_monthly_revenue_by_business_line
        )
        return {"data": data}
    except Exception as e:
        logger.exception(f"Error querying monthly revenue by business line: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/top-customers")
async def get_top_customers(limit: int = 20):
    """Get top customers by revenue."""
    try:
        cache_key = f"top_customers_{limit}"
        data = get_cached_or_query(
            cache_key,
            lambda: query_top_customers(limit)
        )
        return {"data": data}
    except Exception as e:
        logger.exception(f"Error querying top customers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/revenue-trends")
async def get_revenue_trends():
    """Get revenue trends over time."""
    try:
        data = get_cached_or_query(
            "revenue_trends",
            query_revenue_trends
        )
        return {"data": data}
    except Exception as e:
        logger.exception(f"Error querying revenue trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/order-status")
async def get_order_status():
    """Get order counts by status."""
    try:
        data = get_cached_or_query(
            "order_status",
            query_order_status
        )
        return {"data": data}
    except Exception as e:
        logger.exception(f"Error querying order status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dashboard/material-breakdown")
async def get_material_breakdown(limit: int = 20):
    """Get revenue breakdown by material type."""
    try:
        cache_key = f"material_breakdown_{limit}"
        data = get_cached_or_query(
            cache_key,
            lambda: query_material_breakdown(limit)
        )
        return {"data": data}
    except Exception as e:
        logger.exception(f"Error querying material breakdown: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

