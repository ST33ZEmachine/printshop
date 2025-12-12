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
  last_extraction_event_id STRING
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
