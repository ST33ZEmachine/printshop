# MaxPrint Extraction Pipeline - Development Journal

## Session 1: Initial Extraction Pipeline Setup
**Date:** November 30, 2025

### Overview
Built an LLM-based extraction pipeline to enrich Trello card data for the ADK agent. The pipeline extracts structured information from card descriptions that are currently buried in free-form text.

### What We Built

#### 1. Buyer Information Extraction (`extract_buyer_info.py`)
- **Purpose**: Extract buyer/customer names and email addresses from Trello card titles and descriptions
- **Model**: Gemini 2.5 Flash-Lite (optimized for cost and performance)
- **Features**:
  - Extracts all buyer names and emails (not just first occurrence)
  - Identifies primary buyer when multiple are present
  - Provides confidence scores (high/medium/low)
  - Processes cards in batches for efficiency
  - Handles multiple buyers per card

**Results:**
- 500 cards processed
- 92.4% of cards have buyer names extracted
- 85.2% of cards have email addresses extracted
- 83.6% have both name and email
- 413 high-confidence extractions

#### 2. Price Extraction (`extract_price.py`)
- **Purpose**: Extract price information from card descriptions
- **Features**:
  - Extracts all prices found (per-unit, total, etc.)
  - Identifies primary/total price
  - Handles multiple prices per card
  - Provides price type classification (single, per_unit, total, multiple)

#### 3. LLM as Judge (`judge_extraction.py`)
- **Purpose**: Quality assessment of extraction results
- **Model**: Gemini 2.5 Flash
- **Features**:
  - Grades each extraction (A-F)
  - Provides accuracy, completeness, and overall scores (0-100)
  - Identifies false positives and false negatives
  - Suggests improvements
  - Generates aggregate statistics

**Results:**
- 50 cards judged (sample)
- Average accuracy: 79.3/100
- Average completeness: 78.3/100
- Average overall: 77.1/100
- 62% received grade A
- Only 18% received grade F

#### 4. HTML Review Dashboard (`generate_review_html.py`)
- **Purpose**: Visual review interface for extraction and judgment results
- **Features**:
  - Displays original descriptions, extracted fields, and judge evaluations
  - Filterable by grade, issues, and extraction status
  - Color-coded scores and grades
  - Summary statistics dashboard

### Key Decisions & Learnings

1. **Model Selection**:
   - Started with `gemini-2.0-flash-exp` (experimental) but hit quota limits
   - Switched extraction to `gemini-2.5-flash-lite` (stable, cost-effective)
   - Switched judgment to `gemini-2.5-flash` (better reasoning for quality assessment)
   - Result: No quota issues, better extraction quality

2. **Extraction Quality**:
   - Initial extraction: 55% coverage
   - After model switch: 92.4% coverage
   - Quality scores improved from 54.5/100 to 77.1/100

3. **Confidence Calibration**:
   - High confidence extractions: 60% get grade A, avg score 90.8/100
   - Only 8% of cards showed significant confidence/quality discrepancies
   - Extraction confidence is reasonably well-calibrated

4. **Cost Efficiency**:
   - Judgment step uses more tokens (original + extracted data) and more expensive model
   - Best practice: Use judgment for development/testing, sample-based for production monitoring
   - Extraction confidence can be trusted for most production use cases

### Technical Architecture

- **API**: Vertex AI (not Google AI Studio)
- **Authentication**: Google Cloud Application Default Credentials
- **Processing**: Batch-based with configurable concurrency
- **Output**: Enriched JSON with new fields added to original structure

### Files Created

```
extractionPipeline/
├── extract_buyer_info.py      # Buyer name/email extraction
├── extract_price.py            # Price extraction (not yet run)
├── judge_extraction.py         # Quality assessment
├── generate_review_html.py      # HTML dashboard generator
├── requirements.txt            # Dependencies
└── README.md                   # Documentation
```

### Data Files

