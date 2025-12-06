#!/usr/bin/env python3
"""
Parse Orders to Line Items - Batch Extraction Pipeline

This script extracts structured line items from signage order descriptions
using Google Gemini LLM. It reads a Trello board JSON export, processes
cards in batches, and outputs normalized line items in CSV format.

Usage:
    # Test with dry-run first (no API calls, estimates tokens/cost)
    python parse_orders_to_line_items.py --dry-run
    
    # Test with small subset
    python parse_orders_to_line_items.py --limit 50
    
    # Full run
    python parse_orders_to_line_items.py

Configuration (via environment variables or constants below):
    INPUT_FILE:  Path to the input JSON file (Trello board export)
    OUTPUT_FILE: Path to the output CSV file (one line item per row)
    ERROR_FILE:  Path to the error log file (JSONL format)
    GEMINI_MODEL: Model ID (default: gemini-2.5-flash-lite)
    BATCH_SIZE: Number of cards per batch (default: 50)
    
Before running:
    1. Set GOOGLE_CLOUD_PROJECT or BIGQUERY_PROJECT env variable
    2. Authenticate with: gcloud auth application-default login
    3. Install deps: pip install google-genai python-dotenv

Author: Data Engineering Team
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

# ==============================================================================
# CONFIGURATION - Modify these or set via environment variables
# ==============================================================================
INPUT_FILE = os.environ.get(
    "INPUT_FILE", 
    "bourquin_05122025_snapshot.json"
)
OUTPUT_FILE = os.environ.get(
    "OUTPUT_FILE",
    "line_items_output.csv"
)
ERROR_FILE = os.environ.get(
    "ERROR_FILE",
    "parse_errors.jsonl"
)
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "25"))  # 25 for reliability with complex prompts
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "1"))

# Gemini 2.5 Flash Lite pricing (as of Dec 2024)
# Input: $0.075 per 1M tokens, Output: $0.30 per 1M tokens
PRICE_INPUT_PER_M = 0.075
PRICE_OUTPUT_PER_M = 0.30

# ==============================================================================
# ENVIRONMENT SETUP
# ==============================================================================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

# ==============================================================================
# SYSTEM PROMPT FOR LINE ITEM EXTRACTION
# ==============================================================================
SYSTEM_PROMPT = """You are a data extraction engine.

You receive information about signage jobs. Each job has:
- `order_id`: a unique identifier for the job
- `description`: an open-text description that may include:
  - SECTION HEADERS (location groups), e.g.:
    - STORE FRONT
    - EAST FACING WALL: (New Holland & KOBELCO Logos)
    - WEST FACING WALL: (DLE & Kubota logos)
    - SERVICE DEPARTMENT:
  - ORDER LINES that describe manufactured/installed items, for example:
    - Supply & Install (1) 896"x48" Aluminum Composite Panels - Grey
    - Supply (1) 576"x48" (6 - 8'x4') Aluminum Composite Panel- Grey w/ black logo and white text" SERVICE DEPARTMENT.
    - Supply & Install (1) 120"xX" Acrylic "DLE" logo, (Black version of logo) *Install on Store Front ACP over doorway.

Your task:

1. Attempt to identify SECTION HEADERS (location groups). If no obvious section headers are available then leave null.
   - A location group is a label like "STORE FRONT", "EAST FACING WALL: (New Holland & KOBELCO Logos)", "SERVICE DEPARTMENT:".
   - A location group applies to the order lines that follow it until the next section header.
   - If an order line appears before any header, `location_group` should be null.

2. Under each location group, identify individual ORDER LINES.
   - An order line usually includes:
     - An order class phrase such as "Supply & Install", "Supply", "Install".
     - A quantity in parentheses, e.g. `(1)`, `(2)`, `(6)`.
     - Dimensions like `896"x48"` (width"xheight").
     - A material, such as "Aluminum Composite Panels", "Acrylic".
     - Optional colour and additional descriptive text.
   - Some lines may contain extra hints, e.g. `(2 Panels)`, `w/ black logo and white text`, logo names, or notes.

