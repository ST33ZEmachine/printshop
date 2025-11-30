# Trello Data Extraction Pipeline

This pipeline enriches Trello card data by extracting structured information from card descriptions using Google Gemini LLM.

## Overview

The extraction pipeline processes raw Trello JSON exports and uses an LLM to extract valuable information that's buried in card descriptions. Currently, it extracts:

- **Buyer information**: Extracts buyer/customer names and email addresses from card titles and descriptions
- **Price information**: Extracts dollar amounts from card descriptions into a new `extracted_price` field
- **Quality judgment**: Uses an LLM judge to evaluate and grade extraction quality

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Google Cloud credentials:**
   - Make sure you have Google Cloud credentials configured:
     ```bash
     gcloud auth application-default login
     ```
   - Or set `GOOGLE_APPLICATION_CREDENTIALS` environment variable

3. **Set environment variables:**
   Create a `.env` file in the project root or set:
   - `BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT`: Your Google Cloud project ID
   - `GEMINI_MODEL` (optional): Gemini model to use (default: `gemini-2.0-flash-exp`)
   - `GCP_LOCATION` (optional): GCP location (default: `us-central1`)

## Usage

### Extract Buyer Information (Names & Emails)

**Basic Usage:**
```bash
python extract_buyer_info.py --input "rDbSqbLq - board-archive-2021-0707.json"
```

This will:
- Read the input JSON file
- Extract buyer names and email addresses from card titles and descriptions
- Save enriched data to `rDbSqbLq - board-archive-2021-0707_buyer_enriched.json`

**Advanced Options:**
```bash
python extract_buyer_info.py \
  --input "input.json" \
  --output "output.json" \
  --batch-size 20 \
  --max-workers 3 \
  --model "gemini-2.0-flash-exp"
```

### Extract Price Information

**Basic Usage:**
```bash
python extract_price.py --input "rDbSqbLq - board-archive-2021-0707.json"
```

This will:
- Read the input JSON file
- Extract price information from card descriptions
- Save enriched data to `rDbSqbLq - board-archive-2021-0707_enriched.json`

**Advanced Options:**
```bash
python extract_price.py \
  --input "input.json" \
  --output "output.json" \
  --batch-size 10 \
  --max-workers 3 \
  --model "gemini-2.0-flash-exp"
```

### Judge Extraction Quality

**Basic Usage:**
```bash
python judge_extraction.py --input "rDbSqbLq - board-archive-2021-0707_buyer_enriched.json"
```

This will:
- Review the extraction results from the enriched JSON
- Grade each extraction (A-F)
- Identify false positives and false negatives
- Provide quality scores and improvement suggestions
- Save judged data to `rDbSqbLq - board-archive-2021-0707_buyer_enriched_judged.json`

**Advanced Options:**
```bash
python judge_extraction.py \
  --input "enriched.json" \
  --output "judged.json" \
  --sample-size 50 \
  --batch-size 10 \
  --max-workers 2 \
  --model "gemini-2.0-flash-exp"
```

**Common Options (all scripts):**
- `--input`: Input JSON file path (required)
- `--output`: Output JSON file path (optional, defaults to input filename with appropriate suffix)
- `--batch-size`: Number of cards to process per LLM call (default: 20 for buyer extraction, 10 for price extraction/judgment)
- `--max-workers`: Maximum concurrent batch requests (default: 3 for extraction, 2 for judgment)
- `--model`: Gemini model ID (default: from `GEMINI_MODEL` env var or `gemini-2.0-flash-exp`)
- `--sample-size`: (Judgment only) Only judge a sample of N cards for testing

## Output Format

The enriched JSON maintains the original Trello structure but adds new fields to each card.

### Buyer Information Extraction Output

```json
{
  "cards": [
    {
      "id": "...",
      "name": "Christine Banford - Remax | Sign Topper",
      "desc": "...",
      "buyer_names": ["Christine Banford"],
      "buyer_emails": ["banfordchristine@gmail.com"],
      "primary_buyer_name": "Christine Banford",
      "primary_buyer_email": "banfordchristine@gmail.com",
      "buyer_confidence": "high",
      "buyer_notes": "Found name and email in description"
    }
  ],
  "extraction_metadata": {
    "buyer_extraction": {
      "model": "gemini-2.0-flash-exp",
      "batch_size": 20,
      "total_cards": 500,
      "cards_with_names": 450,
      "cards_with_emails": 420,
      "cards_with_both": 400,
      "cards_with_multiple_names": 25,
      "cards_with_multiple_emails": 10
    }
  }
}
```

**Buyer Information Fields:**
- `buyer_names`: Array of all buyer/customer names found (empty array if none)
- `buyer_emails`: Array of all email addresses found (empty array if none)
- `primary_buyer_name`: The primary/most relevant buyer name (string or null)
- `primary_buyer_email`: The primary/most relevant email (string or null)
- `buyer_confidence`: `"high"`, `"medium"`, or `"low"` based on extraction confidence
- `buyer_notes`: Brief explanation of what was found