- `rDbSqbLq - board-archive-2021-0707.json` - Original Trello export
- `rDbSqbLq - board-archive-2021-0707_buyer_enriched.json` - Enriched with buyer info
- `rDbSqbLq - board-archive-2021-0707_buyer_enriched_judged.json` - With quality judgments
- `rDbSqbLq - board-archive-2021-0707_buyer_enriched_judged.html` - Review dashboard

### Next Session: Recursive Intelligence Module

**Goal**: Build a recursive intelligence module that the ADK agent can use to improve first-pass extraction capability.

**Context**: 
- Current extraction pipeline works well but has some edge cases
- Judge identifies false positives/negatives and suggests improvements
- Need a way to learn from mistakes and improve extraction prompts/strategies

**Requirements**:
1. Analyze judgment results to identify patterns in extraction failures
2. Generate improved extraction prompts based on failure patterns
3. Test improved prompts and measure quality improvement
4. Create a feedback loop that the agent can use to iteratively improve extraction
5. Integrate with existing extraction pipeline

**Key Questions to Explore**:
- How can we automatically identify common failure patterns?
- What prompt engineering techniques improve extraction for edge cases?
- How do we validate that improvements actually work?
- Should this be a separate module or integrated into the extraction pipeline?
- How do we balance improvement vs. cost (more LLM calls)?

**Starting Point**:
- Review the 4 discrepancy cases identified (2 overconfident, 2 underconfident)
- Analyze the 9 grade F cases to find common patterns
- Look at false positives/negatives to understand what the extraction model struggles with
- Design a module that can learn from these patterns and suggest prompt improvements

**Success Criteria**:
- Module can identify extraction failure patterns
- Module can generate improved prompts
- Improved prompts show measurable quality improvement
- Process can be automated/iterative
- Cost remains reasonable

---

## Session 2: Cloud Run + Firebase Hosting Deployment
**Date:** December 3, 2025

### Overview
Wrapped the existing ADK Trello Orders Agent in a Cloud Run API and deployed a web chat UI on Firebase Hosting. Created a complete MVP demo stack that allows users to query their BigQuery order data through a simple chat interface.

### What We Built

#### 1. Backend API (`backend/`)
- **Framework**: FastAPI with async support
- **Endpoint**: `POST /chat` - accepts `{session_id, message}`, returns `{reply}`
- **Session Management**: InMemorySessionService for conversation state
- **Deployment**: Cloud Run with auto-scaling

**Key Files:**
- `backend/main.py` - FastAPI application
- `backend/Dockerfile` - Container definition
- `backend/requirements.txt` - Python dependencies
- `cloudbuild.yaml` - Cloud Build configuration
- `deploy-backend.sh` - One-command deployment script

#### 2. Frontend Chat UI (`frontend/`)
- **Stack**: Vanilla HTML/CSS/JS (no framework)
- **Features**:
  - Clean, modern chat interface
  - Session persistence via localStorage
  - Auto-scroll to latest messages
  - Loading states and error handling
  - Markdown rendering with marked.js
- **Deployment**: Firebase Hosting

**Key Files:**
- `frontend/index.html` - Chat interface
- `frontend/script.js` - API communication and markdown rendering
- `frontend/styles.css` - Styling with markdown support
- `frontend/firebase.json` - Hosting configuration

#### 3. Agent Refactoring
- Moved `agent/adk_trello_agent/agent.py` → `agent.py` (project root)
- Deleted redundant `agent/agent.py`
- Updated `run_adk_agent.sh` with deprecation notice

### Architecture

```
User Browser → Firebase Hosting (maxprint-61206.web.app)
             → Cloud Run (trello-orders-api-kspii3btya-uc.a.run.app)
             → ADK Agent + MCP Tools
             → BigQuery (trello_rag.trello_rag_20210707)
```

### Key Decisions & Learnings

1. **Session Management**:
   - Initially tried `VertexAiSessionService` but it requires a Reasoning Engine
   - Switched to `InMemorySessionService` - simpler, sufficient for MVP
   - Sessions auto-created on first message

