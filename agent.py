"""
ADK Trello Orders Agent

This is an initial Agent Development Kit (ADK) agent that exposes Trello-order
BigQuery data via a structured ADK agent, suitable for use with `adk run` and
`adk web` (ADK Web UI).

It uses MCP BigQuery tools (via toolbox) to handle queries, which automatically
handle table qualification and provide better query capabilities than direct
BigQuery client calls.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

# Load environment variables from .env file
# Try project root first, then current directory
project_root = Path(__file__).parent
load_dotenv(project_root / ".env")  # Project root .env
load_dotenv()  # Also check current directory and parent dirs

# Environment configuration
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT")
if not PROJECT_ID:
    raise ValueError(
        "BIGQUERY_PROJECT environment variable is required. "
        "Set it in your .env file or export it before running the agent."
    )


def _trello_instruction() -> str:
    """System instructions for the Trello orders agent."""
    return """You are a senior data analyst for a print shop.

The business data you work with is exported from a Trello board that tracks
orders made to the business. Each row typically represents a card/order with
fields like name, desc (description), labels, dates and other metadata.

Your goals:
- Help the user understand past work, especially by customer, sport, team,
  product, and time period.
- Always explain which tables and filters you used.
- Prefer high-precision results over broad fuzzy matches.

BigQuery usage guidelines:
- ALWAYS use case-insensitive searches with LOWER() or UPPER().
- For multi-word terms (e.g. 'rugby canada'), search for individual words with
  AND/OR logic instead of a single exact phrase.
- Prefer matches where the main identifying terms appear in the `name` column.
- Treat matches that only appear in `labels` or `desc` as lower confidence and
  call that out explicitly.
- Some columns (like desc) are reserved words: wrap them in backticks, e.g.
  `desc`. When using LOWER(), write LOWER(`desc`).
- When you get noisy results, add additional predicates (for example filtering
  by date, by Trello list/status, or by product keywords) to reduce pollution.
- Use the available BigQuery tools to explore schemas and discover table names
  before writing queries.

When you present results:
- Group and summarize them (counts, totals, key examples) instead of dumping
  raw rows.
- If some rows look off-topic or low confidence, say so and explain why.
- If the data is incomplete (e.g., only one snapshot date), clearly state that
  limitation so the user doesn't over-interpret the results.
"""


# Create MCP BigQuery toolset (same as the original agent uses)
# This connects to the toolbox BigQuery MCP server
# Use absolute path to toolbox to ensure it works regardless of working directory
toolbox_path = project_root / "toolbox"
if not toolbox_path.exists():
    raise FileNotFoundError(
        f"toolbox not found at {toolbox_path}. "
        "Make sure toolbox is in the project root directory."
    )

bigquery_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=str(toolbox_path),
            args=["--prebuilt", "bigquery", "--stdio", "--port", "0"],
            env={**os.environ, "BIGQUERY_PROJECT": PROJECT_ID},
        ),
        timeout=300,  # 5 minutes for long-running queries
    ),
)

trello_orders_agent = Agent(
    name="trello_orders_agent",
    model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp"),
    instruction=_trello_instruction(),
    description=(
        "Analyze Trello-derived BigQuery order data for a print shop. "
        "Uses BigQuery MCP tools to explore and query order data."
    ),
    tools=[bigquery_toolset],
)

# ADK entrypoint: ADK Web/CLI look for this name
root_agent = trello_orders_agent
