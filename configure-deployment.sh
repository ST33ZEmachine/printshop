#!/bin/bash
# Configuration script for Cloud Run and Firebase Hosting deployment
# Usage: ./configure-deployment.sh

set -e

echo "🔧 Cloud Run & Firebase Hosting Configuration"
echo "=============================================="
echo ""

# Get GCP Project ID
read -p "Enter your GCP Project ID [maxprint-479504]: " GCP_PROJECT
GCP_PROJECT=${GCP_PROJECT:-maxprint-479504}

# Get Region
read -p "Enter preferred region [us-central1]: " REGION
REGION=${REGION:-us-central1}

# Get Firebase Project ID
read -p "Enter Firebase Project ID (can be same as GCP) [${GCP_PROJECT}]: " FIREBASE_PROJECT
FIREBASE_PROJECT=${FIREBASE_PROJECT:-${GCP_PROJECT}}

# Get Gemini Model
read -p "Enter Gemini Model [gemini-2.0-flash-exp]: " GEMINI_MODEL
GEMINI_MODEL=${GEMINI_MODEL:-gemini-2.0-flash-exp}

echo ""
echo "📝 Configuration Summary:"
echo "  GCP Project ID: ${GCP_PROJECT}"
echo "  Region: ${REGION}"
echo "  Firebase Project ID: ${FIREBASE_PROJECT}"
echo "  Gemini Model: ${GEMINI_MODEL}"
echo ""

read -p "Apply these settings? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

# Update deploy-backend.sh
echo "📝 Updating deploy-backend.sh..."
# Use a more reliable method with Python
python3 << PYTHON_SCRIPT
import re

with open('deploy-backend.sh', 'r') as f:
    content = f.read()

# Update PROJECT_ID default
content = re.sub(
    r'PROJECT_ID=\$\{1:-\$\{GOOGLE_CLOUD_PROJECT:-\"[^\"]+\"\}\}',
    f'PROJECT_ID=${{1:-${{GOOGLE_CLOUD_PROJECT:-"{GCP_PROJECT}"}}}}',
    content
)

# Update REGION default
content = re.sub(
    r'REGION=\$\{3:-\"[^\"]+\"\}',
    f'REGION=${{3:-"{REGION}"}}',
    content
)

with open('deploy-backend.sh', 'w') as f:
    f.write(content)
PYTHON_SCRIPT

# Update frontend/.firebaserc
echo "📝 Updating frontend/.firebaserc..."
cat > frontend/.firebaserc << EOF
{
  "projects": {
    "default": "${FIREBASE_PROJECT}"
  }
}
EOF

# Update backend/main.py CORS (with Firebase domains)
echo "📝 Updating backend/main.py CORS settings..."
python3 << PYTHON_SCRIPT
import re

with open('backend/main.py', 'r') as f:
    content = f.read()

# Replace CORS allow_origins
new_cors = f'''app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://{FIREBASE_PROJECT}.web.app",
        "https://{FIREBASE_PROJECT}.firebaseapp.com",
        "http://localhost:3000",  # For local development
        "http://localhost:8080",  # For local backend testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)'''

# Find and replace the CORS middleware block
pattern = r'app\.add_middleware\(\s*CORSMiddleware,[^)]+\)'
content = re.sub(pattern, new_cors, content, flags=re.DOTALL)

with open('backend/main.py', 'w') as f:
    f.write(content)
PYTHON_SCRIPT

# Create a .env.example file
echo "📝 Creating .env.example..."
cat > .env.example << EOF
# Google Cloud Configuration
BIGQUERY_PROJECT=${GCP_PROJECT}
GOOGLE_CLOUD_PROJECT=${GCP_PROJECT}
GOOGLE_CLOUD_LOCATION=${REGION}

# Gemini Model
GEMINI_MODEL=${GEMINI_MODEL}

# Application
APP_NAME=trello_orders_chat
EOF

echo ""
echo "✅ Configuration complete!"
echo ""
echo "📋 Next steps:"
echo "1. Review the changes in:"
echo "   - deploy-backend.sh"
echo "   - frontend/.firebaserc"
echo "   - backend/main.py (CORS settings)"
echo ""
echo "2. Deploy backend:"
echo "   ./deploy-backend.sh"
echo ""
echo "3. After backend deployment, update frontend/script.js with the Cloud Run URL"
echo ""
echo "4. Deploy frontend:"
echo "   cd frontend && firebase deploy --only hosting"
echo ""

