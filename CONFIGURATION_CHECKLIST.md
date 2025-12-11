# Configuration Checklist

Please provide the following information to complete the deployment setup:

## Required Information

### 1. Google Cloud Project Details
- [ ] **GCP Project ID**: `_________________`
  - Example: `maxprint-479504`
  - Find it: `gcloud config get-value project` or [GCP Console](https://console.cloud.google.com)

- [ ] **Preferred Region**: `_________________`
  - Default: `us-central1`
  - Options: `us-central1`, `us-east1`, `us-west1`, `europe-west1`, `asia-east1`, etc.

### 2. Firebase Project
- [ ] **Firebase Project ID**: `_________________`
  - Can be the same as GCP Project ID
  - Or create a new Firebase project: [Firebase Console](https://console.firebase.google.com)
  - Find it: `firebase projects:list`

### 3. Service Account (Optional but Recommended)
- [ ] **Service Account Email**: `_________________`
  - Default: Cloud Run will create one automatically
  - Or use existing: `PROJECT_NUMBER-compute@developer.gserviceaccount.com`
  - Find it: `gcloud iam service-accounts list`

### 4. Model Configuration (Optional)
- [ ] **Gemini Model**: `_________________`
  - Default: `gemini-2.0-flash-exp`
  - Options: `gemini-2.0-flash-exp`, `gemini-1.5-pro`, `gemini-1.5-flash`, etc.

## After Deployment - You'll Need to Provide:

### 5. Cloud Run Service URL (After Backend Deployment)
- [ ] **Backend URL**: `https://_________________.run.app`
  - This will be generated after deploying the backend
  - Format: `https://trello-orders-api-XXXXX-uc.a.run.app`

## Quick Commands to Get Your Info

```bash
# Get current GCP project
gcloud config get-value project

# List all GCP projects
gcloud projects list

# List Firebase projects
firebase projects:list

# List service accounts
gcloud iam service-accounts list

# Check if Firebase is initialized
firebase projects:list
```

## What I'll Do With This Information

Once you provide these values, I will:

1. **Update deployment script** (`deploy-backend.sh`) with your project ID
2. **Update Firebase config** (`frontend/.firebaserc`) with your Firebase project ID
3. **Update backend CORS** (`backend/main.py`) with your Firebase domain
4. **Create a ready-to-deploy configuration**

## Example Response Format

You can provide the info like this:

```
GCP Project ID: maxprint-479504
Region: us-central1
Firebase Project ID: maxprint-479504 (same as GCP)
Service Account: (use default)
Gemini Model: gemini-2.0-flash-exp (default)
```


