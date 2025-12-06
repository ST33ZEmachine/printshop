"""
Evaluation Queries for Agent Testing

This script runs a series of test queries against the agent and compares
the results against known ground truth from BigQuery.

Usage:
    python eval_queries.py
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Tuple

from google.cloud import bigquery

# Ensure we have the BIGQUERY_PROJECT set
if not os.environ.get("BIGQUERY_PROJECT"):
    os.environ["BIGQUERY_PROJECT"] = "maxprint-479504"

PROJECT_ID = os.environ["BIGQUERY_PROJECT"]
TABLE = f"{PROJECT_ID}.trello_rag.bourquin_05122025_snapshot"


def get_ground_truth() -> Dict[str, Any]:
    """
    Get ground truth data from BigQuery for evaluation.
    """
    client = bigquery.Client(project=PROJECT_ID)
    
    results = {}
    
    # Query 1: Total cards count
    query = f"SELECT COUNT(*) as total FROM `{TABLE}`"
    result = list(client.query(query).result())
    results["total_cards"] = result[0].total
    
    # Query 2: Count of Paz Fuels orders
    query = f"""
        SELECT COUNT(*) as count 
        FROM `{TABLE}` 
        WHERE LOWER(purchaser) LIKE '%paz fuels%' 
           OR LOWER(name) LIKE '%paz fuels%'
    """
    result = list(client.query(query).result())
    results["paz_fuels_orders"] = result[0].count
    
    # Query 3: Top 5 purchasers by order count
    query = f"""
        SELECT purchaser, COUNT(*) as order_count
        FROM `{TABLE}`
        WHERE purchaser IS NOT NULL AND purchaser != ''
        GROUP BY purchaser
        ORDER BY order_count DESC
        LIMIT 5
    """
    result = list(client.query(query).result())
    results["top_5_purchasers"] = [
        {"purchaser": r.purchaser, "order_count": r.order_count}
        for r in result
    ]
    
    # Query 4: Cards with high confidence
    query = f"""
        SELECT COUNT(*) as count 
        FROM `{TABLE}` 
        WHERE buyer_confidence = 'high'
    """
    result = list(client.query(query).result())
    results["high_confidence_count"] = result[0].count
    
    # Query 5: Sample purchasers with their buyer emails (for verification)
    query = f"""
        SELECT purchaser, primary_buyer_email, primary_buyer_name
        FROM `{TABLE}`
        WHERE purchaser IS NOT NULL 
          AND primary_buyer_email IS NOT NULL
          AND purchaser != ''
        LIMIT 10
    """
    result = list(client.query(query).result())
    results["sample_purchaser_contacts"] = [
        {
            "purchaser": r.purchaser,
            "email": r.primary_buyer_email,
            "name": r.primary_buyer_name
        }
        for r in result
    ]
    
    # Query 6: Orders by list_name (status) distribution
    query = f"""
        SELECT list_name, COUNT(*) as count
        FROM `{TABLE}`
        WHERE list_name IS NOT NULL
        GROUP BY list_name
        ORDER BY count DESC
        LIMIT 10
    """
    result = list(client.query(query).result())
    results["orders_by_status"] = [
        {"status": r.list_name, "count": r.count}
        for r in result
    ]
    
    # Query 7: Unique purchasers count
    query = f"""
        SELECT COUNT(DISTINCT purchaser) as count
        FROM `{TABLE}`
        WHERE purchaser IS NOT NULL AND purchaser != ''
    """
    result = list(client.query(query).result())
    results["unique_purchasers"] = result[0].count
    
    return results


def print_ground_truth(results: Dict[str, Any]):
    """Print ground truth in a readable format."""
    print("\n" + "="*70)
    print("GROUND TRUTH DATA FROM BIGQUERY")
    print("="*70)
    
    print(f"\n1. Total Cards: {results['total_cards']:,}")
    print(f"2. Paz Fuels Orders: {results['paz_fuels_orders']}")
    print(f"3. High Confidence Extractions: {results['high_confidence_count']:,}")
    print(f"4. Unique Purchasers: {results['unique_purchasers']:,}")
    
    print("\n5. Top 5 Purchasers by Order Count:")
    for i, p in enumerate(results['top_5_purchasers'], 1):
        print(f"   {i}. {p['purchaser']}: {p['order_count']} orders")
    
    print("\n6. Orders by Status (Top 10):")
    for s in results['orders_by_status']:
        print(f"   - {s['status']}: {s['count']:,} orders")
    
    print("\n7. Sample Purchaser Contacts (for verification):")
    for c in results['sample_purchaser_contacts'][:5]:
        print(f"   - {c['purchaser']}")
        print(f"     Contact: {c['name']} ({c['email']})")
    
    print("="*70)


# Evaluation test cases - questions to ask the agent
EVAL_TEST_CASES = [
    {
        "id": "total_count",
        "question": "How many total cards/orders are in the bourquin_05122025_snapshot table?",
        "expected_field": "total_cards",
        "validation_type": "exact_number",
    },
    {
        "id": "paz_fuels",
        "question": "How many orders are from Paz Fuels in the bourquin_05122025_snapshot table?",
        "expected_field": "paz_fuels_orders",
        "validation_type": "number_in_response",
    },
    {
        "id": "top_purchaser",
        "question": "What is the top purchaser by number of orders in bourquin_05122025_snapshot?",
        "expected_field": "top_5_purchasers",
        "validation_type": "contains_top_purchaser",
    },
    {
        "id": "unique_purchasers",
        "question": "How many unique purchasers are in the bourquin_05122025_snapshot table?",
        "expected_field": "unique_purchasers",
        "validation_type": "number_in_response",
    },
]


async def run_agent_query(question: str) -> str:
    """Run a query through the agent and return the response."""
    from agent import root_agent
    from google.adk.runners import InMemoryRunner
    
    runner = InMemoryRunner(agent=root_agent)
    
    response_text = ""
    # Use run_debug which has a simpler API
    events = await runner.run_debug(
        question,
        user_id="eval_user",
        session_id=f"eval_session_{abs(hash(question)) % 10000}",
        verbose=False
    )
    
    # Extract text from events
    for event in events:
        if hasattr(event, 'content') and event.content:
            if hasattr(event.content, 'parts'):
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text += part.text
    
    return response_text


def validate_response(
    response: str,
    expected: Any,
    validation_type: str
) -> Tuple[bool, str]:
    """
    Validate an agent response against expected value.
    
    Returns:
        Tuple of (passed, explanation)
    """
    response_lower = response.lower()
    
    if validation_type == "exact_number":
        # Check if the exact number appears in response
        if str(expected) in response:
            return True, f"Found expected number {expected}"
        # Check with comma formatting
        formatted = f"{expected:,}"
        if formatted in response:
            return True, f"Found expected number {formatted}"
        return False, f"Expected {expected}, not found in response"
    
    elif validation_type == "number_in_response":
        # Check if the number appears somewhere in response
        if str(expected) in response:
            return True, f"Found {expected} in response"
        return False, f"Expected to find {expected} in response"
    
    elif validation_type == "contains_top_purchaser":
        # Check if top purchaser name is in response
        if expected and len(expected) > 0:
            top = expected[0]["purchaser"].lower()
            if top in response_lower:
                return True, f"Found top purchaser '{expected[0]['purchaser']}'"
        return False, f"Top purchaser not found in response"
    
    return False, "Unknown validation type"


async def run_evaluation():
    """Run full evaluation suite."""
    print("\n" + "="*70)
    print("AGENT EVALUATION SUITE")
    print("="*70)
    
    # Get ground truth
    print("\nFetching ground truth from BigQuery...")
    ground_truth = get_ground_truth()
    print_ground_truth(ground_truth)
    
    # Run agent queries
    print("\n" + "="*70)
    print("RUNNING AGENT EVALUATIONS")
    print("="*70)
    
    results = []
    passed = 0
    failed = 0
    
    for test in EVAL_TEST_CASES:
        print(f"\n--- Test: {test['id']} ---")
        print(f"Question: {test['question']}")
        
        try:
            response = await run_agent_query(test['question'])
            expected = ground_truth.get(test['expected_field'])
            
            is_valid, explanation = validate_response(
                response, expected, test['validation_type']
            )
            
            status = "✅ PASS" if is_valid else "❌ FAIL"
            print(f"Status: {status}")
            print(f"Explanation: {explanation}")
            print(f"Response excerpt: {response[:200]}...")
            
            if is_valid:
                passed += 1
            else:
                failed += 1
                
            results.append({
                "test_id": test['id'],
                "passed": is_valid,
                "explanation": explanation,
            })
            
        except Exception as e:
            print(f"Status: ❌ ERROR")
            print(f"Error: {e}")
            failed += 1
            results.append({
                "test_id": test['id'],
                "passed": False,
                "explanation": f"Error: {e}",
            })
    
    # Summary
    print("\n" + "="*70)
    print("EVALUATION SUMMARY")
    print("="*70)
    print(f"Total Tests: {len(EVAL_TEST_CASES)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Pass Rate: {passed/len(EVAL_TEST_CASES)*100:.1f}%")
    print("="*70)
    
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--ground-truth":
        # Just print ground truth
        results = get_ground_truth()
        print_ground_truth(results)
    else:
        # Run full evaluation
        asyncio.run(run_evaluation())

