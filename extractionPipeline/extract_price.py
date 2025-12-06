"""
Extraction Pipeline: Price Extraction from Trello Card Descriptions

This script uses an LLM (Google Gemini) to extract price information from
Trello card descriptions and adds a new 'price' field to each card.

Usage:
    python extract_price.py [--input INPUT_FILE] [--output OUTPUT_FILE] [--batch-size BATCH_SIZE]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
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
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
DEFAULT_BATCH_SIZE = 100  # Larger batch size to reduce API calls


def extract_price_from_batch(
    client: genai.Client,
    cards: List[Dict[str, Any]],
    model_id: str
) -> List[Dict[str, Any]]:
    """
    Extract price information from a batch of cards using the LLM.
    
    Args:
        client: Google Gemini client
        cards: List of card dictionaries
        model_id: Model identifier
        
    Returns:
        List of cards with added 'price' field
    """
    # Prepare batch prompt
    card_descriptions = []
    for i, card in enumerate(cards):
        card_name = card.get("name", "N/A")
        card_desc = card.get("desc", "")
        card_descriptions.append(
            f"Card {i+1}:\n"
            f"  Name: {card_name}\n"
            f"  Description: {card_desc}\n"
        )
    
    batch_text = "\n---\n".join(card_descriptions)
    
    prompt = f"""You are a data extraction assistant. Extract price information from the following Trello card descriptions.

For each card, identify ALL price values (in dollars) mentioned in the description. Prices might be:
- A single dollar amount (e.g., "$17.10", "$15", "$1,234.56")
- A per-unit price (e.g., "$15 ea.", "$10 each")
- A total price for an order
- Multiple prices (e.g., "$15 per unit, $150 total" or "Item 1: $10, Item 2: $20")

IMPORTANT: When multiple prices are found:
- Extract ALL prices found in the description
- Identify which is the PRIMARY/TOTAL price (usually the largest or explicitly labeled as "total")
- Include all other prices in the "all_prices" array
- If it's unclear which is primary, use the largest price as primary

Return a JSON array with one object per card. Each object should have:
- "index": the card index (0-based)
- "price": the PRIMARY/TOTAL numeric price value (as a number, not a string) or null if no price found
- "all_prices": an array of ALL prices found (as numbers), including the primary price. Empty array if none found.
- "price_type": "total", "per_unit", "single", "multiple", or null
- "confidence": "high", "medium", or "low" based on how clear the price is
- "notes": brief explanation of what prices were found (optional)