3. For each order line, extract a structured line item with the following fields:
   - `line_index` (integer): 1-based index of the order line within this job (across all sections).
   - `location_group` (string or null): the most recent section header text above this line, normalized by trimming whitespace and trailing punctuation (like `:`).
   - `order_class` (string or null): e.g. "Supply & Install", "Supply", "Install".
   - `quantity` (integer or null): parse from parentheses like `(1)`. If there are multiple candidates, choose the main one describing the item count. If uncertain, use null.
   - `price` (number or null): the dollar value of the line if applicable. Leave null if no dollar value is listed.
   - `raw_price_text` (string or null): the exact substring from the source containing the price, e.g. "$489.00", "$45 ea", "= $99 + tax". This is required if `price` is not null.
   - `width_in` (number or null): the numeric width in inches from patterns like `896"x48"`.
   - `height_in` (number or null): the numeric height in inches from patterns like `896"x48"`.
     - If the second dimension is not a clear number (e.g. `120"xX"`), set `height_in` to null.
   - `raw_dimensions_text` (string or null): the exact substring that represents dimensions, e.g. `896"x48"`. If multiple candidates exist, choose the main one.
   - `material` (string or null): e.g. "Aluminum Composite Panels", "Aluminum Composite Panel", "Acrylic".
   - `description` (string or null): a concise human-readable summary of what is being supplied/installed, including logos if relevant.
   - `colour` (string or null): main colour(s) of the panels or material, e.g. "Grey", "Black", "White". Do not invent colours.
   - `extra_notes` (string or null): any additional details that do not fit the above fields, e.g. "(2 Panels)", "w/ black logo and white text", logo names and installation notes.
   - `raw_line_text` (string): the full original text for this order line.
   - `llm_confidence` (string): "high", "medium", or "low" based on your certainty.

4. Output format:
- Return a JSON array where each element corresponds to one input job.
- Each element has this structure:

{
  "order_id": "<copy of the input order_id>",
  "line_items": [
    {
      "line_index": 1,
      "location_group": "...",
      "order_class": "...",
      "quantity": 1,
      "price": 489.0,
      "raw_price_text": "$489.00",
      "width_in": 896,
      "height_in": 48,
      "raw_dimensions_text": "896\\"x48\\"",
      "material": "Aluminum Composite Panels",
      "description": "Install on Store Front ACP over doorway. Acrylic \\"DLE\\" logo (Black version of logo).",
      "colour": "Grey",
      "extra_notes": "(2 Panels)",
      "raw_line_text": "...",
      "llm_confidence": "high"
    }
  ]
}

Rules and clarifications:

- If a field is completely missing or ambiguous, set it to null instead of guessing, and put the raw phrase into `extra_notes`.
- For quantity, use an integer when clearly present, otherwise null.
- CRITICAL PRICE RULES:
  - Only extract prices that are EXPLICITLY stated as dollar amounts in the text (e.g. "$489.00", "$45 ea", "= $99").
  - NEVER calculate or derive prices. If the text says "5 hours at $125/hr", extract price=125 and raw_price_text="$125.00/ hr", NOT price=625.
  - If a price is per-unit (e.g. "$12 ea", "$0.50 each"), extract the per-unit price, not a total.
  - The `raw_price_text` field MUST contain the exact substring from the source that you extracted the price from. If you cannot point to exact source text, set price to null.
  - When in doubt about a price, set price to null rather than guess.
- For dimensions:
  - Recognize patterns like `number"xnumber"`.
  - The first number is `width_in`, the second is `height_in`.
  - Strip quotes and whitespace before converting to a number.
  - If the second token is not numeric (e.g. `120"xX"`), set `height_in` to null and keep the full text in `raw_dimensions_text`.
