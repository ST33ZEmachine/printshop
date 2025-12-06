"""
Extraction Pipeline: Buyer Name and Email Extraction from Trello Cards

This script uses an LLM (Google Gemini) to extract buyer names and email addresses
from Trello card names and descriptions, storing them in separate fields.

It also extracts structured fields from card titles using simple string parsing:
- purchaser: The company/person name (first segment before "|")
- order_summary: Brief description of the order (second segment between first and second "|")

Usage:
    python extract_buyer_info.py [--input INPUT_FILE] [--output OUTPUT_FILE] [--batch-size BATCH_SIZE] [--limit LIMIT]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
DEFAULT_BATCH_SIZE = 100  # Larger batch size to reduce API calls


def extract_title_fields(card_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract purchaser and order_summary from card title using pipe delimiter.
    
    Card titles follow the format: "Company Name | Order Summary | Additional Info"
    
    Args:
        card_name: The card title/name string
        
    Returns:
        Tuple of (purchaser, order_summary) - either can be None if not found
    """
    if not card_name or "|" not in card_name:
        return None, None
    
    parts = [p.strip() for p in card_name.split("|")]
    
    purchaser = parts[0] if len(parts) > 0 and parts[0] else None
    order_summary = parts[1] if len(parts) > 1 and parts[1] else None
    
    return purchaser, order_summary


