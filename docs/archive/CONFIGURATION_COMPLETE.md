# ✅ Configuration Complete

## Your Configuration

### Firebase Project
- **Firebase Project ID**: `maxprint-61206`
- **Firebase Hosting URLs**:
  - `https://maxprint-61206.web.app`
  - `https://maxprint-61206.firebaseapp.com`

### Google Cloud Project
- **GCP Project ID**: `maxprint-479504` (from your gcloud config)
- **Region**: `us-central1` (default)

## Files Updated

✅ **frontend/.firebaserc** - Set to `maxprint-61206`
✅ **backend/main.py** - CORS configured for Firebase domains

## Next Steps

### 1. Deploy Backend to Cloud Run

```bash
./deploy-backend.sh maxprint-479504
```

Or if you want to specify a different region:

```bash
./deploy-backend.sh maxprint-479504 trello-orders-api us-central1
```

**Note**: The script will use `maxprint-479504` as the GCP project. If your Firebase project uses a different GCP project, update the script accordingly.

After deployment, you'll get a Cloud Run URL like:
```
https://trello-orders-api-xxxxx-uc.a.run.app
```

### 2. Update Frontend with Backend URL

After the backend is deployed, edit `frontend/script.js`:

```javascript
// Update this line with your Cloud Run service URL
const API_URL = 'https://trello-orders-api-xxxxx-uc.a.run.app';
```

### 3. Deploy Frontend to Firebase Hosting

```bash
cd frontend
firebase deploy --only hosting
```

Your app will be available at:
- `https://maxprint-61206.web.app`
- `https://maxprint-61206.firebaseapp.com`

## Important Notes

### GCP Project vs Firebase Project

Your Firebase project (`maxprint-61206`) might be different from your GCP project (`maxprint-479504`). 

**If they're different:**
- The backend will deploy to GCP project `maxprint-479504`
- The frontend will deploy to Firebase project `maxprint-61206`
- Make sure both projects have the necessary permissions and billing enabled

**If they should be the same:**
- Update `deploy-backend.sh` to use `maxprint-61206` instead
- Or link your Firebase project to the correct GCP project

### Verify Firebase Project Link

Check if your Firebase project is linked to the correct GCP project:

```bash
firebase projects:list
```

If needed, you can link them:
1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project
3. Go to Project Settings → General
4. Check the "Default GCP resource location"

## Testing Locally

Before deploying, test locally:

### Backend
```bash
cd backend
export BIGQUERY_PROJECT="maxprint-479504"
export GOOGLE_CLOUD_PROJECT="maxprint-479504"
python main.py
```

### Frontend
```bash
cd frontend
# Update script.js: const API_URL = 'http://localhost:8080'
python3 -m http.server 3000
```

Visit `http://localhost:3000` to test.

## Troubleshooting

### "Project not found" error
- Ensure you're logged in: `gcloud auth login`
- Set the project: `gcloud config set project maxprint-479504`
- For Firebase: `firebase login`

### CORS errors after deployment
- Verify Firebase domains are in `backend/main.py` CORS settings
- Redeploy backend after any CORS changes

### Different GCP projects
If your Firebase project uses a different GCP project than `maxprint-479504`:
1. Update `deploy-backend.sh` with the correct project ID
2. Or create a Cloud Run service in the Firebase project's GCP project