- For `location_group`, use the verbatim header text but trimmed of leading/trailing whitespace and punctuation.
- Do not merge multiple distinct order lines into one line item; each physical item or logical set described as a single line should be a separate entry in `line_items`.
- If no order lines can be identified for a job, return an empty `line_items` array for that job.
- Do not output anything except the JSON array."""


# ==============================================================================
# CSV COLUMN DEFINITIONS (BigQuery-friendly, lower_snake_case)
# ==============================================================================
CSV_COLUMNS = [
    "order_id",
    "line_index",
    "location_group",
    "order_class",
    "quantity",
    "price",
    "raw_price_text",
    "price_validated",
    "width_in",
    "height_in",
    "raw_dimensions_text",
    "material",
    "description",
    "colour",
    "extra_notes",
    "raw_line_text",
    "llm_confidence",
]


def estimate_tokens(text: str) -> int:
    """
    Estimate token count using simple heuristic (1 token ≈ 4 chars).
    This is a rough approximation for planning purposes.
    """
    return len(text) // 4


def validate_price_against_source(price: float, raw_price_text: str) -> bool:
    """
    Validate that extracted price matches the raw_price_text citation.
    Returns True if price appears valid, False if likely hallucinated.
    """
    if price is None or raw_price_text is None:
        return True  # Nothing to validate
    
    import re
    # Match dollar amounts including $.XX format (leading dot)
    pattern = r'\$?(\d+(?:,\d{3})*(?:\.\d{1,2})?|\.\d{1,2})'
    matches = re.findall(pattern, raw_price_text)
    
    for match in matches:
        try:
            source_val = float(match.replace(',', ''))
            # Check if extracted price is close to any value in source
            if abs(price - source_val) < 0.01:
                return True
        except:
            pass
    
    return False


def validate_line_item(item: dict) -> dict:
    """
    Validate and normalize a line item dictionary.
    Ensures all expected fields exist with proper types.
    """
    validated = {}
    
    # Integer fields
    for field in ["line_index", "quantity"]:
        val = item.get(field)
        if val is not None:
            try:
                validated[field] = int(val)
            except (ValueError, TypeError):
                validated[field] = None
        else:
            validated[field] = None
    
    # Numeric fields (float)
    for field in ["price", "width_in", "height_in"]:
        val = item.get(field)
        if val is not None:
            try:
                validated[field] = float(val)
            except (ValueError, TypeError):
                validated[field] = None
        else:
            validated[field] = None
    
    # String fields
    for field in ["location_group", "order_class", "raw_dimensions_text", 
                  "raw_price_text", "material", "description", "colour", 
                  "extra_notes", "raw_line_text", "llm_confidence"]:
        val = item.get(field)
        if val is not None and val != "":
            validated[field] = str(val)
        else:
            validated[field] = None
    
    # Validate price against raw_price_text
    price_valid = validate_price_against_source(
        validated.get("price"), 
        validated.get("raw_price_text")
    )
    validated["price_validated"] = price_valid
    
    # Flag invalid prices but don't null them - let downstream decide
    if not price_valid and validated.get("price") is not None:
        extra = validated.get("extra_notes") or ""
        validated["extra_notes"] = (extra + " [PRICE_UNVERIFIED]").strip()
    
    return validated


def clean_json_response(text: str) -> str:
    """
    Clean up LLM response text to extract valid JSON.
    Handles markdown code blocks and other common issues.
    """
    text = text.strip()
    
    # Remove markdown code blocks
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    
    text = text.strip()
    return text


def parse_json_response(text: str) -> Optional[list]:
    """
    Parse the LLM response as JSON array.
    Returns None if parsing fails.
    """
    cleaned = clean_json_response(text)
    try:
        result = json.loads(cleaned)
        # Ensure it's a list
        if isinstance(result, dict):
            # Single result, wrap in list
            return [result]
        return result if isinstance(result, list) else None
    except json.JSONDecodeError:
        return None


def build_batch_prompt(cards: list[dict]) -> str:
    """
    Build the user prompt for a batch of cards.
    """
    parts = []
    for i, card in enumerate(cards):
        order_id = card.get("id", f"unknown_{i}")
        desc = card.get("desc", "")
        parts.append(f"[Job {i}]\norder_id: {order_id}\ndescription:\n{desc}")
    
    return "Extract line items from the following jobs:\n\n" + "\n\n---\n\n".join(parts) + "\n\nReturn the JSON array."


def extract_line_items_batch(
    client,  # genai.Client
    cards: list[dict],
    model_id: str,
    max_retries: int = MAX_RETRIES
) -> tuple[list[dict], list[dict]]:
    """
    Extract line items from a batch of cards in a single API call.
    
    Args:
        client: Gemini client
        cards: List of card dictionaries with 'id' and 'desc' fields
        model_id: Model to use
        max_retries: Number of retries for JSON parse failures
        
    Returns:
        Tuple of (successful_results, errors)
        - successful_results: list of dicts with order_id and line_items
        - errors: list of error dicts
    """
    from google.genai import types
    
    # Build batch prompt
    user_prompt = build_batch_prompt(cards)
    full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt
    
    results = []
    errors = []
    
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=full_prompt)]
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        response_text = response.text.strip() if response.text else ""
        
        # Parse response
        parsed = parse_json_response(response_text)
        
        if parsed is None:
            # Retry with fix prompt
            if max_retries > 0:
                logger.warning("JSON parse failed, retrying with fix prompt...")
                fix_prompt = f"""The previous response was not valid JSON.
