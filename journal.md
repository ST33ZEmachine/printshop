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

## Session 2: Recursive Intelligence Module (TODO)

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

