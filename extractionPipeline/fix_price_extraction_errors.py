#!/usr/bin/env python3
"""
Fix price extraction errors in BigQuery line items table.

Some prices were incorrectly extracted where "total" prices were interpreted
as unit prices, then multiplied by quantity, creating massive overstatements.

This script:
1. Identifies records where price * quantity > $100k
2. Checks if raw_price_text contains "total" 
3. If so, divides price by quantity to get correct unit price
4. Updates the records in BigQuery
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

# Load environment variables from .env file
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
load_dotenv()

# Configuration
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT_ID:
    print("Error: BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable not set.")
    print("Set it in your .env file or export it before running.")
    sys.exit(1)

DATASET_ID = "trello_rag"
TABLE_ID = "bourquin_05122025_snapshot_lineitems"

# Use owner account for write access (don't use read-only service account)
# Unset GOOGLE_APPLICATION_CREDENTIALS to use default credentials
if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

client = bigquery.Client(project=PROJECT_ID)


def find_problematic_records():
    """Find records where price * quantity > $100k and likely represent total prices."""
    query = """
    SELECT 
      order_id,
      line_index,
      price,
      quantity,
      price * COALESCE(quantity, 1) as line_total,
      raw_price_text,
      price_validated,
      material,
      description,
      raw_line_text
    FROM `{project}.{dataset}.{table}`
    WHERE price IS NOT NULL 
      AND price * COALESCE(quantity, 1) > 100000
    ORDER BY price * COALESCE(quantity, 1) DESC
    """.format(project=PROJECT_ID, dataset=DATASET_ID, table=TABLE_ID)
    
    result = client.query(query).result()
    return list(result)


def identify_fixes(records):
    """Identify which records need fixing based on raw_price_text."""
    fixes = []
    
    for row in records:
        raw_text = (row.raw_price_text or "").lower()
        is_total = "total" in raw_text or "tot" in raw_text
        
        # Only fix if:
        # 1. Contains "total" in price text
        # 2. Has quantity > 1
        # 3. Price seems unreasonably high for a unit price
        if is_total and row.quantity and row.quantity > 1:
            corrected_unit_price = row.price / row.quantity
            fixes.append({
                'order_id': row.order_id,
                'line_index': row.line_index,
                'current_price': row.price,
                'quantity': row.quantity,
                'corrected_price': corrected_unit_price,
                'line_total': row.price * row.quantity,
                'raw_price_text': row.raw_price_text,
                'material': row.material,
                'description': row.description
            })
    
    return fixes


def preview_fixes(fixes):
    """Preview the fixes that will be made."""
    print("=" * 80)
    print("PREVIEW OF FIXES")
    print("=" * 80)
    print(f"\nFound {len(fixes)} records to fix:\n")
    
    total_correction = 0
    for fix in fixes:
        old_total = fix['line_total']
        new_total = fix['corrected_price'] * fix['quantity']
        correction = old_total - new_total
        total_correction += correction
        
        print(f"Order: {fix['order_id']} | Line: {fix['line_index']}")
        print(f"  Current: ${fix['current_price']:,.2f} × {fix['quantity']} = ${old_total:,.2f}")
        print(f"  Corrected: ${fix['corrected_price']:,.2f} × {fix['quantity']} = ${new_total:,.2f}")
        print(f"  Reduction: ${correction:,.2f}")
        print(f"  Raw price text: '{fix['raw_price_text']}'")
        print("-" * 80)
    
    print(f"\nTotal revenue correction: ${total_correction:,.2f}")
    return fixes


def apply_fixes(fixes, dry_run=True):
    """Apply fixes to BigQuery table."""
    if not fixes:
        print("No fixes to apply.")
        return
    
    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 80)
        return
    
    print("\n" + "=" * 80)
    print("APPLYING FIXES TO BIGQUERY")
    print("=" * 80)
    
    # Build UPDATE statements
    updates = []
    for fix in fixes:
        update_query = """
        UPDATE `{project}.{dataset}.{table}`
        SET price = {corrected_price}
        WHERE order_id = '{order_id}' 
          AND line_index = {line_index}
        """.format(
            project=PROJECT_ID,
            dataset=DATASET_ID,
            table=TABLE_ID,
            corrected_price=fix['corrected_price'],
            order_id=fix['order_id'],
            line_index=fix['line_index']
        )
        updates.append(update_query)
    
    # Execute updates
    for i, update_query in enumerate(updates, 1):
        try:
            print(f"Updating record {i}/{len(updates)}: {fixes[i-1]['order_id']} line {fixes[i-1]['line_index']}")
            client.query(update_query).result()
            print("  ✓ Success")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    print(f"\n✓ Applied {len(updates)} fixes")


def main(dry_run=True):
    print("=" * 80)
    print("FIX PRICE EXTRACTION ERRORS")
    print("=" * 80)
    print(f"Project: {PROJECT_ID}")
    print(f"Dataset: {DATASET_ID}")
    print(f"Table: {TABLE_ID}")
    if dry_run:
        print("Mode: DRY RUN (no changes will be made)")
    else:
        print("Mode: APPLY FIXES (changes will be written to BigQuery)")
    print()
    
    # Find problematic records
    print("Step 1: Finding records with price * quantity > $100k...")
    records = find_problematic_records()
    print(f"Found {len(records)} records with price * quantity > $100k\n")
    
    # Identify fixes
    print("Step 2: Identifying records that need fixing...")
    fixes = identify_fixes(records)
    print(f"Identified {len(fixes)} records to fix\n")
    
    # Preview fixes
    preview_fixes(fixes)
    
    # Apply fixes if not dry run
    if fixes and not dry_run:
        print("\n" + "=" * 80)
        response = input("Apply these fixes? (yes/no): ").strip().lower()
        if response == 'yes':
            apply_fixes(fixes, dry_run=False)
        else:
            print("Cancelled.")
    elif fixes and dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE")
        print("Run with --apply flag to actually apply these fixes")
    else:
        print("\nNo fixes needed!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fix price extraction errors in BigQuery")
    parser.add_argument("--apply", action="store_true", help="Actually apply fixes (default is dry-run)")
    args = parser.parse_args()
    
    main(dry_run=not args.apply)

