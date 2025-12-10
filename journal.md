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

4. **Authentication**: Currently public/unauthenticated. Add Firebase Auth or similar before production use. Options:
   - Firebase Authentication (Google sign-in, email/password)
   - Cloud Run IAM (require Google account)
   - API key authentication

5. **Card Hyperlinking**: When displaying order results, add clickable links to the original Trello cards using the `shortUrl` field from the data. This would let users jump directly to the card in Trello for more details.

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

---

## Session 5: Data Enrichment Pipeline & Performance Optimization
**Date:** December 7, 2025

### Overview
Significantly improved the Trello card extraction pipeline performance, added comprehensive data enrichment (dates, business lines, materials, dimensions), and implemented data quality auditing. Achieved 8x performance improvement through model optimization and proper logging infrastructure.

### What We Built

#### 1. Performance Optimization (`extract_trello_data.py`)
- **Problem**: Initial extraction was hanging, slow reporting, API traffic dropping to zero
- **Root Causes Identified**:
  - All `asyncio.create_task()` calls created upfront causing contention
  - No feedback before first batch completed
  - `asyncio.to_thread` bottleneck due to default `ThreadPoolExecutor` size
  - No timeout on API calls
- **Solutions Implemented**:
  - Wave-based processing for controlled concurrency
  - Immediate batch start logging
  - Explicitly sized `ThreadPoolExecutor` to match `--workers`
  - Added 300-second timeout for API calls
  - Simplified LLM prompt and reduced extracted fields
  - Switched from `gemini-2.5-flash` to `gemini-2.5-flash-lite` for 12x speed improvement

**Results:**
- Initial: ~77 seconds per 25-card batch
- Optimized: ~6.4 seconds per 25-card batch (12x faster)
- Processing rate: ~500 cards/minute (up from ~20 cards/minute)
- Zero API timeouts with proper worker management

#### 2. Date Enrichment (`add_created_date.py`)
- **Purpose**: Extract creation dates from Trello card IDs (hexadecimal timestamps)
- **Features**:
  - Extracts first 8 hex characters from card ID
  - Converts to Unix timestamp, then to datetime
  - Adds multiple date fields: `date_created`, `datetime_created`, `year_created`, `month_created`, `year_month`, `unix_timestamp`
- **Technical Details**:
  - Trello card IDs encode creation timestamp in first 8 hex characters
  - Conversion: `int(hex_id[:8], 16)` → Unix timestamp → `datetime.fromtimestamp()`

#### 3. Business Card Pricing Audit (`audit_business_cards.py`)
- **Problem**: Business card orders were misclassified - "per_unit" pricing was being applied when cards are sold in packs (250/500/1000), causing massive revenue overstatements
- **Solution**: LLM-based audit system that:
  - Sorts cards by revenue, audits top N (e.g., 2000)
  - Identifies business card orders with pricing errors
  - Corrects `price_type` from "per_unit" to "total"
  - Recalculates `unit_price` and `total_revenue`
  - Adds `audit_log: "business card issue"` and `original_revenue` fields
- **Model**: `gemini-2.5-flash-lite` with aggressive prompt targeting "ea set" terminology
- **Architecture**: Parallel processing with `ThreadPoolExecutor` and `asyncio.gather()`

**Results:**
- Identified and corrected business card pricing errors in top revenue orders
- Prevented significant revenue misrepresentation
- Audit metadata preserved for traceability

#### 4. Line Item Enrichment (`enrich_line_items.py`)
- **Purpose**: Classify each line item with business line, material, and dimensions
- **Fields Added**:
  - `business_line`: "Signage", "Printing", or "Engraving"
  - `material`: Material type (e.g., "Aluminum", "Vinyl", "Coroplast", "14PT Coated")
  - `dimensions`: Size information (e.g., "36x24", "96x48")
- **Architecture**:
  - Flattens all line items from all cards into single list (20,438 items)
  - Batches line items (25 per batch)
  - Parallel processing with 5 workers
  - Re-integrates enriched data back into nested card structure
