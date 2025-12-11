# Deployment Guide & Recommendations

## Answers to Your Questions

### 1. ✅ Agent Selection
- **Done**: Moved `agent/adk_trello_agent/agent.py` to root `agent.py`
- **Done**: Deleted old `agent/agent.py`
- The ADK agent is now at the project root and ready to use

### 2. ✅ Session Management
- **Implemented**: Each `session_id` maintains its own conversation history
- Uses Vertex AI Session Service for persistent sessions across requests
- Frontend automatically generates and persists session IDs in localStorage

### 3. 📋 Recommended Environment Variables for Cloud Run

**Required:**
- `BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT`: Your GCP project ID
- `GOOGLE_CLOUD_LOCATION`: GCP region (e.g., `us-central1`)

**Optional but Recommended:**
- `GEMINI_MODEL`: Gemini model version (default: `gemini-2.0-flash-exp`)
- `APP_NAME`: Application identifier for session management (default: `trello_orders_chat`)

**Set via gcloud:**
```bash
gcloud run services update trello-orders-api \
  --set-env-vars BIGQUERY_PROJECT=PROJECT_ID,GOOGLE_CLOUD_PROJECT=PROJECT_ID,GOOGLE_CLOUD_LOCATION=us-central1,GEMINI_MODEL=gemini-2.0-flash-exp
```

### 4. 🔧 Toolbox Binary Decision

**Recommendation: Include in Docker Image** ✅

**Why:**
- The `toolbox` binary is required for MCP BigQuery tools
- It's not available in Cloud Run by default
- Including it ensures consistent behavior across environments
- The binary is small and doesn't significantly impact image size

**Implementation:**
- ✅ Dockerfile copies `toolbox` from project root
- ✅ Binary is made executable in the container
- ✅ Path is correctly configured in `agent.py`

**Alternative (if needed):**
If you prefer to use a pre-installed toolbox in Cloud Run:
1. Create a custom base image with toolbox pre-installed
2. Or use a Cloud Build step to download toolbox during build
3. Update `agent.py` to use the new path

### 5. 📝 ADK Agent Invocation

**How it works:**
The backend uses the ADK `Runner` class with `VertexAiSessionService`:

```python
from google.adk import Runner
from google.adk.sessions import VertexAiSessionService
from google.genai import types

# Initialize session service
session_service = VertexAiSessionService(
    project=PROJECT_ID,
    location=LOCATION,
)

# Create runner with your agent
runner = Runner(
    agent=root_agent,  # From agent.py
    app_name=APP_NAME,
    session_service=session_service,
)

# Invoke agent for each message
user_content = types.Content(
    role="user",
    parts=[types.Part.from_text(message)]
)

async for event in runner.run_async(
    user_id=session_id,
    session_id=session_id,
    new_message=user_content
):
    # Collect response text
    if event.content and event.content.parts:
        for part in event.content.parts:
            if hasattr(part, 'text') and part.text:
                response_text += part.text
```

This is exactly how `adk run` and `adk web` invoke agents internally.

## Quick Deployment Checklist

### Backend (Cloud Run)

- [ ] Set `BIGQUERY_PROJECT` environment variable
- [ ] Ensure service account has required IAM roles:
  - `roles/bigquery.dataViewer`
  - `roles/bigquery.jobUser`
  - `roles/aiplatform.user`
- [ ] Build Docker image: `gcloud builds submit --tag gcr.io/PROJECT_ID/trello-orders-api`
- [ ] Deploy: Use `deploy-backend.sh` or manual `gcloud run deploy`
- [ ] Note the service URL for frontend configuration

### Frontend (Firebase Hosting)

- [ ] Update `frontend/script.js` with Cloud Run service URL
- [ ] Update `frontend/.firebaserc` with Firebase project ID
- [ ] Deploy: `firebase deploy --only hosting`
- [ ] Update backend CORS settings with Firebase domain
- [ ] Redeploy backend if CORS was updated

## Testing

### Local Testing

1. **Backend:**
   ```bash
   cd backend
   export BIGQUERY_PROJECT="your-project"
   python main.py
   ```

2. **Frontend:**
   ```bash
   cd frontend
   # Update script.js: const API_URL = 'http://localhost:8080'
   python3 -m http.server 3000
   ```

3. **Test API:**
   ```bash
   curl -X POST http://localhost:8080/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id": "test", "message": "Hello"}'
   ```

### Production Testing

1. Verify health endpoint: `curl https://your-service.run.app/health`
2. Test chat endpoint with a real query
3. Check Cloud Run logs for errors
4. Verify session persistence across multiple requests

## Troubleshooting

### Common Issues

1. **Import Error: `No module named 'agent'`**
   - Solution: Ensure `agent.py` is in project root
   - Verify Dockerfile copies `agent.py` correctly

2. **Toolbox Not Found**
   - Solution: Check `toolbox` exists in project root
   - Verify Dockerfile copies and makes it executable

3. **CORS Errors**
   - Solution: Update `backend/main.py` CORS origins
   - Redeploy backend after changes

4. **Session Not Persisting**
   - Solution: Check service account has `roles/aiplatform.user`
   - Verify `GOOGLE_CLOUD_PROJECT` is set correctly

5. **BigQuery Access Denied**
   - Solution: Verify service account IAM roles
   - Check `BIGQUERY_PROJECT` matches your project

## Next Steps

1. **Review the code** in `backend/main.py` and `frontend/script.js`
2. **Test locally** before deploying
3. **Deploy backend** first, get the service URL
4. **Update frontend** with the service URL
5. **Deploy frontend** to Firebase Hosting
6. **Update CORS** in backend if needed
7. **Test end-to-end** in production

## Support

For issues:
- Check Cloud Run logs: `gcloud run services logs read trello-orders-api`
- Review backend/frontend README files
- Verify environment variables are set correctly


