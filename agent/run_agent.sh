#!/bin/bash

# Set BigQuery environment variables if not already set
export BIGQUERY_PROJECT=${BIGQUERY_PROJECT:-"maxprint-479504"}
export BIGQUERY_DATASET=${BIGQUERY_DATASET:-""}
export BIGQUERY_TRELLO_TABLE=${BIGQUERY_TRELLO_TABLE:-"trello_orders"}

# Run the agent
./.venv/bin/python agent.py