- **Model**: `gemini-2.5-flash-lite`
- **Performance**: ~3,500 items/minute (7x faster than extraction due to simpler task)

**Results:**
- **20,422 / 20,438 items enriched (99.9%)**
- **0 errors**
- **5.8 minutes total processing time**
- **Business Line Distribution**:
  - Signage: 14,399 items, $3,296,573 (70.5% of revenue)
  - Printing: 4,986 items, $1,016,847 (21.8% of revenue)
  - Engraving: 397 items, $62,385 (1.3% of revenue)
  - Not classified: 656 items, $85,646 (1.8% of revenue)

#### 5. Logging Infrastructure
- **Problem**: Enrichment script had no progress logging, making it impossible to monitor long-running processes
- **Solution**: Comprehensive logging system with:
  - Console output (INFO level) with timestamps
  - File logging (DEBUG level) to `enrichment.log`
  - Progress updates every 20 batches showing:
    - Batches completed / total
    - Items enriched count
    - Processing rate (items/minute)
    - ETA (estimated time remaining)
    - Error count
  - Final summary with business line distribution and revenue breakdown

### Key Technical Decisions & Learnings

1. **Model Selection for Speed**:
   - `gemini-2.5-flash-lite` is 12x faster than `gemini-2.5-flash` for simple classification tasks
   - Trade-off: Slightly less reasoning capability, but sufficient for structured extraction
   - Cost: Significantly lower token usage and faster inference

2. **Prompt Size Matters**:
   - Extraction: ~2KB input per card → ~500 cards/minute
   - Enrichment: ~50 chars input per item → ~3,500 items/minute
   - **7x speed difference** primarily due to prompt size, not task complexity

3. **Parallel Processing Architecture**:
   - `ThreadPoolExecutor` with explicit worker count matching `--workers`
   - `asyncio.gather()` for batch parallelization
   - Wave-based processing prevents API rate limiting
   - Proper timeout handling prevents hanging

4. **Data Structure Strategy**:
   - Keep nested JSON structure during enrichment (cards → line_items)
   - Flatten only for final BigQuery upload
   - Preserves relationships and makes enrichment easier

5. **Error Handling**:
   - Background processes can fail silently - always run in foreground for initial testing
   - Comprehensive logging is essential for long-running processes
   - Checkpointing would be valuable for resumability (future enhancement)

### Files Created/Modified

```
extractionPipeline/
├── extract_trello_data.py          # Performance optimized extraction
├── add_created_date.py              # Date enrichment from card IDs
├── audit_business_cards.py          # Business card pricing corrections
├── enrich_line_items.py             # Business line/material/dimensions enrichment
├── enrichment.log                   # Detailed enrichment logs
└── recent_50_items_report.html      # Sample enrichment report
```

### Data Files

- `LyB2G53h_cards_extracted.json` - Master file with all enrichments:
  - Original card data
  - Extracted line items with prices
  - Date fields (date_created, year_month, etc.)
  - Buyer information (name, email)
  - Business line classification
  - Material and dimensions
  - Audit corrections

### Current Data Schema

**Nested Structure (for enrichment):**
```json
{
  "cards": [
    {
      "id": "card_id",
      "name": "card_name",
      "desc": "full_description",
      "date_created": "2024-01-15",
      "year_month": "2024-01",
      "buyer_name": "...",
      "buyer_email": "...",
      "line_items": [
        {
          "description": "...",
          "quantity": 1,
          "price": 100.00,
          "price_type": "total",
          "total_revenue": 100.00,
          "business_line": "Signage",
          "material": "Vinyl",
          "dimensions": "36x24"
        }
      ]
    }
  ]
}
```

**Proposed BigQuery Schema (for upload):**
- `cards` table: Card-level fields (id, name, desc, date_created, buyer_name, buyer_email, etc.)
- `line_items` table: Line item fields (card_id FK, description, quantity, price, business_line, material, dimensions, etc.)
- `card_events` table: Card activity/events (future)

