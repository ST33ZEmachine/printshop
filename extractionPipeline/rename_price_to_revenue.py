#!/usr/bin/env python3
"""
Rename 'price' column to 'revenue' and add 'unit_price' column.

The 'price' column actually represents total revenue for the line item,
not unit price. We need to:
1. Rename 'price' -> 'revenue' 
2. Add 'unit_price' = revenue / quantity
3. Update both CSV and BigQuery
"""

import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery

# Load environment variables
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")
load_dotenv()

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT_ID:
    print("Error: BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable not set.")
    sys.exit(1)

DATASET_ID = "trello_rag"
TABLE_ID = "bourquin_05122025_snapshot_lineitems"

# Use owner account for write access
if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

client = bigquery.Client(project=PROJECT_ID)


def update_csv_file(csv_path: Path):
    """Update CSV: rename price->revenue, add unit_price column."""
    print("=" * 80)
    print("UPDATING CSV FILE")
    print("=" * 80)
    print(f"Reading: {csv_path}")
    
    # Read CSV
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        # Replace 'price' with 'revenue' and add 'unit_price'
        new_fieldnames = []
        for field in fieldnames:
            if field == 'price':
                new_fieldnames.append('revenue')
            else:
                new_fieldnames.append(field)
        new_fieldnames.append('unit_price')
        
        for row in reader:
            # Rename price to revenue
            if 'price' in row:
                row['revenue'] = row.pop('price')
            
            # Calculate unit_price
            revenue = float(row['revenue']) if row.get('revenue') and row['revenue'].strip() else None
            quantity = float(row['quantity']) if row.get('quantity') and row['quantity'].strip() else None
            
            if revenue is not None and quantity is not None and quantity > 0:
                row['unit_price'] = revenue / quantity
            else:
                row['unit_price'] = ''
            
            rows.append(row)
    
    # Write updated CSV
    backup_path = csv_path.with_suffix('.csv.backup')
    print(f"Creating backup: {backup_path}")
    import shutil
    shutil.copy2(csv_path, backup_path)
    
    print(f"Writing updated CSV: {csv_path}")
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"✓ CSV updated: {len(rows):,} rows")
    return new_fieldnames


def update_bigquery_schema():
    """Update BigQuery table: rename price->revenue, add unit_price column."""
    print("\n" + "=" * 80)
    print("UPDATING BIGQUERY TABLE")
    print("=" * 80)
    
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    
    # Step 1: Add revenue column (copy from price)
    # Note: BigQuery doesn't support dropping columns easily, so we'll keep both
    # and update the agent to use 'revenue' going forward
    print("Step 1: Adding 'revenue' column and copying data from 'price'...")
    check_schema_query = f"""
    SELECT column_name 
    FROM `{PROJECT_ID}.{DATASET_ID}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE_ID}'
      AND column_name IN ('price', 'revenue')
    """
    schema_result = client.query(check_schema_query).result()
    existing_columns = [row.column_name for row in schema_result]
    
    if 'revenue' not in existing_columns:
        # Add revenue column
        add_revenue_query = f"""
        ALTER TABLE `{table_ref}`
        ADD COLUMN IF NOT EXISTS revenue FLOAT64
        """
        client.query(add_revenue_query).result()
        print("  ✓ Added 'revenue' column")
        
        # Copy data from price to revenue
        copy_data_query = f"""
        UPDATE `{table_ref}`
        SET revenue = price
        WHERE price IS NOT NULL
        """
        client.query(copy_data_query).result()
        print("  ✓ Copied data from 'price' to 'revenue'")
        print("  ⚠️  Note: 'price' column still exists for backward compatibility")
    else:
        print("  ✓ 'revenue' column already exists")
    
    # Step 2: Add unit_price column
    print("\nStep 2: Adding unit_price column...")
    add_unit_price_query = f"""
    ALTER TABLE `{table_ref}`
    ADD COLUMN IF NOT EXISTS unit_price FLOAT64
    """
    client.query(add_unit_price_query).result()
    print("  ✓ Added unit_price column")
    
    # Step 3: Calculate unit_price = revenue / quantity
    print("Step 3: Calculating unit_price values...")
    calculate_unit_price_query = f"""
    UPDATE `{table_ref}`
    SET unit_price = revenue / NULLIF(quantity, 0)
    WHERE revenue IS NOT NULL 
      AND quantity IS NOT NULL 
      AND quantity > 0
    """
    result = client.query(calculate_unit_price_query).result()
    print("  ✓ Calculated unit_price for rows with revenue and quantity")
    
    print("\n✓ BigQuery schema update complete")


def verify_changes():
    """Verify the changes were applied correctly."""
    print("\n" + "=" * 80)
    print("VERIFICATION")
    print("=" * 80)
    
    query = f"""
    SELECT 
      COUNT(*) as total_rows,
      COUNT(CASE WHEN revenue IS NOT NULL THEN 1 END) as rows_with_revenue,
      COUNT(CASE WHEN unit_price IS NOT NULL THEN 1 END) as rows_with_unit_price,
      SUM(revenue) as total_revenue,
      AVG(unit_price) as avg_unit_price
    FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
    """
    result = client.query(query).result()
    for row in result:
        print(f"Total rows: {row.total_rows:,}")
        print(f"Rows with revenue: {row.rows_with_revenue:,}")
        print(f"Rows with unit_price: {row.rows_with_unit_price:,}")
        print(f"Total revenue: ${row.total_revenue:,.2f}")
        print(f"Average unit price: ${row.avg_unit_price:,.2f}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rename price to revenue and add unit_price")
    parser.add_argument("--csv-only", action="store_true", help="Only update CSV file")
    parser.add_argument("--bq-only", action="store_true", help="Only update BigQuery")
    parser.add_argument("--apply", action="store_true", help="Actually apply changes (default is dry-run)")
    args = parser.parse_args()
    
    csv_path = Path(__file__).parent / "bourquin_05122025_snapshot_lineitems.csv"
    
    if not args.apply:
        print("=" * 80)
        print("DRY RUN MODE - No changes will be made")
        print("Run with --apply to actually update files")
        print("=" * 80)
        return
    
    if not args.bq_only:
        if not csv_path.exists():
            print(f"Error: CSV file not found: {csv_path}")
            sys.exit(1)
        update_csv_file(csv_path)
    
    if not args.csv_only:
        update_bigquery_schema()
        verify_changes()
    
    print("\n" + "=" * 80)
    print("✓ UPDATE COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()

