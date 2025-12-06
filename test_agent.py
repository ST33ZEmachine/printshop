#!/usr/bin/env python3
"""
Local test script for the ADK Trello Orders Agent.

Uses ADK's InMemoryRunner with run_debug() for quick local testing
without needing to deploy to Cloud Run.

Usage:
    python test_agent.py
    
Or with a specific question:
    python test_agent.py "How many orders do we have?"
"""

import asyncio
import sys
import os

# Ensure we have the BIGQUERY_PROJECT set
if not os.environ.get("BIGQUERY_PROJECT"):
    os.environ["BIGQUERY_PROJECT"] = "maxprint-479504"

from agent import root_agent
from google.adk.runners import InMemoryRunner


async def test_agent(question: str = "What data do you have access to?"):
    """Test the agent with a question using run_debug()."""
    print(f"\n{'='*60}")
    print(f"Testing agent with: {question}")
    print(f"{'='*60}\n")
    
    # Create an in-memory runner for local testing
    runner = InMemoryRunner(agent=root_agent)
    
    # Use run_debug for easy testing with verbose mode to see tool calls
    events = await runner.run_debug(
        question,
        user_id="test_user",
        session_id="test_session",
        verbose=True  # Show tool calls and results
    )
    
    print(f"\n{'='*60}")
    print("Test complete!")
    print(f"{'='*60}\n")
    
    return events


async def interactive_mode():
    """Run in interactive mode - keep asking questions."""
    print("\n" + "="*60)
    print("ADK Trello Orders Agent - Interactive Debug Mode")
    print("="*60)
    print("Type 'quit' or 'exit' to stop")
    print("="*60 + "\n")
    
    runner = InMemoryRunner(agent=root_agent)
    
    while True:
        try:
            question = input("\nYou: ").strip()
            if question.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break
            if not question:
                continue
                
            print("\nAgent is thinking...")
            events = await runner.run_debug(
                question,
                user_id="test_user",
                session_id="test_session"
            )
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    import warnings
    import logging
    import contextlib
    
    # Suppress the anyio cleanup warning (cosmetic issue during MCP teardown)
    warnings.filterwarnings("ignore", message=".*cancel scope.*")
    logging.getLogger("anyio").setLevel(logging.CRITICAL)
    
    # Suppress stderr noise during async cleanup
    @contextlib.contextmanager
    def suppress_cleanup_errors():
        """Suppress MCP/anyio cleanup errors that occur after work is done."""
        import io
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            yield
        finally:
            # Check if there was a real error (not just cleanup noise)
            stderr_output = sys.stderr.getvalue()
            sys.stderr = old_stderr
            # Only print if it's NOT the known cleanup error
            if stderr_output and "cancel scope" not in stderr_output and "GeneratorExit" not in stderr_output:
                print(stderr_output, file=sys.stderr)
    
    if len(sys.argv) > 1:
        # Run with provided question
        question = " ".join(sys.argv[1:])
        with suppress_cleanup_errors():
            asyncio.run(test_agent(question))
    else:
        # Run in interactive mode
        with suppress_cleanup_errors():
            asyncio.run(interactive_mode())