Return ONLY a valid JSON array with one object per job.
Each object must have "order_id" and "line_items" fields.

Previous response that failed:
{response_text[:2000]}"""
                
                fix_response = client.models.generate_content(
                    model=model_id,
                    contents=[
                        types.Content(role="user", parts=[types.Part(text=fix_prompt)])
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json"
                    )
                )
                
                fix_text = fix_response.text.strip() if fix_response.text else ""
                parsed = parse_json_response(fix_text)
        
        if parsed is None:
            # Complete failure - log all cards as errors
            for card in cards:
                errors.append({
                    "order_id": card.get("id", "unknown"),
                    "error": "JSON parse failed after retry",
                    "desc_preview": card.get("desc", "")[:300]
                })
                results.append({"order_id": card.get("id"), "line_items": []})
            return results, errors
        
        # Map results back to cards
        result_map = {}
        for item in parsed:
            if isinstance(item, dict) and "order_id" in item:
                result_map[item["order_id"]] = item
        
        # Match results to input cards
        for card in cards:
            order_id = card.get("id", "unknown")
            if order_id in result_map:
                result = result_map[order_id]
                # Validate line items
                line_items = result.get("line_items", [])
                validated_items = []
                for i, li in enumerate(line_items):
                    if isinstance(li, dict):
                        validated = validate_line_item(li)
                        if validated["line_index"] is None:
                            validated["line_index"] = i + 1
                        validated_items.append(validated)
                results.append({
                    "order_id": order_id,
                    "line_items": validated_items
                })
            else:
                # Result not found for this card
                results.append({"order_id": order_id, "line_items": []})
                if card.get("desc", "").strip():
                    errors.append({
                        "order_id": order_id,
                        "error": "Result not found in batch response",
                        "desc_preview": card.get("desc", "")[:300]
                    })
        
        return results, errors
        
    except Exception as e:
        logger.error(f"API error: {e}")
        # Return empty results for all cards
        for card in cards:
            errors.append({
                "order_id": card.get("id", "unknown"),
                "error": f"API error: {str(e)}",
                "desc_preview": card.get("desc", "")[:300]
            })
            results.append({"order_id": card.get("id"), "line_items": []})
        return results, errors


def flatten_line_items(results: list[dict]) -> list[dict]:
    """
    Flatten results to one row per line item.
    """
    flattened = []
    for result in results:
        order_id = result.get("order_id", "unknown")
        for item in result.get("line_items", []):
            row = {"order_id": order_id}
            row.update(item)
            flattened.append(row)
    return flattened


def write_csv(data: list[dict], filepath: Path, columns: list[str]) -> int:
    """
    Write data to CSV file with proper escaping.
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            # Ensure all columns exist
            clean_row = {col: row.get(col) for col in columns}
            writer.writerow(clean_row)
    return len(data)


