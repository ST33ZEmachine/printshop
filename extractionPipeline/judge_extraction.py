"""
Extraction Judge: LLM-based Quality Assessment

This script uses an LLM (Google Gemini) to review and grade the extraction results
from the buyer information extraction pipeline. It evaluates:
- Accuracy of extracted names and emails
- Completeness (did we miss anything?)
- Quality of primary buyer selection
- Overall extraction quality

Usage:
    python judge_extraction.py [--input ENRICHED_FILE] [--output OUTPUT_FILE] [--sample-size N]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
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
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
DEFAULT_BATCH_SIZE = 100  # Larger batch size to reduce API calls


def judge_extraction_batch(
    client: genai.Client,
    cards: List[Dict[str, Any]],
    model_id: str
) -> List[Dict[str, Any]]:
    """
    Judge/evaluate the extraction quality for a batch of cards using the LLM.
    
    Args:
        client: Google Gemini client
        cards: List of card dictionaries with extraction results
        model_id: Model identifier
        
    Returns:
        List of cards with added judgment/evaluation fields
    """
    # Prepare batch for judgment
    card_data = []
    for i, card in enumerate(cards):
        card_name = card.get("name", "N/A")
        card_desc = card.get("desc", "")
        extracted_names = card.get("buyer_names", [])
        extracted_emails = card.get("buyer_emails", [])
        primary_name = card.get("primary_buyer_name")
        primary_email = card.get("primary_buyer_email")
        extraction_confidence = card.get("buyer_confidence", "low")
        extraction_notes = card.get("buyer_notes", "")
        
        card_data.append(
            f"Card {i+1}:\n"
            f"  Title: {card_name}\n"
            f"  Description: {card_desc}\n"
            f"  --- EXTRACTION RESULTS ---\n"
            f"  Extracted Names: {extracted_names}\n"
            f"  Extracted Emails: {extracted_emails}\n"
            f"  Primary Name: {primary_name}\n"
            f"  Primary Email: {primary_email}\n"
            f"  Extraction Confidence: {extraction_confidence}\n"
            f"  Extraction Notes: {extraction_notes}\n"
        )
    
    batch_text = "\n---\n".join(card_data)
    
    prompt = f"""You are a quality assurance judge evaluating buyer information extraction results from Trello cards.

For each card, you need to:
1. Review the ORIGINAL card title and description
2. Evaluate the EXTRACTION RESULTS (names, emails, primary buyer)
3. Determine if the extraction is ACCURATE, COMPLETE, and CORRECT

Evaluation Criteria:
- **Accuracy**: Are the extracted names/emails actually buyer/customer information? (not other people mentioned)
- **Completeness**: Did the extraction miss any buyer names or emails that are present?
- **Correctness**: Is the primary buyer correctly identified?
- **False Positives**: Are there extracted items that are NOT buyer information?
- **False Negatives**: Are there buyer names/emails in the original that were NOT extracted?

For each card, provide:
- A grade: "A" (excellent), "B" (good), "C" (acceptable), "D" (poor), or "F" (failed)
- Accuracy score: 0-100 (how accurate are the extractions?)
- Completeness score: 0-100 (how complete is the extraction?)
- Overall score: 0-100 (weighted average)
- Issues found: List of any problems (false positives, false negatives, incorrect primary buyer, etc.)
- Suggestions: How to improve the extraction

Return a JSON array with one object per card. Each object should have:
- "index": the card index (0-based)
- "grade": letter grade (A-F)
- "accuracy_score": 0-100
- "completeness_score": 0-100
- "overall_score": 0-100
- "false_positives": array of extracted items that are NOT buyer information (empty if none)
- "false_negatives": array of buyer information that was MISSED (empty if none)
- "primary_buyer_correct": boolean - is the primary buyer correctly identified?
- "issues": array of strings describing problems found (empty if none)
- "suggestions": array of strings with improvement suggestions (empty if none)
- "judge_notes": string with overall assessment

Example response format:
[
  {{
    "index": 0,
    "grade": "A",
    "accuracy_score": 95,
    "completeness_score": 100,
    "overall_score": 97,
    "false_positives": [],
    "false_negatives": [],
    "primary_buyer_correct": true,
    "issues": [],
    "suggestions": [],
    "judge_notes": "Excellent extraction - all buyer information correctly identified"
  }},
  {{
    "index": 1,
    "grade": "C",
    "accuracy_score": 80,
    "completeness_score": 50,
    "overall_score": 65,
    "false_positives": ["General Manager"],
    "false_negatives": ["john@example.com"],
    "primary_buyer_correct": false,
    "issues": ["Extracted job title instead of name", "Missed email address in description"],
    "suggestions": ["Filter out job titles", "Check for emails in all sections"],
    "judge_notes": "Extraction missed some information and included non-buyer data"
  }}
]

