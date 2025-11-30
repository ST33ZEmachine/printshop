#!/bin/bash

# Set BIGQUERY_PROJECT if not already set
export BIGQUERY_PROJECT=${BIGQUERY_PROJECT:-"maxprint-479504"}

# Run the agent
./.venv/bin/python agent.py
