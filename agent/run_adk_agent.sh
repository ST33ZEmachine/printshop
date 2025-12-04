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

# NOTE: This script is for ADK CLI usage (adk web / adk run)
# The agent has been moved to root agent.py for Cloud Run usage.
# If you want to use ADK CLI, you'll need to restore the package structure
# or use the Cloud Run API instead.
#
# For Cloud Run usage, see: backend/README.md
# For local testing, use: python backend/main.py

echo "Warning: ADK CLI requires package structure. Use Cloud Run API instead."
echo "See backend/README.md for local development instructions."
exit 1

