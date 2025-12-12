# Trello Webhook Pipeline - Implementation Plan

> Status: Archived. Final architecture and setup are documented in `WEBHOOK_ARCHITECTURE_FINAL.md` and `WEBHOOK_SETUP_GUIDE.md`. This plan is kept for reference.

## Overview

This document outlines the step-by-step implementation plan for the Trello webhook pipeline that captures real-time card updates and maintains current state in BigQuery.

## Existing Tables (Master - Immutable)

- `trello_rag.bourquin_05122025_snapshot` - Cards master table
- `trello_rag.bourquin_05122025_snapshot_lineitems` - Line items master table

These tables will remain immutable and serve as the original extraction records.

## New Tables to Create

1. `trello_rag.trello_webhook_events` - Event log (immutable)
2. `trello_rag.bourquin_cards_current` - Current cards state (updated)
3. `trello_rag.bourquin_lineitems_current` - Current line items state (updated)

---

## Phase 1: Table Setup (Foundation)

### Step 1.1: Create Events Table
- [x] Create `trello_rag.trello_webhook_events` table
- [x] Define schema (event_id, action_type, card_id, list transitions, etc.)
- [x] Set up partitioning (by created_at) and clustering
- [ ] Test: Insert a test event manually

### Step 1.2: Create Current Tables
- [x] Create `trello_rag.bourquin_cards_current` (mirror of snapshot schema + metadata fields)
- [x] Create `trello_rag.bourquin_lineitems_current` (mirror of snapshot_lineitems schema)
- [ ] Test: Verify schemas match master tables

### Step 1.3: Schema Alignment Check
- [ ] Compare existing snapshot table schemas with our extraction output
- [ ] Identify any missing fields or differences
- [ ] Document schema mappings

---

## Phase 2: Core Infrastructure

### Step 2.1: BigQuery Client Module
- [ ] Create `backend/integrations/trello/bigquery_client.py`
- [ ] Functions: insert_event, check_idempotency, get_last_description
- [ ] Functions: insert_card_master, insert_card_current, upsert_card_current
- [ ] Functions: insert_line_items_master, insert_line_items_current, delete_line_items_current
- [ ] Test: Unit tests for each function

### Step 2.2: Single-Card Extraction Service
- [ ] Create `extractionPipeline/extract_single_card.py`
- [ ] Refactor shared extraction logic from `extract_trello_data.py`
- [ ] Create `CardExtractionService` class
- [ ] Test: Extract a single test card

### Step 2.3: Description Change Detection
- [ ] Function to compare old vs new description
- [ ] Query last description from events table or current table
- [ ] Return boolean: description_changed
- [ ] Test: Test with various scenarios

---

## Phase 3: Webhook Processing Pipeline

### Step 3.1: BigQuery Event Publisher
- [ ] Create `BigQueryTrelloEventPublisher` class
- [ ] Implement: store_raw_event, check_idempotency, process_event (async)
- [ ] Wire up to router in `main.py`
- [ ] Test: Send test webhook, verify event stored

### Step 3.2: Event Processing Logic
- [ ] Implement `_process_event` method:
  - Fetch full card from Trello API
  - Determine action type (createCard vs updateCard)
  - Check if description changed
  - Route to appropriate handler
- [ ] Test: Process test events

### Step 3.3: Card Creation Handler
- [ ] Handle `createCard` webhook:
  - Check if card exists in master (skip if exists)
  - Extract with LLM
  - Insert into master tables
  - Insert into current tables
  - Mark event processed
- [ ] Test: Create test card in Trello, verify processing

### Step 3.4: Card Update Handler
- [ ] Handle `updateCard` webhook:
  - Check if description changed
  - If YES: Re-extract → Update current tables
  - If NO: Update metadata only in current table
  - Mark event processed
- [ ] Test: Update test card (description change, metadata change)

---

## Phase 4: Integration & Testing

### Step 4.1: Wire Everything Together
- [ ] Connect publisher → extraction → BigQuery updates
- [ ] Add error handling and logging
- [ ] Test: End-to-end with real webhook

### Step 4.2: Register Webhook
- [ ] Use `trello_webhook_cli.py` to register webhook for Bourquin board
- [ ] Verify webhook is active
- [ ] Test: Make a change in Trello, verify webhook received

### Step 4.3: Error Handling & Monitoring
- [ ] Add retry logic for transient failures
- [ ] Store errors in events table
- [ ] Add logging for debugging
- [ ] Test: Simulate failures, verify error handling

### Step 4.4: Agent Integration
- [ ] Update agent instructions to use `_current` tables
- [ ] Test: Query current data via agent

---

## Implementation Order

1. **Phase 1**: Table creation scripts (foundation)
2. **Phase 2.1**: BigQuery client utilities (core database operations)
3. **Phase 2.2**: Single-card extraction (reuse existing logic)
4. **Phase 3**: Publisher and processing (webhook → database flow)
5. **Phase 4**: Integration and testing (end-to-end validation)

---

## Decisions Made

1. **Table naming**: Use `bourquin_cards_current` and `bourquin_lineitems_current` to match existing naming convention
2. **Initial data**: Start fresh - let webhooks populate current tables (can backfill later if needed)
3. **Webhook registration**: Wait until pipeline is ready
4. **Error recovery**: Rely on Trello retries + manual reprocessing tool (future enhancement)

---

## Status

- [ ] Phase 1: Table Setup
- [ ] Phase 2: Core Infrastructure
- [ ] Phase 3: Webhook Processing Pipeline
- [ ] Phase 4: Integration & Testing
