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
├── agent.py                 # ADK agent (moved from agent/adk_trello_agent/)
├── toolbox                  # MCP BigQuery server binary
├── backend/                 # Cloud Run API
│   ├── main.py             # FastAPI application
│   ├── requirements.txt    # Python dependencies
│   ├── Dockerfile          # Container image definition
│   └── README.md           # Backend deployment guide
├── frontend/               # Firebase Hosting UI
│   ├── index.html          # Chat interface
│   ├── script.js           # Client-side logic
│   ├── styles.css          # Styling
│   ├── firebase.json       # Firebase config
│   └── README.md           # Frontend deployment guide
└── README.md               # This file
```

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

#### Build and Push Docker Image

```bash
# From project root
gcloud builds submit --tag gcr.io/PROJECT_ID/trello-orders-api
```

#### Deploy to Cloud Run

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
  --max-instances 10 \
  --service-account YOUR_SERVICE_ACCOUNT@PROJECT_ID.iam.gserviceaccount.com
```

**Important**: Replace `PROJECT_ID` and `YOUR_SERVICE_ACCOUNT` with your actual values.

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

### 4. Update CORS in Backend

After deploying the frontend, update the backend CORS settings to allow your Firebase domain:

Edit `backend/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://PROJECT_ID.web.app",
        "https://PROJECT_ID.firebaseapp.com"
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
- `GEMINI_MODEL`: Gemini model to use (default: `gemini-2.0-flash-exp`)
- `APP_NAME`: Application name for session management (default: `trello_orders_chat`)
- `PORT`: Server port (default: `8080`)

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

### GET /health

Health check endpoint for Cloud Run.

**Response:**
```json
{
  "status": "healthy"
}
```

## Session Management

Each `session_id` maintains its own conversation history via Vertex AI Session Service. The frontend automatically generates and persists a session ID in localStorage, ensuring continuity across page reloads.

## Toolbox Binary

The `toolbox` binary (MCP BigQuery server) is included in the Docker image. It's copied from the project root during the build process. Ensure the binary is executable and compatible with the Cloud Run container architecture (Linux x86_64 or ARM64).

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


