#!/bin/bash
# Deployment script for Cloud Run backend
# Usage: ./deploy-backend.sh [PROJECT_ID] [SERVICE_NAME] [REGION]

set -e

PROJECT_ID=${1:-${GOOGLE_CLOUD_PROJECT:-"maxprint-479504"}}
SERVICE_NAME=${2:-"trello-orders-api"}
REGION=${3:-"us-central1"}
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

echo "🚀 Deploying backend to Cloud Run..."
echo "Project: ${PROJECT_ID}"
echo "Service: ${SERVICE_NAME}"
echo "Region: ${REGION}"
echo "Image: ${IMAGE_NAME}"
echo ""

# Build and push Docker image
echo "📦 Building Docker image..."
# Use cloudbuild.yaml to specify Dockerfile location
gcloud builds submit --config cloudbuild.yaml --project ${PROJECT_ID} .

# Deploy to Cloud Run
echo "🚀 Deploying to Cloud Run..."
echo "Using read-only service account: maxprint-agent-readonly@${PROJECT_ID}.iam.gserviceaccount.com"
# Load Trello credentials from .env if available
TRELLO_KEY_VAL=""
TRELLO_TOKEN_VAL=""
if [ -f .env ]; then
  TRELLO_KEY_VAL=$(grep "^TRELLO_KEY=" .env | cut -d= -f2)
  TRELLO_TOKEN_VAL=$(grep "^TRELLO_TOKEN=" .env | cut -d= -f2)
fi

ENV_VARS="BIGQUERY_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GEMINI_MODEL=${GEMINI_MODEL:-gemini-2.5-flash},GOOGLE_GENAI_USE_VERTEXAI=true"

# Add Trello credentials if available
if [ -n "$TRELLO_KEY_VAL" ] && [ -n "$TRELLO_TOKEN_VAL" ]; then
  ENV_VARS="${ENV_VARS},TRELLO_KEY=${TRELLO_KEY_VAL},TRELLO_TOKEN=${TRELLO_TOKEN_VAL}"
  echo "Including Trello credentials from .env"
fi

gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --project ${PROJECT_ID} \
  --service-account maxprint-agent-readonly@${PROJECT_ID}.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --set-env-vars "${ENV_VARS}" \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10

# Get service URL (wait a moment for deployment to complete)
sleep 5
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --project ${PROJECT_ID} --format 'value(status.url)' 2>/dev/null || echo "Service URL will be available after deployment completes")

echo ""
echo "✅ Deployment complete!"
echo "Service URL: ${SERVICE_URL}"
echo ""
echo "📝 Next steps:"
echo "1. Update frontend/script.js with this URL:"
echo "   const API_URL = '${SERVICE_URL}';"
echo "2. Update backend/main.py CORS settings if needed"
echo "3. Redeploy backend if CORS was updated"