def write_jsonl(data: list[dict], filepath: Path) -> int:
    """
    Write data to JSONL file.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        for record in data:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(data)


def run_dry_run(cards: list[dict], batch_size: int):
    """
    Run dry-run mode: estimate tokens and cost without making API calls.
    """
    logger.info("\n" + "=" * 60)
    logger.info("DRY RUN MODE - No API calls will be made")
    logger.info("=" * 60)
    
    # Count cards with descriptions
    cards_with_desc = [c for c in cards if c.get("desc", "").strip()]
    cards_empty = len(cards) - len(cards_with_desc)
    
    logger.info(f"\nInput Analysis:")
    logger.info(f"  Total cards:              {len(cards)}")
    logger.info(f"  Cards with descriptions:  {len(cards_with_desc)}")
    logger.info(f"  Cards without desc:       {cards_empty}")
    
    # Calculate batches
    num_batches = (len(cards_with_desc) + batch_size - 1) // batch_size
    logger.info(f"\nBatch Configuration:")
    logger.info(f"  Batch size:               {batch_size} cards")
    logger.info(f"  Total batches:            {num_batches}")
    logger.info(f"  Total API calls:          {num_batches}")
    
    # Estimate tokens
    system_tokens = estimate_tokens(SYSTEM_PROMPT)
    
    # Sample descriptions for token estimation
    desc_lengths = [len(c.get("desc", "")) for c in cards_with_desc]
    avg_desc_chars = sum(desc_lengths) / len(desc_lengths) if desc_lengths else 0
    max_desc_chars = max(desc_lengths) if desc_lengths else 0
    
    # Estimate per-batch input tokens
    avg_batch_desc_tokens = estimate_tokens("".join(
        c.get("desc", "") for c in cards_with_desc[:batch_size]
    ))
    # Add overhead for prompt structure
    prompt_overhead = estimate_tokens(build_batch_prompt(cards_with_desc[:batch_size])) - avg_batch_desc_tokens
    
    input_per_batch = system_tokens + prompt_overhead + (batch_size * estimate_tokens("x" * int(avg_desc_chars)))
    total_input_tokens = input_per_batch * num_batches
    
    # Estimate output tokens (assume ~2 line items per card, ~150 tokens each)
    avg_line_items_per_card = 2  # Conservative estimate
    output_per_item = 150
    output_per_batch = batch_size * avg_line_items_per_card * output_per_item
    total_output_tokens = output_per_batch * num_batches
    
    logger.info(f"\nToken Estimates:")
    logger.info(f"  System prompt:            {system_tokens:,} tokens")
    logger.info(f"  Avg desc length:          {avg_desc_chars:.0f} chars (~{estimate_tokens('x' * int(avg_desc_chars)):,} tokens)")
    logger.info(f"  Max desc length:          {max_desc_chars:,} chars (~{estimate_tokens('x' * max_desc_chars):,} tokens)")
    logger.info(f"  Input per batch:          ~{input_per_batch:,} tokens")
    logger.info(f"  Output per batch:         ~{output_per_batch:,} tokens (estimated)")
    logger.info(f"  Total input tokens:       ~{total_input_tokens:,}")
    logger.info(f"  Total output tokens:      ~{total_output_tokens:,}")
    
    # Cost estimate
    input_cost = (total_input_tokens / 1_000_000) * PRICE_INPUT_PER_M
    output_cost = (total_output_tokens / 1_000_000) * PRICE_OUTPUT_PER_M
    total_cost = input_cost + output_cost
    
    logger.info(f"\nCost Estimate (Gemini 2.5 Flash Lite):")
    logger.info(f"  Input cost:               ${input_cost:.4f}")
    logger.info(f"  Output cost:              ${output_cost:.4f}")
    logger.info(f"  TOTAL ESTIMATED COST:     ${total_cost:.4f}")
    
    # Time estimate (assume ~2 seconds per batch including rate limiting)
    time_estimate_sec = num_batches * 2
    time_estimate_min = time_estimate_sec / 60
    
    logger.info(f"\nTime Estimate:")
    logger.info(f"  ~{time_estimate_min:.1f} minutes ({time_estimate_sec} seconds)")
    
    logger.info("\n" + "=" * 60)
    logger.info("To run the actual extraction, remove --dry-run flag")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Extract structured line items from signage order descriptions"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=INPUT_FILE,
        help=f"Input JSON file path (default: {INPUT_FILE})"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_FILE,
        help=f"Output CSV file path (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "--errors",
        type=str,
        default=ERROR_FILE,
        help=f"Error log file path (default: {ERROR_FILE})"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Gemini model ID (default: {MODEL_ID})"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Cards per API call (default: {BATCH_SIZE})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cards to process (for testing)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate tokens and cost without making API calls"
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    script_dir = Path(__file__).parent
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = script_dir / input_path
    
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = script_dir / output_path
    
    error_path = Path(args.errors)
    if not error_path.is_absolute():
        error_path = script_dir / error_path
    
    model_id = args.model or MODEL_ID
    
    # Load input file
    logger.info("Loading input JSON file...")
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON: {e}")
        sys.exit(1)
    
    # Extract cards
    if isinstance(data, dict) and "cards" in data:
        cards = data["cards"]
        logger.info(f"Loaded Trello board with {len(cards)} cards")
    elif isinstance(data, list):
        cards = data
        logger.info(f"Loaded {len(cards)} records from JSON array")
    else:
        logger.error("Input must be a Trello board JSON or a JSON array")
        sys.exit(1)
    
    # Apply limit
    total_cards = len(cards)
    if args.limit and args.limit < len(cards):
        cards = cards[:args.limit]
        logger.info(f"Limited to {len(cards)} cards")
    
    # Dry run mode
    if args.dry_run:
        run_dry_run(cards, args.batch_size)
        return
    
    # Validate environment for actual run
    if not PROJECT_ID:
        logger.error("Error: BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT not set")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("LINE ITEM EXTRACTION PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Input:       {input_path}")
    logger.info(f"Output:      {output_path}")
    logger.info(f"Errors:      {error_path}")
    logger.info(f"Model:       {model_id}")
    logger.info(f"Project:     {PROJECT_ID}")
    logger.info(f"Batch size:  {args.batch_size}")
    logger.info("=" * 60)
    
    # Import genai only when actually running
    from google import genai
    
    # Initialize client
    logger.info("Initializing Gemini client...")
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {e}")
        sys.exit(1)
    
    # Process in batches
    logger.info("Starting extraction...")
    start_time = time.time()
    
    all_results = []
    all_errors = []
    batch_size = args.batch_size
    
    # Filter to cards with descriptions for batching
    cards_with_desc = [c for c in cards if c.get("desc", "").strip()]
    cards_empty = [c for c in cards if not c.get("desc", "").strip()]
    
    # Add empty results for cards without descriptions
    for card in cards_empty:
        all_results.append({"order_id": card.get("id"), "line_items": []})
    
    # Process cards with descriptions in batches
    num_batches = (len(cards_with_desc) + batch_size - 1) // batch_size
    
    for i in range(0, len(cards_with_desc), batch_size):
        batch = cards_with_desc[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        logger.info(f"Batch {batch_num}/{num_batches} ({len(batch)} cards)")
        
        results, errors = extract_line_items_batch(client, batch, model_id)
        all_results.extend(results)
        all_errors.extend(errors)
        
        # Progress
        total_items = sum(len(r.get("line_items", [])) for r in all_results)
        logger.info(f"  -> {total_items} total line items, {len(all_errors)} errors")
        
        # Rate limiting
        if batch_num < num_batches:
            time.sleep(1)
    
    elapsed = time.time() - start_time
    
    # Flatten and write output
    logger.info("Writing output...")
    flattened = flatten_line_items(all_results)
    write_csv(flattened, output_path, CSV_COLUMNS)
    
    if all_errors:
        write_jsonl(all_errors, error_path)
    
    # Summary
    orders_with_items = sum(1 for r in all_results if r.get("line_items"))
    high_conf = sum(1 for item in flattened if item.get("llm_confidence") == "high")
    med_conf = sum(1 for item in flattened if item.get("llm_confidence") == "medium")
    low_conf = sum(1 for item in flattened if item.get("llm_confidence") == "low")
    
    logger.info("\n" + "=" * 60)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Cards processed:     {len(cards)}")
    logger.info(f"Cards with items:    {orders_with_items}")
    logger.info(f"Extraction errors:   {len(all_errors)}")
    logger.info(f"Total line items:    {len(flattened)}")
    logger.info(f"  High confidence:   {high_conf}")
    logger.info(f"  Medium confidence: {med_conf}")
    logger.info(f"  Low confidence:    {low_conf}")
    logger.info(f"Time elapsed:        {elapsed:.1f}s")
    logger.info(f"Output: {output_path}")
    if all_errors:
        logger.info(f"Errors: {error_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