Cards to evaluate:
{batch_text}

Return only the JSON array, no other text."""

    try:
        # Call Gemini API
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,  # Slightly higher for judgment reasoning
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
            judgment_data = json.loads(response_text)
            # Ensure it's a list
            if not isinstance(judgment_data, list):
                logger.warning(f"Expected list but got {type(judgment_data)}, wrapping in list")
                judgment_data = [judgment_data]
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            # Return cards with default judgment on error
            judgment_data = [{
                "index": i,
                "grade": "F",
                "accuracy_score": 0,
                "completeness_score": 0,
                "overall_score": 0,
                "false_positives": [],
                "false_negatives": [],
                "primary_buyer_correct": False,
                "issues": [f"Parse error: {str(e)}"],
                "suggestions": [],
                "judge_notes": "Failed to parse judgment"
            } for i in range(len(cards))]
        
        # Map judgments back to cards
        judged_cards = []
        judgment_map = {item["index"]: item for item in judgment_data}
        
        for i, card in enumerate(cards):
            judged_card = card.copy()
            judgment = judgment_map.get(i, {
                "grade": "F",
                "accuracy_score": 0,
                "completeness_score": 0,
                "overall_score": 0,
                "false_positives": [],
                "false_negatives": [],
                "primary_buyer_correct": False,
                "issues": ["No judgment data"],
                "suggestions": [],
                "judge_notes": "No judgment available"
            })
            # Add judgment fields
            judged_card["judgment"] = judgment
            judged_cards.append(judged_card)
        
        return judged_cards
        
    except Exception as e:
        logger.error(f"Error judging extraction batch: {e}")
        # Return cards with default judgment on error
        judged_cards = []
        for card in cards:
            judged_card = card.copy()
            judged_card["judgment"] = {
                "grade": "F",
                "accuracy_score": 0,
                "completeness_score": 0,
                "overall_score": 0,
                "false_positives": [],
                "false_negatives": [],
                "primary_buyer_correct": False,
                "issues": [f"Judgment error: {str(e)}"],
                "suggestions": [],
                "judge_notes": f"Error during judgment: {str(e)}"
            }
            judged_cards.append(judged_card)
        return judged_cards


def process_cards_for_judgment(
    client: genai.Client,
    cards: List[Dict[str, Any]],
    model_id: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = 2  # Lower concurrency for judgment
) -> List[Dict[str, Any]]:
    """
    Process all cards in batches for judgment/evaluation.
    
    Args:
        client: Google Gemini client
        cards: List of all card dictionaries with extraction results
        model_id: Model identifier
        batch_size: Number of cards to process per batch
        max_workers: Maximum number of concurrent batch requests
        
    Returns:
        List of cards with added judgment fields
    """
    total_cards = len(cards)
    logger.info(f"Judging {total_cards} cards in batches of {batch_size}")
    
    # Split into batches
    batches = []
    for i in range(0, total_cards, batch_size):
        batch = cards[i:i + batch_size]
        batches.append((i // batch_size, batch))
    
    logger.info(f"Created {len(batches)} batches for judgment")
    
    judged_cards = [None] * total_cards
    
    # Process batches with limited concurrency
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(judge_extraction_batch, client, batch, model_id): batch_idx
            for batch_idx, batch in batches
        }
        
        completed = 0
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_results = future.result()
                # Place results in correct positions
                start_idx = batch_idx * batch_size
                for i, judged_card in enumerate(batch_results):
                    judged_cards[start_idx + i] = judged_card
                completed += 1
                logger.info(f"Completed judgment batch {batch_idx + 1}/{len(batches)} ({completed * batch_size}/{total_cards} cards)")
            except Exception as e:
                logger.error(f"Error processing judgment batch {batch_idx}: {e}")
                # Fill with default judgments
                start_idx = batch_idx * batch_size
                batch = batches[batch_idx][1]
                for i, card in enumerate(batch):
                    judged_card = card.copy()
                    judged_card["judgment"] = {
                        "grade": "F",
                        "accuracy_score": 0,
                        "completeness_score": 0,
                        "overall_score": 0,
                        "false_positives": [],
                        "false_negatives": [],
                        "primary_buyer_correct": False,
                        "issues": [f"Batch processing error: {str(e)}"],
                        "suggestions": [],
                        "judge_notes": f"Error: {str(e)}"
                    }
                    judged_cards[start_idx + i] = judged_card
    
    return judged_cards


def calculate_statistics(judged_cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate overall statistics from judgments."""
    total = len(judged_cards)
    if total == 0:
        return {}
    
    grades = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    accuracy_scores = []
    completeness_scores = []
    overall_scores = []
    false_positives_count = 0
    false_negatives_count = 0
    primary_correct_count = 0
    total_issues = 0
    
    for card in judged_cards:
        judgment = card.get("judgment", {})
        grade = judgment.get("grade", "F")
        if grade in grades:
            grades[grade] += 1
        
        accuracy_scores.append(judgment.get("accuracy_score", 0))
        completeness_scores.append(judgment.get("completeness_score", 0))
        overall_scores.append(judgment.get("overall_score", 0))
        
        if judgment.get("false_positives"):
            false_positives_count += len(judgment.get("false_positives", []))
        if judgment.get("false_negatives"):
            false_negatives_count += len(judgment.get("false_negatives", []))
        if judgment.get("primary_buyer_correct", False):
            primary_correct_count += 1
        
        if judgment.get("issues"):
            total_issues += len(judgment.get("issues", []))
    
    return {
        "total_cards": total,
        "grade_distribution": grades,
        "average_accuracy": sum(accuracy_scores) / total if accuracy_scores else 0,
        "average_completeness": sum(completeness_scores) / total if completeness_scores else 0,
        "average_overall": sum(overall_scores) / total if overall_scores else 0,
        "total_false_positives": false_positives_count,
        "total_false_negatives": false_negatives_count,
        "primary_buyer_correct_rate": primary_correct_count / total if total > 0 else 0,
        "total_issues": total_issues,
        "cards_with_issues": sum(1 for c in judged_cards if c.get("judgment", {}).get("issues"))
    }