**Handling Multiple Buyers:**
When a card has multiple names or emails, the script:
- Extracts ALL names and emails found
- Stores them in arrays (`buyer_names`, `buyer_emails`)
- Identifies the primary buyer (usually the first or most prominent)
- Stores primary values separately for easy querying

### Price Information Extraction Output

```json
{
  "cards": [
    {
      "id": "...",
      "name": "...",
      "desc": "...",
      "extracted_price": 17.10,
      "all_prices": [17.10],
      "price_type": "single",
      "price_confidence": "high",
      "price_notes": "Found '$17.10' in description"
    },
    {
      "id": "...",
      "name": "...",
      "desc": "Item 1: $15 per unit, Total: $150",
      "extracted_price": 150.0,
      "all_prices": [15.0, 150.0],
      "price_type": "multiple",
      "price_confidence": "high",
      "price_notes": "Found '$15 per unit' and '$150 total'"
    }
  ],
  "extraction_metadata": {
    "price_extraction": {
      "model": "gemini-2.0-flash-exp",
      "batch_size": 10,
      "total_cards": 500,
      "cards_with_price": 450,
      "cards_without_price": 50,
      "cards_with_multiple_prices": 25
    }
  }
}
```

**New Fields:**
- `extracted_price`: Primary/total numeric price value (or `null` if not found). When multiple prices are found, this is the total or largest price.
- `all_prices`: Array of ALL prices found in the description (as numbers). Includes the primary price. Empty array if none found.
- `price_type`: Type of price found: `"total"`, `"per_unit"`, `"single"`, `"multiple"`, or `null`
- `price_confidence`: `"high"`, `"medium"`, or `"low"` based on extraction confidence
- `price_notes`: Brief explanation of what prices were found

**Handling Multiple Prices:**
When a card description contains multiple prices (e.g., "$15 per unit, $150 total" or "Item 1: $10, Item 2: $20"), the script:
- Extracts ALL prices found
- Identifies the primary/total price (usually the largest or explicitly labeled as "total")
- Stores the primary price in `extracted_price` for easy querying
- Stores all prices in `all_prices` array for complete information
- Sets `price_type` to `"multiple"` when more than one price is found

## Performance Considerations

- **Batch Size**: Larger batches (10-20 cards) are more efficient but may hit token limits for very long descriptions
- **Concurrency**: `max_workers=3` provides good balance between speed and API rate limits
- **API Costs**: Each batch makes one API call. For 500 cards with batch_size=10, that's 50 API calls

## Quality Judgment

The judge script provides comprehensive quality assessment of extraction results:

### Judgment Output

Each card gets a `judgment` object with:
- `grade`: Letter grade (A-F)
- `accuracy_score`: 0-100 (how accurate are the extractions?)
- `completeness_score`: 0-100 (how complete is the extraction?)
- `overall_score`: 0-100 (weighted average)
- `false_positives`: Items extracted that aren't actually buyer information
- `false_negatives`: Buyer information that was missed
- `primary_buyer_correct`: Whether the primary buyer was correctly identified
- `issues`: List of problems found
- `suggestions`: Improvement recommendations
- `judge_notes`: Overall assessment

### Example Workflow

```bash
# 1. Extract buyer information
python extract_buyer_info.py --input "input.json"

# 2. Judge the extraction quality
python judge_extraction.py --input "input_buyer_enriched.json"

# 3. Review the judgment summary and improve extraction if needed
```

### Judgment Statistics

The judge provides aggregate statistics:
- Grade distribution (A-F percentages)
- Average accuracy, completeness, and overall scores
- False positive/negative counts
- Primary buyer correctness rate
- Cards with issues identified

## Next Steps

After running the extractions:
1. Run the judge script to evaluate extraction quality
2. Review judgment results to identify improvement opportunities
3. Upload to BigQuery to make the extracted fields available to the ADK agent
4. Consider combining multiple extractions (run buyer extraction, then price extraction on the same file)
5. Extend the pipeline to extract other fields (order quantities, product types, delivery dates, etc.)

## Troubleshooting

**Error: "BIGQUERY_PROJECT environment variable not set"**
- Set `BIGQUERY_PROJECT` or `GOOGLE_CLOUD_PROJECT` in your `.env` file or environment

**Error: "Failed to initialize Gemini client"**
- Ensure Google Cloud credentials are configured: `gcloud auth application-default login`
- Verify your project ID is correct

**Low extraction rates:**
- Review `price_notes` fields to understand why prices weren't found
- Consider adjusting the prompt in `extract_price.py` for your specific data format
- Check that descriptions actually contain price information