def enrich_cards_with_title_fields(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Add purchaser and order_summary fields to cards by parsing their titles.
    This is a fast, non-LLM operation.
    
    Args:
        cards: List of card dictionaries
        
    Returns:
        List of cards with added purchaser and order_summary fields
    """
    enriched = []
    for card in cards:
        enriched_card = card.copy()
        card_name = card.get("name", "")
        purchaser, order_summary = extract_title_fields(card_name)
        enriched_card["purchaser"] = purchaser
        enriched_card["order_summary"] = order_summary
        enriched.append(enriched_card)
    return enriched


def extract_buyer_info_from_batch(
    client: genai.Client,
    cards: List[Dict[str, Any]],
    model_id: str
) -> List[Dict[str, Any]]:
    """
    Extract buyer names and email addresses from a batch of cards using the LLM.
    
    Args:
        client: Google Gemini client
        cards: List of card dictionaries
        model_id: Model identifier
        
    Returns:
        List of cards with added buyer information fields
    """
    # Prepare batch prompt
    card_data = []
    for i, card in enumerate(cards):
        card_name = card.get("name", "N/A")
        card_desc = card.get("desc", "")
        card_data.append(
            f"[Card index={i}]\n"
            f"  Title: {card_name}\n"
            f"  Description: {card_desc}\n"
        )
    
    batch_text = "\n---\n".join(card_data)
    
    prompt = f"""You are a data extraction assistant. Extract buyer/customer names and email addresses from the following Trello cards.

For each card, identify:
1. Buyer/Customer names (the person or company placing the order)
2. Email addresses associated with the buyer

Names and emails can appear in:
- The card title (e.g., "John Smith - Company | Product")
- The card description
- Sometimes there are multiple names/emails (extract all)

IMPORTANT RULES:
- Extract ALL names and emails found (not just the first one)
- Names should be full names when available (e.g., "John Smith" not just "John")
- Email addresses should be complete and valid format
- If a name appears multiple times, include it only once
- If an email appears multiple times, include it only once
- If no name/email found, use empty array
- Distinguish between buyer names and other names (like "General Manager" titles - extract the person's name, not the title)
- CRITICAL: The "index" field in your response MUST exactly match the index shown in [Card index=N] for each card

Return a JSON array with one object per card. Each object should have:
- "index": the card index (MUST match the index=N shown above each card)
- "buyer_names": array of buyer/customer names found (as strings), empty array if none
- "buyer_emails": array of email addresses found (as strings), empty array if none
- "primary_buyer_name": the primary/most relevant buyer name (string or null)
- "primary_buyer_email": the primary/most relevant email (string or null)
- "confidence": "high", "medium", or "low" based on how clear the information is
- "notes": brief explanation of what was found (optional)

Example response format:
[
  {{
    "index": 0,
    "buyer_names": ["Christine Banford"],
    "buyer_emails": ["banfordchristine@gmail.com"],
    "primary_buyer_name": "Christine Banford",
    "primary_buyer_email": "banfordchristine@gmail.com",
    "confidence": "high",
    "notes": "Found name and email in description"
  }},
  {{
    "index": 1,
    "buyer_names": ["Ashley Mendonca"],
    "buyer_emails": ["gm@bwpkamloops.com"],
    "primary_buyer_name": "Ashley Mendonca",
    "primary_buyer_email": "gm@bwpkamloops.com",
    "confidence": "high",
    "notes": "Found name and email in description"
  }},
  {{
    "index": 2,
    "buyer_names": [],
    "buyer_emails": [],
    "primary_buyer_name": null,
    "primary_buyer_email": null,
    "confidence": "low",
    "notes": "No buyer information found"
  }}
]

Cards to process:
{batch_text}

Return only the JSON array, no other text."""

    try:
        # Call Gemini API
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,  # Low temperature for consistent extraction
                response_mime_type="application/json"
            )
        )
        
        # Parse response
        response_text = response.text.strip()
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        elif response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        # Parse JSON
        try:
            buyer_data = json.loads(response_text)
            # Ensure it's a list
            if not isinstance(buyer_data, list):
                logger.warning(f"Expected list but got {type(buyer_data)}, wrapping in list")
                buyer_data = [buyer_data]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            # Return cards with empty buyer info on error
            buyer_data = [{
                "index": i,
                "buyer_names": [],
                "buyer_emails": [],
                "primary_buyer_name": None,
                "primary_buyer_email": None,
                "confidence": "low",
                "notes": f"Parse error: {str(e)}"
            } for i in range(len(cards))]
        
        # Map buyer info back to cards
        enriched_cards = []
        buyer_map = {item["index"]: item for item in buyer_data}
        
        for i, card in enumerate(cards):
            enriched_card = card.copy()
            buyer_info = buyer_map.get(i, {
                "buyer_names": [],
                "buyer_emails": [],
                "primary_buyer_name": None,
                "primary_buyer_email": None,
                "confidence": "low",
                "notes": "No extraction data"
            })
            enriched_card["buyer_names"] = buyer_info.get("buyer_names", [])
            enriched_card["buyer_emails"] = buyer_info.get("buyer_emails", [])
            enriched_card["primary_buyer_name"] = buyer_info.get("primary_buyer_name")
            enriched_card["primary_buyer_email"] = buyer_info.get("primary_buyer_email")
            enriched_card["buyer_confidence"] = buyer_info.get("confidence", "low")
            enriched_card["buyer_notes"] = buyer_info.get("notes", "")
            enriched_cards.append(enriched_card)
        
        return enriched_cards
        
    except Exception as e:
        logger.error(f"Error extracting buyer info from batch: {e}")
        # Return cards with empty buyer info on error
        enriched_cards = []
        for card in cards:
            enriched_card = card.copy()
            enriched_card["buyer_names"] = []
            enriched_card["buyer_emails"] = []
            enriched_card["primary_buyer_name"] = None
            enriched_card["primary_buyer_email"] = None
            enriched_card["buyer_confidence"] = "low"
            enriched_card["buyer_notes"] = f"Extraction error: {str(e)}"
            enriched_cards.append(enriched_card)
        return enriched_cards


def process_cards(
    client: genai.Client,
    cards: List[Dict[str, Any]],
    model_id: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = 3
) -> List[Dict[str, Any]]:
    """
    Process all cards in batches, extracting buyer information.
    
    Args:
        client: Google Gemini client
        cards: List of all card dictionaries
        model_id: Model identifier
        batch_size: Number of cards to process per batch
        max_workers: Maximum number of concurrent batch requests
        
    Returns:
        List of enriched cards with buyer information
    """
    total_cards = len(cards)
    logger.info(f"Processing {total_cards} cards in batches of {batch_size}")
    
    # Split into batches
    batches = []
    for i in range(0, total_cards, batch_size):
        batch = cards[i:i + batch_size]
        batches.append((i // batch_size, batch))
    
    logger.info(f"Created {len(batches)} batches")
    
    enriched_cards = [None] * total_cards
    
    # Process batches with limited concurrency
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_buyer_info_from_batch, client, batch, model_id): batch_idx
            for batch_idx, batch in batches
        }
        
        completed = 0
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_results = future.result()
                # Place results in correct positions
                start_idx = batch_idx * batch_size
                for i, enriched_card in enumerate(batch_results):
                    enriched_cards[start_idx + i] = enriched_card
                completed += 1
                logger.info(f"Completed batch {batch_idx + 1}/{len(batches)} ({completed * batch_size}/{total_cards} cards)")
            except Exception as e:
                logger.error(f"Error processing batch {batch_idx}: {e}")
                # Fill with unenriched cards
                start_idx = batch_idx * batch_size
                batch = batches[batch_idx][1]
                for i, card in enumerate(batch):
                    enriched_card = card.copy()
                    enriched_card["buyer_names"] = []
                    enriched_card["buyer_emails"] = []
                    enriched_card["primary_buyer_name"] = None
                    enriched_card["primary_buyer_email"] = None
                    enriched_card["buyer_confidence"] = "low"
                    enriched_card["buyer_notes"] = f"Batch processing error: {str(e)}"
                    enriched_cards[start_idx + i] = enriched_card
    
    return enriched_cards


def main():
    parser = argparse.ArgumentParser(
        description="Extract buyer names and email addresses from Trello cards using LLM"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="rDbSqbLq - board-archive-2021-0707.json",
        help="Input Trello JSON file path"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path (default: input file with '_buyer_enriched' suffix)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of cards to process per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=3,
        help="Maximum number of concurrent batch requests (default: 3)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Gemini model ID (default: {MODEL_ID})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cards to process (for testing)"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    if not PROJECT_ID:
        logger.error("BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable not set.")
        sys.exit(1)
    
    # Determine output path
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_buyer_enriched{input_path.suffix}"
    
    model_id = args.model or MODEL_ID
    
    logger.info(f"Input file: {input_path}")
    logger.info(f"Output file: {output_path}")
    logger.info(f"Model: {model_id}")
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Batch size: {args.batch_size}")
    if args.limit:
        logger.info(f"Card limit: {args.limit}")
    
    # Load Trello JSON
    logger.info("Loading Trello JSON file...")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON file: {e}")
        sys.exit(1)
    
    cards = data.get("cards", [])
    total_cards_in_file = len(cards)
    logger.info(f"Loaded {total_cards_in_file} cards from file")
    
    # Apply limit if specified
    if args.limit and args.limit < len(cards):
        cards = cards[:args.limit]
        logger.info(f"Limited to {len(cards)} cards for processing")
    
    if not cards:
        logger.warning("No cards found in JSON file")
        sys.exit(0)
    
    # First, extract title fields (purchaser and order_summary) - fast, no LLM needed
    logger.info("Extracting purchaser and order_summary from card titles...")
    cards = enrich_cards_with_title_fields(cards)
    cards_with_purchaser = sum(1 for c in cards if c.get("purchaser"))
    cards_with_order_summary = sum(1 for c in cards if c.get("order_summary"))
    logger.info(f"  - Cards with purchaser: {cards_with_purchaser}/{len(cards)}")
    logger.info(f"  - Cards with order_summary: {cards_with_order_summary}/{len(cards)}")
    
    # Initialize Gemini client
    logger.info("Initializing Gemini client...")
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        logger.error("Make sure you have Google Cloud credentials configured.")
        sys.exit(1)
    
    # Process cards
    logger.info("Starting buyer information extraction...")
    enriched_cards = process_cards(
        client,
        cards,
        model_id,
        batch_size=args.batch_size,
        max_workers=args.max_workers
    )
    
    # Update data with enriched cards
    data["cards"] = enriched_cards
    
    # Add metadata about the extraction
    if "extraction_metadata" not in data:
        data["extraction_metadata"] = {}
    cards_with_names = sum(1 for c in enriched_cards if c.get("buyer_names") and len(c.get("buyer_names", [])) > 0)
    cards_with_emails = sum(1 for c in enriched_cards if c.get("buyer_emails") and len(c.get("buyer_emails", [])) > 0)
    cards_with_both = sum(1 for c in enriched_cards if 
                         c.get("buyer_names") and len(c.get("buyer_names", [])) > 0 and
                         c.get("buyer_emails") and len(c.get("buyer_emails", [])) > 0)
    cards_with_multiple_names = sum(1 for c in enriched_cards if len(c.get("buyer_names", [])) > 1)
    cards_with_multiple_emails = sum(1 for c in enriched_cards if len(c.get("buyer_emails", [])) > 1)
    cards_with_purchaser = sum(1 for c in enriched_cards if c.get("purchaser"))
    cards_with_order_summary = sum(1 for c in enriched_cards if c.get("order_summary"))
    
    data["extraction_metadata"]["buyer_extraction"] = {
        "model": model_id,
        "batch_size": args.batch_size,
        "total_cards": len(enriched_cards),
        "cards_with_purchaser": cards_with_purchaser,
        "cards_with_order_summary": cards_with_order_summary,
        "cards_with_names": cards_with_names,
        "cards_with_emails": cards_with_emails,
        "cards_with_both": cards_with_both,
        "cards_with_multiple_names": cards_with_multiple_names,
        "cards_with_multiple_emails": cards_with_multiple_emails,
        "limit_applied": args.limit,
    }
    
    # Save enriched JSON
    logger.info(f"Saving enriched data to {output_path}...")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully saved enriched data to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save output file: {e}")
        sys.exit(1)
    
    # Print summary
    high_confidence = sum(1 for c in enriched_cards if c.get("buyer_confidence") == "high")
    medium_confidence = sum(1 for c in enriched_cards if c.get("buyer_confidence") == "medium")
    low_confidence = sum(1 for c in enriched_cards if c.get("buyer_confidence") == "low")
    
    logger.info("\n" + "="*60)
    logger.info("EXTRACTION SUMMARY")
    logger.info("="*60)
    logger.info(f"Total cards processed: {len(enriched_cards)}")
    if args.limit:
        logger.info(f"  (Limited from {total_cards_in_file} total cards in file)")
    logger.info("-"*60)
    logger.info("TITLE PARSING (purchaser | order_summary):")
    logger.info(f"Cards with purchaser: {cards_with_purchaser} ({cards_with_purchaser/len(enriched_cards)*100:.1f}%)")
    logger.info(f"Cards with order_summary: {cards_with_order_summary} ({cards_with_order_summary/len(enriched_cards)*100:.1f}%)")
    logger.info("-"*60)
    logger.info("LLM EXTRACTION (buyer contact names & emails):")
    logger.info(f"Cards with buyer names: {cards_with_names} ({cards_with_names/len(enriched_cards)*100:.1f}%)")
    logger.info(f"  - Cards with multiple names: {cards_with_multiple_names}")
    logger.info(f"Cards with buyer emails: {cards_with_emails} ({cards_with_emails/len(enriched_cards)*100:.1f}%)")
    logger.info(f"  - Cards with multiple emails: {cards_with_multiple_emails}")
    logger.info(f"Cards with both name and email: {cards_with_both} ({cards_with_both/len(enriched_cards)*100:.1f}%)")
    logger.info(f"Confidence levels:")
    logger.info(f"  - High confidence: {high_confidence}")
    logger.info(f"  - Medium confidence: {medium_confidence}")
    logger.info(f"  - Low confidence: {low_confidence}")
    logger.info("="*60)


if __name__ == "__main__":
    main()