2. **Toolbox Binary**:
   - Local `toolbox` was macOS ARM64, Cloud Run needs Linux x86_64
   - Solution: Download Linux binary in Dockerfile from `storage.googleapis.com/genai-toolbox/`
   - Version: v0.21.0

3. **Dependency Conflicts**:
   - `google-adk>=1.0.0` requires `starlette>=0.46.2` and `uvicorn>=0.34.0`
   - Original `fastapi==0.115.0` was incompatible
   - Solution: Removed version pins, let pip resolve compatible versions

4. **API Changes**:
   - `types.Part.from_text(message)` → `types.Part(text=message)`
   - Newer google-genai API changed method signatures

5. **Environment Variables** (Cloud Run):
   - `BIGQUERY_PROJECT` - BigQuery project ID
   - `GOOGLE_CLOUD_PROJECT` - GCP project
   - `GOOGLE_CLOUD_LOCATION` - Region (us-central1)
   - `GOOGLE_GENAI_USE_VERTEXAI=true` - Use Vertex AI backend
   - `GEMINI_MODEL` - Model selection

### URLs

- **Frontend**: https://maxprint-61206.web.app
- **Backend**: https://trello-orders-api-kspii3btya-uc.a.run.app
- **GCP Project**: maxprint-479504
- **Firebase Project**: maxprint-61206

### Local Development

```bash
# Test agent locally
export BIGQUERY_PROJECT=maxprint-479504
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=maxprint-479504
export GOOGLE_CLOUD_LOCATION=us-central1
python test_agent.py "Search for Rugby Canada orders"

# Deploy backend
./deploy-backend.sh maxprint-479504

# Deploy frontend
cd frontend && firebase deploy --only hosting
```

### Known Issues / TODO

1. **Markdown Rendering**: Added marked.js but formatting still not rendering correctly in production. Fallback regex formatter is in place but needs debugging.

2. **Session Persistence**: Sessions are in-memory, lost on container restart. Consider upgrading to persistent session storage for production.

3. **CORS**: Currently configured for Firebase domains + localhost. May need adjustment for other environments.

---

## Session 3: Markdown Fix + Recursive Intelligence Module (TODO)

**Prompt for Next Session:**

"Last session we deployed the Trello Orders Chat app to Cloud Run + Firebase Hosting. The app is working and querying BigQuery correctly, but there's one issue to fix:

1. **Markdown Rendering Bug**: The chat UI includes marked.js for markdown rendering, but the bot responses are still showing raw markdown (e.g., `**Name:**` instead of **Name:**). The code is in `frontend/script.js` using `marked.parse()`. Please debug why the markdown isn't rendering and fix it.

After fixing that, I'd like to continue with the recursive intelligence module from Session 1's notes - building a system that can analyze extraction failures and improve prompts automatically.

The deployed app URLs are:
- Frontend: https://maxprint-61206.web.app
- Backend: https://trello-orders-api-kspii3btya-uc.a.run.app

Let's start by debugging the markdown issue, then move on to the recursive intelligence module."

---

## Session 4: Recursive Intelligence Module (TODO)

**Prompt for Next Session:**

"I want to build a recursive intelligence module that can improve the extraction pipeline's first-pass capability. 

The current extraction pipeline works well (92% coverage, 77% quality), but the judge identified some patterns:
- 9 cards received grade F (18% of sample)
- 27 false positives and 31 false negatives across 50 cards
- Some high-confidence extractions still got low grades

I'd like a module that:
1. Analyzes judgment results to identify failure patterns (e.g., 'extracts job titles as names', 'misses emails in signature blocks')
2. Generates improved extraction prompts that address these patterns
3. Tests the improved prompts on a validation set
4. Creates a feedback loop for iterative improvement

The module should:
- Be cost-efficient (minimize additional LLM calls)
- Provide measurable improvements
- Be integrable with the existing extraction pipeline
- Work with the ADK agent architecture

Let's start by analyzing the current failure patterns and designing the module architecture."

