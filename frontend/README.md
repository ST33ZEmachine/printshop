# Frontend - Firebase Hosting Chat UI

A simple, clean chat interface for interacting with the Trello Orders Agent.

## Local Development

### Prerequisites

- A running backend API (see `../backend/README.md`)
- A local web server (or use Firebase CLI)

### Setup

1. Update the API URL in `script.js`:
```javascript
const API_URL = 'http://localhost:8080';  // Your backend URL
```

2. Serve the files using a local server:

**Option 1: Python**
```bash
cd frontend
python3 -m http.server 3000
```

**Option 2: Node.js (http-server)**
```bash
npm install -g http-server
cd frontend
http-server -p 3000
```

**Option 3: Firebase CLI (recommended for testing Firebase config)**
```bash
firebase serve --only hosting
```

3. Open `http://localhost:3000` in your browser

## Deployment to Firebase Hosting

### Prerequisites

1. Install Firebase CLI:
```bash
npm install -g firebase-tools
```

2. Login to Firebase:
```bash
firebase login
```

3. Initialize Firebase (if not already done):
```bash
cd frontend
firebase init hosting
```

### Configure

1. Update `.firebaserc` with your Firebase project ID:
```json
{
  "projects": {
    "default": "your-firebase-project-id"
  }
}
```

2. Update `script.js` with your Cloud Run service URL:
```javascript
const API_URL = 'https://your-service-xxxxx-uc.a.run.app';
```

### Deploy

```bash
cd frontend
firebase deploy --only hosting
```

Your app will be available at:
`https://your-firebase-project-id.web.app`

### CORS Configuration

If you encounter CORS errors, ensure your Cloud Run service allows requests from your Firebase Hosting domain. Update `backend/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-firebase-project-id.web.app",
        "https://your-firebase-project-id.firebaseapp.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Features

- **Session Persistence**: Each browser session maintains conversation history via localStorage
- **Auto-scroll**: Chat automatically scrolls to show latest messages
- **Responsive Design**: Works on desktop and mobile devices
- **Error Handling**: Displays user-friendly error messages
- **Loading States**: Visual feedback during API requests

## File Structure

```
frontend/
├── index.html      # Main HTML structure
├── script.js       # Chat logic and API communication
├── styles.css      # Styling
├── firebase.json   # Firebase Hosting configuration
├── .firebaserc     # Firebase project configuration
└── README.md       # This file
```

