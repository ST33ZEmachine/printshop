-- BigQuery SQL script to create webhook pipeline tables
-- Run this in BigQuery Console: https://console.cloud.google.com/bigquery

-- 1. Create trello_webhook_events table
CREATE TABLE IF NOT EXISTS `maxprint-479504.trello_rag.trello_webhook_events` (
  event_id STRING NOT NULL,
  action_type STRING,
  action_date TIMESTAMP,
  card_id STRING NOT NULL,
  board_id STRING,
  board_name STRING,
  list_id STRING,
  list_name STRING,
  list_before_id STRING,
  list_before_name STRING,
  list_after_id STRING,
  list_after_name STRING,
  is_list_transition BOOL,
  member_creator_id STRING,
  member_creator_username STRING,
  raw_payload JSON,
  processed BOOL,
  processed_at TIMESTAMP,
  extraction_triggered BOOL,
  error_message STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY card_id, action_type, is_list_transition
OPTIONS(
  description="Immutable log of all Trello webhook events. Tracks card changes, list transitions, and processing status."
);

-- 2. Create bourquin_cards_current table
CREATE TABLE IF NOT EXISTS `maxprint-479504.trello_rag.bourquin_cards_current` (
  card_id STRING NOT NULL,
  name STRING,
  `desc` STRING,
  labels STRING,
  closed BOOL,
  dateLastActivity TIMESTAMP,
  purchaser STRING,
  order_summary STRING,
  primary_buyer_name STRING,
  primary_buyer_email STRING,
  date_created DATE,
  datetime_created TIMESTAMP,
  year_created INT64,
  month_created INT64,
  year_month STRING,
  unix_timestamp INT64,
  line_item_count INT64,
  -- List/board tracking fields
  list_id STRING,
  list_name STRING,
  board_id STRING,
  board_name STRING,
  -- Metadata fields
  last_updated_at TIMESTAMP,
  last_extracted_at TIMESTAMP,
  last_extraction_event_id STRING,
  last_event_type STRING
)
OPTIONS(
  description="Current state of all Trello cards. Updated on any card change. Mirrors bourquin_05122025_snapshot schema with additional metadata fields."
);

-- 3. Create bourquin_lineitems_current table
CREATE TABLE IF NOT EXISTS `maxprint-479504.trello_rag.bourquin_lineitems_current` (
  card_id STRING NOT NULL,
  line_index INT64 NOT NULL,
  quantity INT64,
  raw_price FLOAT64,
  price_type STRING,
  unit_price FLOAT64,
  total_revenue FLOAT64,
  description STRING,
  business_line STRING,
  material STRING,
  dimensions STRING
)
OPTIONS(
  description="Current state of all line items. Updated only when card description changes. Mirrors bourquin_05122025_snapshot_lineitems schema."
);

-- 4. Create pending_bigquery_updates table (retry queue for streaming buffer failures)
CREATE TABLE IF NOT EXISTS `maxprint-479504.trello_rag.pending_bigquery_updates` (
  update_id STRING NOT NULL,
  operation_type STRING NOT NULL,  -- 'upsert_card', 'upsert_line_items', 'mark_event_processed'
  target_table STRING NOT NULL,     -- 'bourquin_cards_current', 'bourquin_lineitems_current', 'trello_webhook_events'
  payload JSON NOT NULL,             -- Operation-specific data (card data, line items, event_id, etc.)
  retry_count INT64 NOT NULL DEFAULT 0,
  first_queued_at TIMESTAMP NOT NULL,
  last_retry_at TIMESTAMP,
  next_retry_at TIMESTAMP NOT NULL, -- Calculated: first_queued_at + (retry_count * delay)
  status STRING NOT NULL,            -- 'pending', 'processing', 'completed', 'failed'
  error_message STRING,
  completed_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY status, next_retry_at, operation_type
OPTIONS(
  description="Queue for BigQuery operations that failed due to streaming buffer. Processed by background job with exponential backoff."
);