Example response format:
[
  {{"index": 0, "price": 17.10, "all_prices": [17.10], "price_type": "single", "confidence": "high", "notes": "Found '$17.10' in description"}},
  {{"index": 1, "price": 15.0, "all_prices": [15.0], "price_type": "per_unit", "confidence": "high", "notes": "Found '$15 ea.' in description"}},
  {{"index": 2, "price": 150.0, "all_prices": [15.0, 150.0], "price_type": "multiple", "confidence": "high", "notes": "Found '$15 per unit' and '$150 total'"}},
  {{"index": 3, "price": null, "all_prices": [], "price_type": null, "confidence": "low", "notes": "No price found"}}
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
            price_data = json.loads(response_text)
            # Ensure it's a list
            if not isinstance(price_data, list):
                logger.warning(f"Expected list but got {type(price_data)}, wrapping in list")
                price_data = [price_data]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            # Return cards with null prices on error
            price_data = [{
                "index": i, 
                "price": None, 
                "all_prices": [],
                "price_type": None,
                "confidence": "low", 
                "notes": f"Parse error: {str(e)}"
            } for i in range(len(cards))]
        
        # Map prices back to cards
        enriched_cards = []
        price_map = {item["index"]: item for item in price_data}
        
        for i, card in enumerate(cards):
            enriched_card = card.copy()
            price_info = price_map.get(i, {
                "price": None, 
                "all_prices": [],
                "price_type": None,
                "confidence": "low", 
                "notes": "No extraction data"
            })
            enriched_card["extracted_price"] = price_info.get("price")
            enriched_card["all_prices"] = price_info.get("all_prices", [])
            enriched_card["price_type"] = price_info.get("price_type")
            enriched_card["price_confidence"] = price_info.get("confidence", "low")
            enriched_card["price_notes"] = price_info.get("notes", "")
            enriched_cards.append(enriched_card)
        
        return enriched_cards
        
    except Exception as e:
        logger.error(f"Error extracting prices from batch: {e}")
        # Return cards with null prices on error
        enriched_cards = []
        for card in cards:
            enriched_card = card.copy()
            enriched_card["extracted_price"] = None
            enriched_card["all_prices"] = []
            enriched_card["price_type"] = None
            enriched_card["price_confidence"] = "low"
            enriched_card["price_notes"] = f"Extraction error: {str(e)}"
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
    Process all cards in batches, extracting price information.
    
    Args:
        client: Google Gemini client
        cards: List of all card dictionaries
        model_id: Model identifier
        batch_size: Number of cards to process per batch
        max_workers: Maximum number of concurrent batch requests
        
    Returns:
        List of enriched cards with price information
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
            executor.submit(extract_price_from_batch, client, batch, model_id): batch_idx
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
                    enriched_card["extracted_price"] = None
                    enriched_card["price_confidence"] = "low"
                    enriched_card["price_notes"] = f"Batch processing error: {str(e)}"
                    enriched_cards[start_idx + i] = enriched_card
    
    return enriched_cards


def main():
    parser = argparse.ArgumentParser(
        description="Extract price information from Trello card descriptions using LLM"
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
        help="Output JSON file path (default: input file with '_enriched' suffix)"
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
        output_path = input_path.parent / f"{input_path.stem}_enriched{input_path.suffix}"
    
    model_id = args.model or MODEL_ID
    
    logger.info(f"Input file: {input_path}")
    logger.info(f"Output file: {output_path}")
    logger.info(f"Model: {model_id}")
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Batch size: {args.batch_size}")
    
    # Load Trello JSON
    logger.info("Loading Trello JSON file...")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON file: {e}")
        sys.exit(1)
    
    cards = data.get("cards", [])
    logger.info(f"Loaded {len(cards)} cards")
    
    if not cards:
        logger.warning("No cards found in JSON file")
        sys.exit(0)
    
    # Initialize Gemini client
    logger.info("Initializing Gemini client...")
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        logger.error("Make sure you have Google Cloud credentials configured.")
        sys.exit(1)
    
    # Process cards
    logger.info("Starting price extraction...")
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
    cards_with_multiple_prices = sum(1 for c in enriched_cards if len(c.get("all_prices", [])) > 1)
    data["extraction_metadata"]["price_extraction"] = {
        "model": model_id,
        "batch_size": args.batch_size,
        "total_cards": len(enriched_cards),
        "cards_with_price": sum(1 for c in enriched_cards if c.get("extracted_price") is not None),
        "cards_without_price": sum(1 for c in enriched_cards if c.get("extracted_price") is None),
        "cards_with_multiple_prices": cards_with_multiple_prices,
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
    cards_with_price = sum(1 for c in enriched_cards if c.get("extracted_price") is not None)
    cards_with_multiple_prices = sum(1 for c in enriched_cards if len(c.get("all_prices", [])) > 1)
    high_confidence = sum(1 for c in enriched_cards if c.get("price_confidence") == "high")
    medium_confidence = sum(1 for c in enriched_cards if c.get("price_confidence") == "medium")
    low_confidence = sum(1 for c in enriched_cards if c.get("price_confidence") == "low")
    
    logger.info("\n" + "="*60)
    logger.info("EXTRACTION SUMMARY")
    logger.info("="*60)
    logger.info(f"Total cards processed: {len(enriched_cards)}")
    logger.info(f"Cards with price extracted: {cards_with_price} ({cards_with_price/len(enriched_cards)*100:.1f}%)")
    logger.info(f"  - Cards with multiple prices: {cards_with_multiple_prices}")
    logger.info(f"  - High confidence: {high_confidence}")
    logger.info(f"  - Medium confidence: {medium_confidence}")
    logger.info(f"  - Low confidence: {low_confidence}")
    logger.info(f"Cards without price: {len(enriched_cards) - cards_with_price}")
    logger.info("="*60)


if __name__ == "__main__":
    main()