def main():
    parser = argparse.ArgumentParser(
        description="Judge and evaluate buyer information extraction results using LLM"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="rDbSqbLq - board-archive-2021-0707_buyer_enriched.json",
        help="Input enriched JSON file path"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path (default: input file with '_judged' suffix)"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Only judge a sample of N cards (for testing, default: judge all)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of cards to judge per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="Maximum number of concurrent batch requests (default: 2)"
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
        output_path = input_path.parent / f"{input_path.stem}_judged{input_path.suffix}"
    
    model_id = args.model or MODEL_ID
    
    logger.info(f"Input file: {input_path}")
    logger.info(f"Output file: {output_path}")
    logger.info(f"Model: {model_id}")
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Batch size: {args.batch_size}")
    if args.sample_size:
        logger.info(f"Sample size: {args.sample_size} (testing mode)")
    
    # Load enriched JSON
    logger.info("Loading enriched JSON file...")
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
    
    # Sample if requested
    if args.sample_size and args.sample_size < len(cards):
        import random
        cards = random.sample(cards, args.sample_size)
        logger.info(f"Sampling {args.sample_size} cards for judgment")
    
    # Initialize Gemini client
    logger.info("Initializing Gemini client...")
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        logger.error("Make sure you have Google Cloud credentials configured.")
        sys.exit(1)
    
    # Process cards for judgment
    logger.info("Starting judgment/evaluation...")
    judged_cards = process_cards_for_judgment(
        client,
        cards,
        model_id,
        batch_size=args.batch_size,
        max_workers=args.max_workers
    )
    
    # Update data with judged cards
    data["cards"] = judged_cards
    
    # Calculate statistics
    stats = calculate_statistics(judged_cards)
    
    # Add judgment metadata
    if "extraction_metadata" not in data:
        data["extraction_metadata"] = {}
    data["extraction_metadata"]["judgment"] = {
        "model": model_id,
        "batch_size": args.batch_size,
        "judgment_date": datetime.now().isoformat(),
        "statistics": stats
    }
    
    # Save judged JSON
    logger.info(f"Saving judged data to {output_path}...")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully saved judged data to {output_path}")
    except Exception as e:
        logger.error(f"Failed to save output file: {e}")
        sys.exit(1)
    
    # Print summary
    logger.info("\n" + "="*60)
    logger.info("JUDGMENT SUMMARY")
    logger.info("="*60)
    logger.info(f"Total cards judged: {stats.get('total_cards', 0)}")
    logger.info(f"\nGrade Distribution:")
    for grade, count in stats.get("grade_distribution", {}).items():
        pct = (count / stats.get('total_cards', 1)) * 100
        logger.info(f"  {grade}: {count} ({pct:.1f}%)")
    logger.info(f"\nAverage Scores:")
    logger.info(f"  Accuracy: {stats.get('average_accuracy', 0):.1f}/100")
    logger.info(f"  Completeness: {stats.get('average_completeness', 0):.1f}/100")
    logger.info(f"  Overall: {stats.get('average_overall', 0):.1f}/100")
    logger.info(f"\nQuality Metrics:")
    logger.info(f"  Primary buyer correct: {stats.get('primary_buyer_correct_rate', 0)*100:.1f}%")
    logger.info(f"  Total false positives: {stats.get('total_false_positives', 0)}")
    logger.info(f"  Total false negatives: {stats.get('total_false_negatives', 0)}")
    logger.info(f"  Cards with issues: {stats.get('cards_with_issues', 0)}")
    logger.info("="*60)


if __name__ == "__main__":
    main()

