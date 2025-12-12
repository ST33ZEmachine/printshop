# Backend API - Cloud Run Service

This is the FastAPI backend that wraps the ADK Trello Orders Agent for Cloud Run deployment.

## Features

- **Chat API**: LLM-powered chat interface for querying Trello order data
- **Trello Webhooks**: Real-time webhook processing for Trello board events
- **BigQuery Integration**: Automatic data extraction and storage

## Local Development

### Prerequisites

- Python 3.11+
- Google Cloud credentials configured (`gcloud auth application-default login`)
- Environment variables set (see below)

### Setup

1. Install dependencies:
```bash
cd backend
pip install -r requirements.txt
```

2. Set environment variables in `.env` file (project root):
```bash
BIGQUERY_PROJECT=your-project-id
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GEMINI_MODEL=gemini-2.0-flash-exp  # optional
TRELLO_KEY=your-trello-key
TRELLO_TOKEN=your-trello-token
TRELLO_WEBHOOK_CALLBACK_URL=https://your-service.run.app/trello/webhook
```

3. Ensure `agent.py` and `toolbox` are in the project root (one level up)

4. Run the server:
```bash
python main.py
```

The API will be available at `http://localhost:8080`

## API Endpoints

### POST /chat

Send a message to the agent.

**Request:**
```json
{
  "session_id": "unique-session-id",
  "message": "How many orders do we have?"
}
```

**Response:**
```json
{
  "reply": "Based on the data, you have 1,234 orders..."
}
```

### POST /trello/webhook

Receive Trello webhook events (automatically processes card updates).

### GET /health

Health check endpoint for Cloud Run.

## Trello Webhook Integration

### Registering Webhooks

**For Bourquin Signs board:**
```bash
python register_bourquin_webhook.py
```

**General webhook management:**
```bash
python trello_webhook_cli.py list          # List all webhooks
python trello_webhook_cli.py register      # Register a webhook
python trello_webhook_cli.py delete <id>   # Delete a webhook
```

See `WEBHOOK_SETUP_GUIDE.md` in project root for detailed setup instructions.

## Deployment to Cloud Run

### Build and Deploy

Use the deployment script from project root:
```bash
./deploy-backend.sh maxprint-479504 trello-orders-api us-central1
```

Or manually:
```bash
# Build
gcloud builds submit --config cloudbuild.yaml --project maxprint-479504 .

# Deploy
gcloud run deploy trello-orders-api \
  --image gcr.io/maxprint-479504/trello-orders-api:latest \
  --platform managed \
  --region us-central1 \
  --project maxprint-479504 \
  --allow-unauthenticated \
  --set-env-vars BIGQUERY_PROJECT=maxprint-479504,GOOGLE_CLOUD_PROJECT=maxprint-479504,GOOGLE_CLOUD_LOCATION=us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10
```

### Environment Variables

**Required:**
- `BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT`: Your GCP project ID
- `GOOGLE_CLOUD_LOCATION`: GCP region (default: us-central1)

**Optional:**
- `GEMINI_MODEL`: Gemini model to use (default: gemini-2.0-flash-exp)
- `APP_NAME`: Application name for session management (default: trello_orders_chat)
- `PORT`: Server port (default: 8080)
- `TRELLO_KEY`: Trello API key (required for webhook integration)
- `TRELLO_TOKEN`: Trello API token (required for webhook integration)
- `TRELLO_WEBHOOK_CALLBACK_URL`: Public callback URL for Trello webhooks

## Testing

### Test Trello Access

```bash
python test_trello_access.py                    # List all accessible boards
python test_trello_access.py --board-id <id>   # Test specific board
```

### Test BigQuery Client

```bash
python test_bigquery_client.py
```

## Project Structure

```
backend/
├── integrations/
│   └── trello/
│       ├── bigquery_client.py    # BigQuery operations for webhooks
│       ├── config.py             # Trello configuration
│       ├── models.py             # Pydantic models for webhooks
│       ├── publisher.py          # Event publisher (BigQuery)
│       ├── router.py             # FastAPI routes for webhooks
│       └── service.py            # Trello API client
├── main.py                       # FastAPI application
├── register_bourquin_webhook.py  # Register webhook for Bourquin board
├── trello_webhook_cli.py          # General webhook management CLI
├── setup_webhook_tables.py        # Create BigQuery tables
└── test_*.py                     # Test utilities
```

## Documentation

- `WEBHOOK_SETUP_GUIDE.md` - Webhook setup instructions
- `WEBHOOK_ARCHITECTURE_FINAL.md` - Architecture documentation
- `TRELLO_READ_ONLY_AUDIT.md` - Confirmation of read-only operations
