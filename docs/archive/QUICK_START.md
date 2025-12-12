# Quick Start Guide

## What Information Do I Need?

To deploy to Cloud Run and Firebase Hosting, I need:

### Required:
1. **GCP Project ID** - Your Google Cloud Project ID
   - Run: `gcloud config get-value project`
   - Or find it in [GCP Console](https://console.cloud.google.com)

2. **Firebase Project ID** - Can be the same as GCP Project ID
   - Run: `firebase projects:list`
   - Or create one at [Firebase Console](https://console.firebase.google.com)

### Optional (has defaults):
3. **Region** - Default: `us-central1`
4. **Gemini Model** - Default: `gemini-2.0-flash-exp`

## Easy Setup (Recommended)

Run the configuration script:

```bash
./configure-deployment.sh
```

This will:
- Ask for your project IDs and preferences
- Update all configuration files automatically
- Set up CORS for Firebase domains
- Create a `.env.example` file

## Manual Setup

If you prefer to configure manually:

### 1. Update `deploy-backend.sh`
```bash
# Edit the default PROJECT_ID and REGION
nano deploy-backend.sh
```

### 2. Update `frontend/.firebaserc`
```json
{
  "projects": {
    "default": "your-firebase-project-id"
  }
}
```

### 3. Update `backend/main.py` CORS
Add your Firebase domains to the `allow_origins` list:
```python
allow_origins=[
    "https://your-project-id.web.app",
    "https://your-project-id.firebaseapp.com",
    "http://localhost:3000",
]
```

## After Configuration

### Deploy Backend
```bash
./deploy-backend.sh
```

This will output a Cloud Run URL like:
```
https://trello-orders-api-xxxxx-uc.a.run.app
```

### Update Frontend with Backend URL
Edit `frontend/script.js`:
```javascript
const API_URL = 'https://trello-orders-api-xxxxx-uc.a.run.app';
```

### Deploy Frontend
```bash
cd frontend
firebase deploy --only hosting
```

## Verify Deployment

1. **Backend Health Check:**
   ```bash
   curl https://your-service-url.run.app/health
   ```

2. **Frontend:**
   - Visit: `https://your-project-id.web.app`
   - Open browser console to check for errors

## Troubleshooting

### "Project not found"
- Ensure you're logged in: `gcloud auth login`
- Set the project: `gcloud config set project YOUR_PROJECT_ID`

### "Firebase not initialized"
- Run: `firebase login`
- Initialize: `cd frontend && firebase init hosting`

### CORS Errors
- Verify Firebase domains are in `backend/main.py` CORS settings
- Redeploy backend after updating CORS

## Need Help?

Check the detailed guides:
- `README.md` - Full architecture and deployment guide
- `DEPLOYMENT_GUIDE.md` - Detailed deployment instructions
- `backend/README.md` - Backend-specific guide
- `frontend/README.md` - Frontend-specific guide



