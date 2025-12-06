# Backend API - Cloud Run Service

This is the FastAPI backend that wraps the ADK Trello Orders Agent for Cloud Run deployment.

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

2. Set environment variables:
```bash
export BIGQUERY_PROJECT="your-project-id"
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GEMINI_MODEL="gemini-2.0-flash-exp"  # optional
```

3. Ensure `agent.py` and `toolbox` are in the project root (one level up)

4. Run the server:
```bash
python main.py
```

The API will be available at `http://localhost:8080`

### Testing

Test the chat endpoint:
```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session-123",
    "message": "How many orders do we have?"
  }'
```

## Deployment to Cloud Run

### Build and Deploy

1. Build the Docker image:
```bash
# From project root
gcloud builds submit --tag gcr.io/PROJECT_ID/trello-orders-api
```

2. Deploy to Cloud Run:
```bash
gcloud run deploy trello-orders-api \
  --image gcr.io/PROJECT_ID/trello-orders-api \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars BIGQUERY_PROJECT=PROJECT_ID,GOOGLE_CLOUD_PROJECT=PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,GEMINI_MODEL=gemini-2.0-flash-exp \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10
```

### Environment Variables

Required:
- `BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT`: Your GCP project ID
- `GOOGLE_CLOUD_LOCATION`: GCP region (default: us-central1)

Optional:
- `GEMINI_MODEL`: Gemini model to use (default: gemini-2.0-flash-exp)
- `APP_NAME`: Application name for session management (default: trello_orders_chat)
- `PORT`: Server port (default: 8080)

### Service Account

The Cloud Run service uses a dedicated read-only service account:
- **Service Account**: `maxprint-agent-readonly@maxprint-479504.iam.gserviceaccount.com`
- **IAM Roles**:
  - `roles/bigquery.dataViewer` (read-only access to BigQuery tables)
  - `roles/bigquery.jobUser` (can run queries)
  - `roles/aiplatform.user` (for Vertex AI / Gemini API access)

This service account is automatically assigned via the `--service-account` flag in `deploy-backend.sh`.

**Security Note**: This service account has read-only access to BigQuery, preventing the agent from accidentally modifying or deleting data.

## API Endpoints

### POST /chat

Send a message to the agent.

**Request:**
```json
{
  "session_id": "unique-session-id",
  "message": "Your question here"
}
```

**Response:**
```json
{
  "reply": "Agent's response"
}
```

### GET /health

Health check endpoint.

### GET /

Root endpoint with service info.

