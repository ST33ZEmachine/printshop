# Trello Orders Chat - Cloud Run + Firebase Hosting

A minimal web application stack that wraps an existing Google Agents SDK (ADK) agent in a Cloud Run API with a Firebase Hosting chat UI.

## Architecture

```
┌─────────────────┐
│  User Browser   │
└────────┬────────┘
         │
         │ HTTPS
         ▼
┌─────────────────┐
│ Firebase Hosting│  (Static UI)
│  (Frontend)     │
└────────┬────────┘
         │
         │ API Calls
         ▼
┌─────────────────┐
│   Cloud Run     │  (FastAPI Backend)
│   (Backend)     │
└────────┬────────┘
         │
         │ ADK Agent
         ▼
┌─────────────────┐
│  Google ADK     │
│     Agent       │
└────────┬────────┘
         │
         │ MCP Tools
         ▼
┌─────────────────┐
│    BigQuery     │
│   (via MCP)     │
└─────────────────┘
```

## Project Structure

```
maxPrint/
├── agent.py                 # ADK agent
├── backend/                 # Cloud Run API
│   ├── main.py             # FastAPI application
│   ├── requirements.txt    # Python dependencies
│   ├── Dockerfile          # Container image definition
│   ├── integrations/       # Trello webhook integration
│   │   └── trello/         # Webhook processing, BigQuery client
│   ├── setup_webhook_tables.py  # BigQuery table setup
│   ├── register_bourquin_webhook.py  # Webhook registration
│   └── README.md           # Backend deployment guide
├── frontend/               # Firebase Hosting UI
│   ├── index.html          # Chat interface
│   ├── script.js           # Client-side logic
│   ├── styles.css          # Styling
│   ├── firebase.json       # Firebase config
│   └── README.md           # Frontend deployment guide
├── extractionPipeline/     # Data extraction scripts
│   ├── extract_trello_data.py  # Batch extraction
│   ├── extract_single_card.py  # Single card extraction
│   └── ...
├── scripts/                # Utility and evaluation scripts
│   ├── eval_queries.py    # Agent evaluation
│   ├── eval_extraction_accuracy.py  # Extraction validation
│   └── README.md          # Scripts documentation
├── docs/                   # Documentation
│   └── archive/            # Historical/one-time docs
├── cloudbuild.yaml         # Cloud Build configuration
├── deploy-backend.sh       # Deployment script
├── test_agent.py           # Local agent testing
└── README.md               # This file
```

**Note**: The `toolbox` binary (MCP BigQuery server) is automatically downloaded during Docker build, not stored in the repository.

## Quick Start

### Prerequisites

- Google Cloud Project with billing enabled
- Firebase project (can be same as GCP project)
- `gcloud` CLI installed and authenticated
- `firebase` CLI installed
- Python 3.11+ for local development
- Docker (for building container images)

### 1. Local Development

#### Backend

```bash
cd backend
pip install -r requirements.txt

# Set environment variables
export BIGQUERY_PROJECT="your-project-id"
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"

# Run server
python main.py
```

Backend will be available at `http://localhost:8080`

#### Frontend

```bash
cd frontend

# Update script.js with backend URL
# const API_URL = 'http://localhost:8080';

# Serve locally (choose one):
python3 -m http.server 3000
# OR
firebase serve --only hosting
```

Open `http://localhost:3000` in your browser.

### 2. Deploy Backend to Cloud Run

#### Using the Deployment Script (Recommended)

```bash
# From project root
./deploy-backend.sh [PROJECT_ID] [SERVICE_NAME] [REGION]

# Example:
./deploy-backend.sh maxprint-479504 trello-orders-api us-central1
```

The script will:
1. Build the Docker image using `cloudbuild.yaml`
2. Deploy to Cloud Run with the correct service account
3. Set all required environment variables

#### Manual Deployment

If you prefer to deploy manually:

```bash
# Build and push Docker image
gcloud builds submit --config cloudbuild.yaml --project PROJECT_ID .

# Deploy to Cloud Run
gcloud run deploy trello-orders-api \
  --image gcr.io/PROJECT_ID/trello-orders-api:latest \
  --platform managed \
  --region us-central1 \
  --project PROJECT_ID \
  --service-account maxprint-agent-readonly@PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --set-env-vars BIGQUERY_PROJECT=PROJECT_ID,GOOGLE_CLOUD_PROJECT=PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,GEMINI_MODEL=gemini-2.5-flash,GOOGLE_GENAI_USE_VERTEXAI=true \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10
```

**Important**: Replace `PROJECT_ID` with your actual GCP project ID.

#### Required IAM Roles for Service Account

- `roles/bigquery.dataViewer`
- `roles/bigquery.jobUser`
- `roles/aiplatform.user`

#### Get Service URL

After deployment, note the service URL:
```bash
gcloud run services describe trello-orders-api --region us-central1 --format 'value(status.url)'
```

### 3. Deploy Frontend to Firebase Hosting

#### Configure Firebase

```bash
cd frontend

# Update .firebaserc with your Firebase project ID
# Update script.js with your Cloud Run service URL
```

#### Deploy

```bash
firebase deploy --only hosting
```

Your app will be available at:
- `https://PROJECT_ID.web.app`
- `https://PROJECT_ID.firebaseapp.com`

### 4. Update CORS in Backend (if needed)

The backend CORS settings are configured in `backend/main.py`. If your Firebase project ID differs from the hardcoded values, update the `allow_origins` list:

Edit `backend/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://YOUR_PROJECT_ID.web.app",
        "https://YOUR_PROJECT_ID.firebaseapp.com",
        "http://localhost:3000",  # For local development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Then rebuild and redeploy the backend.

## Environment Variables

### Backend (Cloud Run)

**Required:**
- `BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT`: Your GCP project ID
- `GOOGLE_CLOUD_LOCATION`: GCP region (default: `us-central1`)

**Optional:**
- `GEMINI_MODEL`: Gemini model to use (default: `gemini-2.5-flash`)
- `APP_NAME`: Application name for session management (default: `trello_orders_chat`)
- `PORT`: Server port (default: `8080`)
- `TRELLO_KEY`: Trello API key (required for webhook integration)
- `TRELLO_TOKEN`: Trello API token (required for webhook integration)
- `TRELLO_WEBHOOK_CALLBACK_URL`: Public callback URL for Trello webhooks

### Frontend

Update `script.js`:
```javascript
const API_URL = 'https://your-service-xxxxx-uc.a.run.app';
```

## API Reference

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
  "reply": "Based on the data, you have 1,234 orders in total..."
}
```

**Example:**
```bash
curl -X POST https://your-service-xxxxx-uc.a.run.app/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session-123",
    "message": "Show me orders for customer X"
  }'
```

### POST /trello/webhook

Receive Trello webhook events. Automatically processes card creation and updates.

**Note**: See [Webhook Setup Guide](WEBHOOK_SETUP_GUIDE.md) for registration instructions.

### GET /

Root endpoint with service information.

**Response:**
```json
{
  "status": "ok",
  "service": "trello_orders_chat",
  "version": "1.0.0"
}
```

### GET /health

Health check endpoint for Cloud Run.

**Response:**
```json
{
  "status": "healthy"
}
```

### GET /sessions

List active chat sessions (for monitoring/debugging).

**Response:**
```json
{
  "active_sessions": ["session-id-1", "session-id-2"],
  "count": 2
}
```

## Session Management

Each `session_id` maintains its own conversation history via Vertex AI Session Service. The frontend automatically generates and persists a session ID in localStorage, ensuring continuity across page reloads.

## Documentation

### Core Documentation

- **[Backend README](backend/README.md)** - Backend API documentation, deployment, and webhook management
- **[Frontend README](frontend/README.md)** - Frontend deployment and configuration

### Trello Webhook Pipeline

The project includes a real-time webhook pipeline that captures Trello board events and processes them automatically:

- **[Webhook Setup Guide](WEBHOOK_SETUP_GUIDE.md)** - Step-by-step guide for setting up and registering Trello webhooks
- **[Webhook Architecture](WEBHOOK_ARCHITECTURE_FINAL.md)** - Complete architecture documentation including table schemas, data flow, and query patterns
- **[Trello Read-Only Audit](backend/TRELLO_READ_ONLY_AUDIT.md)** - Confirmation that all Trello API operations are read-only

### Archived Documentation

Historical and one-time setup documentation has been moved to `docs/archive/`:

- Configuration checklists and completion records
- Deployment permissions guides
- Historical improvement logs and audits
- Development journal

The following webhook planning documents are kept in root for reference:

- `WEBHOOK_PIPELINE_PLAN.md` - Initial planning document
- `WEBHOOK_IMPLEMENTATION_PLAN.md` - Implementation checklist (now complete)

## Toolbox Binary

The `toolbox` binary (MCP BigQuery server) is automatically downloaded during the Docker build process. The Dockerfile downloads the Linux AMD64 version from Google Cloud Storage, so no manual setup is required.

## Troubleshooting

### CORS Errors

If you see CORS errors in the browser console:
1. Verify your Firebase domain is in the backend's `allow_origins` list
2. Ensure the backend is deployed with the updated CORS settings
3. Check that the frontend is using the correct API URL

### Session Not Persisting

- Sessions are managed by Vertex AI Session Service
- Ensure the Cloud Run service account has `roles/aiplatform.user`
- Check Cloud Run logs for session-related errors

### Toolbox Not Found

- Ensure `toolbox` exists in the project root
- Verify the Dockerfile copies the toolbox binary
- Check that the binary is executable (`chmod +x toolbox`)

### BigQuery Access Issues

- Verify the service account has BigQuery permissions
- Check that `BIGQUERY_PROJECT` environment variable is set correctly
- Review BigQuery audit logs for access denials

## Development Workflow

1. **Make changes to agent**: Edit `agent.py` in project root
2. **Test locally**: Run backend and frontend locally
3. **Deploy backend**: Build and deploy to Cloud Run
4. **Deploy frontend**: Deploy to Firebase Hosting
5. **Test production**: Verify end-to-end functionality

## Cost Considerations

- **Cloud Run**: Pay per request and compute time (generous free tier)
- **Firebase Hosting**: Free tier includes 10GB storage and 360MB/day transfer
- **Vertex AI**: Pay per API call to Gemini models
- **BigQuery**: Pay per query (first 1TB/month free)

## Security Notes

- The backend is currently set to `allow-unauthenticated` for MVP
- In production, consider:
  - Adding authentication (Firebase Auth, API keys, etc.)
  - Restricting CORS to specific domains
  - Rate limiting
  - Input validation and sanitization

## Support

For issues or questions:
1. Check the backend and frontend README files
2. Review Cloud Run logs: `gcloud run services logs read trello-orders-api`
3. Check Firebase Hosting logs in Firebase Console

## License

[Your License Here]


