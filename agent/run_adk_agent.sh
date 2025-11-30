#!/bin/bash

# Set BigQuery environment variables if not already set
export BIGQUERY_PROJECT=${BIGQUERY_PROJECT:-"maxprint-479504"}
export BIGQUERY_DATASET=${BIGQUERY_DATASET:-""}
export BIGQUERY_TRELLO_TABLE=${BIGQUERY_TRELLO_TABLE:-"trello_orders"}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run ADK agent (supports both 'adk web' and 'adk run' commands)
# Usage: ./run_adk_agent.sh web    or    ./run_adk_agent.sh run
# Defaults to 'web' if no argument provided
ADK_COMMAND=${1:-web}

# ADK expects a directory containing agent subdirectories
# Run from the project root so it can find adk_trello_agent/
cd "$SCRIPT_DIR"
adk $ADK_COMMAND .