### Performance Metrics

| Task | Model | Rate | Notes |
|------|-------|------|-------|
| Initial Extraction | gemini-2.5-flash | ~20 cards/min | Too slow, timeouts |
| Optimized Extraction | gemini-2.5-flash-lite | ~500 cards/min | 25x improvement |
| Date Enrichment | Python (no LLM) | Instant | Direct calculation |
| Business Card Audit | gemini-2.5-flash-lite | ~200 cards/min | Complex reasoning |
| Line Item Enrichment | gemini-2.5-flash-lite | ~3,500 items/min | Simple classification |

### Next Steps

1. **BigQuery Integration**:
   - Flatten nested JSON structure into `cards`, `line_items`, and `events` tables
   - Design schema with proper foreign keys
   - Create upload script with data validation
   - Handle incremental updates (new cards only)

2. **Live Trello Integration**:
   - Build webhook receiver for real-time card updates
   - Process new cards through extraction pipeline
   - Update BigQuery incrementally
   - Maintain data freshness

3. **Data Quality Improvements**:
   - Address 656 unclassified line items (3.2%)
   - Validate material and dimensions extraction quality
   - Add confidence scores to enrichments
   - Implement validation rules (e.g., dimensions format)

4. **Monitoring & Alerting**:
   - Track extraction success rates
   - Monitor API costs and usage
   - Alert on high error rates
   - Dashboard for data quality metrics

5. **Resumability**:
   - Add checkpointing to all enrichment scripts
   - Save progress after each batch
   - Allow resume from last checkpoint
   - Handle partial failures gracefully

6. **Additional Enrichments** (if needed):
   - Extract installation dates
   - Identify delivery methods
   - Classify order types (rush, standard, etc.)
   - Extract special instructions or notes

### Key Insights

- **Speed vs. Quality Trade-off**: `gemini-2.5-flash-lite` provides excellent speed for classification tasks while maintaining good quality. Only use `gemini-2.5-flash` when complex reasoning is required.

- **Prompt Engineering**: Smaller, focused prompts dramatically improve performance. The enrichment task (3 fields, simple classification) is 7x faster than extraction (10+ fields, complex parsing).

- **Parallel Processing**: Proper worker management and wave-based processing prevents API rate limiting while maximizing throughput.

- **Data Quality**: Business card pricing audit revealed significant revenue misrepresentation. Always validate high-value extractions, especially when pricing logic is complex.

- **Logging is Critical**: Without proper logging, long-running processes are black boxes. Comprehensive logging enables monitoring, debugging, and user confidence.

---

## 2025-12-09

### What we did
- Added dashboard API endpoints in `backend/main.py` (revenue trends, business line split, top customers, order status, material breakdown) and fixed order status to use `closed` status.
- Built a React + shadcn dashboard under `frontend/dashboard` with Recharts; hosted at `/dashboard` on Firebase (Vite base set to `/dashboard/dist/`).
- Updated Firebase rewrites to serve built assets only and ignore dev sources; fixed MIME issues.
- Deployed backend to Cloud Run via `cloudbuild.yaml` (image `gcr.io/maxprint-479504/trello-orders-api:latest`) and confirmed dashboard loads data from the new endpoints.

### Security upgrade parking lot
- Disable unauthenticated Cloud Run access and require auth (IAM/JWT/IAP/Cloud Endpoints).
- Add rate limiting/throttling and request logging/alerting on dashboard APIs.
- Move config/secrets to Secret Manager; avoid any plaintext envs in deploys.
- Consider Cloud Armor/IAP in front of Cloud Run; restrict CORS to known hosts only.
- Set budgets/quotas and add monitoring on BigQuery usage and API errors.
- Add dependency scanning (Dependabot/Snyk) and periodic vulnerability checks.

---

