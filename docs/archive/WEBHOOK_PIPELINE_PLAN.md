# Trello Webhook Pipeline Architecture Plan

> Status: Archived. Superseded by `WEBHOOK_ARCHITECTURE_FINAL.md` and `WEBHOOK_SETUP_GUIDE.md`. Kept for historical context.

## Overview

This document outlines the architecture and implementation plan for processing Trello webhooks in real-time, extracting data, and updating BigQuery tables.

## Current State

### Existing Infrastructure
- ✅ **Webhook Endpoint**: `/trello/webhook` receives webhook payloads
- ✅ **Publisher Pattern**: `TrelloEventPublisher` interface exists (currently `LoggingTrelloEventPublisher`)
- ✅ **Extraction Pipeline**: `extract_trello_data.py` processes batch JSON files using Gemini API
- ✅ **BigQuery Tables**: 
  - `trello_rag.bourquin_05122025_snapshot` (cards/master table)
  - `trello_rag.bourquin_05122025_snapshot_lineitems` (line items)
- ✅ **Trello API Service**: `TrelloService` can fetch card data

### What's Missing
- ❌ BigQuery table for raw webhook events
- ❌ Publisher implementation that processes events
- ❌ Single-card extraction logic (current pipeline is batch-only)
- ❌ Upsert/merge logic for master tables
- ❌ Async processing pipeline

---

## Architecture Design

### 1. BigQuery Table: `trello_webhook_events`

**Purpose**: Store raw webhook events for audit trail, debugging, reprocessing, and **list transition tracking** (key use case: track how long cards are in certain lists).

**Schema**:
```python
[
    bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),  # action.id (idempotency key)
    bigquery.SchemaField("action_type", "STRING"),  # "createCard", "updateCard", etc.
    bigquery.SchemaField("action_date", "TIMESTAMP"),  # When the action occurred in Trello
    bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),  # For joining to cards table
    bigquery.SchemaField("board_id", "STRING"),
    bigquery.SchemaField("board_name", "STRING"),
    # List transition tracking (CRITICAL for use case)
    bigquery.SchemaField("list_id", "STRING"),  # Current list after action
    bigquery.SchemaField("list_name", "STRING"),  # Current list name after action
    bigquery.SchemaField("list_before_id", "STRING"),  # Previous list (if moved)
    bigquery.SchemaField("list_before_name", "STRING"),  # Previous list name
    bigquery.SchemaField("list_after_id", "STRING"),  # New list (if moved)
    bigquery.SchemaField("list_after_name", "STRING"),  # New list name
    bigquery.SchemaField("is_list_transition", "BOOLEAN"),  # True if card moved between lists
    # Metadata
    bigquery.SchemaField("member_creator_id", "STRING"),
    bigquery.SchemaField("member_creator_username", "STRING"),
    bigquery.SchemaField("raw_payload", "JSON"),  # Full webhook payload for debugging
    # Processing status
    bigquery.SchemaField("processed", "BOOLEAN"),  # Whether extraction has run
    bigquery.SchemaField("processed_at", "TIMESTAMP"),
    bigquery.SchemaField("error_message", "STRING"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),  # When we received the webhook
]
```

**Table Name**: `trello_rag.trello_webhook_events`

**Partitioning**: By `created_at` (daily partitions)

**Clustering**: By `card_id`, `action_type`, `is_list_transition`

**Key Use Case Support**: This table enables tracking:
- When cards enter/exit each list
- Duration cards spend in each list
- List transition sequences
- Active jobs (cards not in "Completed" list)
- Job throughput rates

---

### 2. Event Processing Flow

```
Trello Webhook → FastAPI Router → Publisher → Event Queue/Storage
                                                      ↓
                                            Process Event (async)
                                                      ↓
                                    ┌─────────────────┴─────────────────┐
                                    ↓                                     ↓
                            Store Raw Event                    Fetch Full Card Data
                            (BigQuery)                         (Trello API)
                                    ↓                                     ↓
                                    └─────────────────┬─────────────────┘
                                                      ↓
                                            Extract Data (Gemini)
                                                      ↓
                                    ┌─────────────────┴─────────────────┐
                                    ↓                                     ↓
                            Upsert Card Record                  Upsert Line Items
                            (Master Table)                      (Line Items Table)
```

---

### 3. Action Types to Process

**Priority Actions** (process immediately):
- `createCard` - New card created
- `updateCard` - Card updated (name, description, list moved)
- `addAttachmentToCard` - New attachment (might contain order details)
- `commentCard` - New comment (might contain updates)

**Lower Priority** (log only, optional processing):
- `deleteCard` - Card archived/deleted
- `addMemberToCard` - Member added
- `removeMemberFromCard` - Member removed
- `updateCard:idList` - Card moved between lists (already in updateCard)

**Filtering**: Only process actions where `action.data.card.id` exists.

---

### 4. Publisher Implementation: `BigQueryTrelloEventPublisher`

**Responsibilities**:
1. Store raw webhook event in `trello_webhook_events` table
2. Trigger async processing pipeline
3. Handle idempotency (check if `event_id` already exists)

**Implementation**:
```python
class BigQueryTrelloEventPublisher:
    def __init__(
        self,
        project_id: str,
        dataset_id: str,
        trello_service: TrelloService,
        extraction_service: CardExtractionService,
    ):
        self.bq_client = bigquery.Client(project=project_id)
        self.dataset_id = dataset_id
        self.trello_service = trello_service
        self.extraction_service = extraction_service
    
    async def publish(self, action: TrelloAction) -> None:
        # 1. Check idempotency
        if await self._event_exists(action.id):
            logger.info(f"Event {action.id} already processed, skipping")
            return
        
        # 2. Store raw event
        await self._store_raw_event(action)
        
        # 3. Trigger async processing (don't await - fire and forget)
        asyncio.create_task(self._process_event(action))
    
    async def _process_event(self, action: TrelloAction) -> None:
        """Process event: fetch card, extract, upsert."""
        try:
            # Only process card-related actions
            if not action.data.card or not action.data.card.id:
                return
            
            card_id = action.data.card.id
            
            # Fetch full card data from Trello API
            card_data = await self._fetch_card_data(card_id)
            
            # Extract data using Gemini
            extracted = await self.extraction_service.extract_single_card(card_data)
            
            # Upsert to master tables
            await self._upsert_card(extracted)
            await self._upsert_line_items(extracted)
            
            # Mark event as processed
            await self._mark_event_processed(action.id)
            
        except Exception as e:
            logger.error(f"Error processing event {action.id}: {e}")
            await self._mark_event_error(action.id, str(e))
```

---

### 5. Single-Card Extraction Service

**New Module**: `extractionPipeline/extract_single_card.py`

**Purpose**: Extract data from a single card (reuse logic from batch extraction).

**Key Functions**:
```python
class CardExtractionService:
    def __init__(self, gemini_client: genai.Client, model_id: str):
        self.client = gemini_client
        self.model_id = model_id
    
    async def extract_single_card(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract data from a single card.
        Returns enriched card dict with line_items, buyer info, etc.
        """
        # Reuse extract_batch logic but for single card
        # Wrap in list, process, return first result
        batch_result = extract_batch(self.client, [card], logger)
        return batch_result[0] if batch_result else card
```

**Integration**: Refactor `extract_trello_data.py` to extract shared functions into a common module.

---

### 6. BigQuery Upsert Strategy

**What is Upsert?**: "Upsert" = **UP**date if exists, in**SERT** if not. It's a way to handle both new records and updates in a single operation.

**Example**: 
- Card `abc123` doesn't exist → INSERT it
- Card `abc123` already exists → UPDATE it with new data
- Upsert handles both cases automatically

**Challenge**: BigQuery doesn't support native UPSERT. Options:

#### Option A: MERGE Statement (Recommended)
```sql
MERGE `trello_rag.cards` AS target
USING (SELECT ...) AS source
ON target.card_id = source.card_id
WHEN MATCHED THEN UPDATE SET 
    name = source.name,
    desc = source.desc,
    list_id = source.list_id,
    list_name = source.list_name,
    ...
WHEN NOT MATCHED THEN INSERT (card_id, name, desc, ...)
    VALUES (source.card_id, source.name, source.desc, ...)
```

**How it works**:
- If `card_id` exists → UPDATE the row
- If `card_id` doesn't exist → INSERT a new row
- All in one atomic operation

**Pros**: Atomic, handles updates correctly, no race conditions
**Cons**: Requires SQL generation, slightly more complex

#### Option B: Delete + Insert (Simpler, but not recommended)
```python
# Delete existing card
DELETE FROM table WHERE card_id = ?
# Insert new card
INSERT INTO table VALUES (...)
```

**Pros**: Simple to understand
**Cons**: Not atomic (race conditions possible), slower, loses data briefly

**Recommendation**: **Option A (MERGE)** for production. It's the standard way to do upserts in BigQuery.

---

### 7. Master Cards Table Schema (IMMUTABLE)

**Table Name**: `trello_rag.cards` (single master table, **INSERT only, never UPDATE**)

**Design Principle**: Store static/immutable data from first extraction. All state changes tracked in events table.

**Schema**:
```python
[
    # Core Trello fields (from first extraction)
    bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),  # Primary key
    bigquery.SchemaField("name", "STRING"),  # Initial name (may change in Trello, but we preserve first)
    bigquery.SchemaField("desc", "STRING"),  # Initial description (may change, but we preserve first)
    bigquery.SchemaField("labels", "STRING"),  # Comma-separated (from first extraction)
    bigquery.SchemaField("closed", "BOOLEAN"),  # Initial closed status
    
    # Board info (static)
    bigquery.SchemaField("board_id", "STRING"),
    bigquery.SchemaField("board_name", "STRING"),
    
    # Enriched fields - title parsing (extracted once, typically doesn't change)
    bigquery.SchemaField("purchaser", "STRING"),
    bigquery.SchemaField("order_summary", "STRING"),
    
    # Enriched fields - buyer extraction (extracted once)
    bigquery.SchemaField("primary_buyer_name", "STRING"),
    bigquery.SchemaField("primary_buyer_email", "STRING"),
    
    # Date fields (immutable - card creation date)
    bigquery.SchemaField("date_created", "DATE"),
    bigquery.SchemaField("datetime_created", "TIMESTAMP"),
    bigquery.SchemaField("year_created", "INTEGER"),
    bigquery.SchemaField("month_created", "INTEGER"),
    bigquery.SchemaField("year_month", "STRING"),
    bigquery.SchemaField("unix_timestamp", "INTEGER"),
    
    # Summary (from first extraction)
    bigquery.SchemaField("line_item_count", "INTEGER"),
    
    # Metadata
    bigquery.SchemaField("first_extracted_at", "TIMESTAMP"),  # When we first extracted this card
    bigquery.SchemaField("first_extraction_event_id", "STRING"),  # Event that triggered first extraction
]
```

**What's NOT in Master Table**:
- ❌ Current list (tracked in events table)
- ❌ Last updated timestamp (tracked in events table)
- ❌ Current card name/description (if changed, tracked in events)

**Benefits of Immutable Design**:
- ✅ **No data loss risk** - original extraction preserved even if later extractions fail
- ✅ **Full audit trail** - can see exactly when card was first seen
- ✅ **Simpler logic** - no UPDATE operations, just INSERT
- ✅ **Idempotent** - can safely re-run extraction without worrying about overwrites

**Tradeoff**:
- ⚠️ Current state queries require joining events table (slightly slower)
- ✅ **Solution**: Use materialized view for fast current-state queries

### 8. Insert-Only Implementation (No Upsert Needed!)

**New Module**: `extractionPipeline/bigquery_insert.py`

**Key Change**: Master table is **INSERT only**. Check if card exists, insert if not.

```python
async def insert_card_if_new(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    card: Dict[str, Any],
    event_id: Optional[str] = None,
) -> bool:
    """
    Insert card to master table ONLY if it doesn't exist.
    
    Returns True if inserted, False if already exists.
    
    This is safer than upsert - we never overwrite existing data.
    """
    card_id = card.get("id")
    if not card_id:
        raise ValueError("Card must have an id")
    
    # Check if card already exists
    check_sql = f"""
    SELECT card_id 
    FROM `{project_id}.{dataset_id}.{table_id}`
    WHERE card_id = @card_id
    LIMIT 1
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("card_id", "STRING", card_id),
        ]
    )
    
    result = client.query(check_sql, job_config=job_config).result()
    if list(result):
        # Card already exists, skip insert
        logger.info(f"Card {card_id} already exists in master table, skipping insert")
        return False
    
    # Card doesn't exist, insert it
    card_row = flatten_card(card)
    card_row["first_extracted_at"] = datetime.utcnow().isoformat()
    if event_id:
        card_row["first_extraction_event_id"] = event_id
    
    # Simple INSERT (no MERGE needed!)
    errors = client.insert_rows_json(
        f"{project_id}.{dataset_id}.{table_id}",
        [card_row]
    )
    
    if errors:
        raise Exception(f"Failed to insert card: {errors}")
    
    logger.info(f"Inserted new card {card_id} to master table")
    return True
```

**Benefits**:
- ✅ **Simpler** - no complex MERGE SQL
- ✅ **Safer** - never overwrites existing data
- ✅ **Idempotent** - can safely re-run without side effects
- ✅ **Preserves history** - original extraction always preserved

async def upsert_line_items(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    card_id: str,
    line_items: List[Dict[str, Any]],
) -> None:
    """Upsert line items for a card."""
    # Delete existing line items for this card
    delete_sql = f"""
    DELETE FROM `{project_id}.{dataset_id}.{table_id}`
    WHERE card_id = @card_id
    """
    
    # Insert new line items
    insert_rows = [flatten_line_item(card_id, item) for item in line_items]
    client.insert_rows_json(f"{project_id}.{dataset_id}.{table_id}", insert_rows)
```

---

### 8. Trello API Integration

**Enhancement to `TrelloService`**:

```python
async def fetch_card(self, card_id: str) -> Dict[str, Any]:
    """Fetch full card data including description, attachments, comments."""
    # Use Trello API to get complete card data
    # GET /1/cards/{card_id}?fields=all&attachments=true&actions=commentCard
    response = await self.client.get(
        f"/cards/{card_id}",
        params={
            **self._auth_params(),
            "fields": "all",
            "attachments": "true",
            "actions": "commentCard",
        }
    )
    response.raise_for_status()
    return response.json()
```

**Note**: Webhook payloads only contain partial card data. We need to fetch full card data for extraction.

---

## Implementation Steps

### Phase 1: Foundation (Week 1)

1. **Create BigQuery webhook events table**
   - [ ] Create schema definition
   - [ ] Create table via script or Terraform
   - [ ] Set up partitioning and clustering

2. **Implement BigQueryTrelloEventPublisher**
   - [ ] Create publisher class
   - [ ] Implement raw event storage
   - [ ] Implement idempotency check
   - [ ] Wire up to router in `main.py`

3. **Create single-card extraction service**
   - [ ] Refactor `extract_trello_data.py` to extract shared functions
   - [ ] Create `CardExtractionService` class
   - [ ] Test with sample card

### Phase 2: Processing Pipeline (Week 2)

4. **Implement async event processing**
   - [ ] Implement `_process_event` method
   - [ ] Add Trello API card fetching
   - [ ] Integrate extraction service
   - [ ] Add error handling and retry logic

5. **Implement BigQuery upsert functions**
   - [ ] Create `bigquery_upsert.py` module
   - [ ] Implement `upsert_card` with MERGE
   - [ ] Implement `upsert_line_items` (delete + insert)
   - [ ] Add tests

6. **Wire everything together**
   - [ ] Connect publisher → extraction → upsert
   - [ ] Add logging and monitoring
   - [ ] Test end-to-end with real webhook

### Phase 3: Testing & Optimization (Week 3)

7. **Testing**
   - [ ] Unit tests for each component
   - [ ] Integration tests with mock Trello API
   - [ ] End-to-end test with test webhook
   - [ ] Load testing (handle burst of webhooks)

8. **Monitoring & Observability**
   - [ ] Add metrics (events processed, errors, latency)
   - [ ] Set up alerts for failures
   - [ ] Create dashboard for webhook pipeline health

9. **Optimization**
   - [ ] Batch processing for high-volume periods
   - [ ] Caching for frequently accessed cards
   - [ ] Rate limiting for Trello API calls

---

## File Structure

```
backend/
├── integrations/
│   └── trello/
│       ├── publisher.py (update: add BigQueryTrelloEventPublisher)
│       ├── service.py (update: add fetch_card method)
│       └── bigquery_client.py (new: BigQuery utilities)
│
extractionPipeline/
├── extract_trello_data.py (refactor: extract shared functions)
├── extract_single_card.py (new: single-card extraction)
├── bigquery_upsert.py (new: upsert functions)
└── shared/
    ├── __init__.py
    ├── extraction.py (new: shared extraction logic)
    └── schemas.py (new: shared schema definitions)
```

---

## Configuration

**Environment Variables**:
```bash
# Existing
BIGQUERY_PROJECT=your-project
GOOGLE_CLOUD_PROJECT=your-project
GEMINI_MODEL=gemini-2.5-flash-lite

# New
TRELLO_WEBHOOK_DATASET=trello_rag
TRELLO_WEBHOOK_EVENTS_TABLE=trello_webhook_events
TRELLO_CARDS_TABLE=bourquin_05122025_snapshot
TRELLO_LINEITEMS_TABLE=bourquin_05122025_snapshot_lineitems
```

---

## Error Handling & Resilience

### Idempotency
- Use `action.id` as idempotency key
- Check `trello_webhook_events` table before processing
- Skip if `processed = true`

### Retry Logic
- Retry transient failures (API timeouts, network errors)
- Exponential backoff for Trello API rate limits
- Dead letter queue for persistent failures

### Error Tracking
- Store errors in `trello_webhook_events.error_message`
- Set `processed = false` on error
- Alert on error rate threshold

---

## Performance Considerations

### Async Processing
- Use `asyncio.create_task()` for fire-and-forget processing
- Don't block webhook response
- Process events in background

### Batching
- For high-volume periods, batch multiple events
- Process cards in batches of 10-25 (reuse batch extraction)
- Batch BigQuery writes

### Rate Limiting
- Trello API: 300 requests per 10 seconds per token
- Implement rate limiter for `fetch_card` calls
- Queue events if rate limit hit

---

## Monitoring Queries

### Check Processing Status
```sql
SELECT 
    action_type,
    COUNT(*) as total,
    SUM(CASE WHEN processed THEN 1 ELSE 0 END) as processed,
    SUM(CASE WHEN error_message IS NOT NULL THEN 1 ELSE 0 END) as errors
FROM `trello_rag.trello_webhook_events`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY action_type
```

### Find Failed Events
```sql
SELECT 
    event_id,
    action_type,
    card_id,
    error_message,
    created_at
FROM `trello_rag.trello_webhook_events`
WHERE processed = false
    OR error_message IS NOT NULL
ORDER BY created_at DESC
LIMIT 100
```

### Processing Latency
```sql
SELECT 
    AVG(TIMESTAMP_DIFF(processed_at, created_at, SECOND)) as avg_latency_seconds,
    MAX(TIMESTAMP_DIFF(processed_at, created_at, SECOND)) as max_latency_seconds
FROM `trello_rag.trello_webhook_events`
WHERE processed = true
    AND processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
```

---

## List Transition Tracking Queries (Key Use Case)

### Active Jobs (Cards Not Completed)
```sql
WITH current_lists AS (
    SELECT 
        card_id,
        list_after_name as current_list,
        list_after_id as current_list_id,
        action_date as last_moved_at,
        ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY action_date DESC) as rn
    FROM `trello_rag.trello_webhook_events`
    WHERE is_list_transition = true
)
SELECT 
    c.card_id,
    c.name,
    c.purchaser,
    cl.current_list,
    cl.current_list_id,
    cl.last_moved_at,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), cl.last_moved_at, HOUR) as hours_in_current_list
FROM `trello_rag.cards` c
JOIN current_lists cl ON c.card_id = cl.card_id
WHERE cl.rn = 1  -- Most recent transition
    AND c.closed = false
    AND cl.current_list != 'Completed'
ORDER BY hours_in_current_list DESC
```

### List Duration Analysis (How Long Cards Stay in Each List)
```sql
WITH list_transitions AS (
    SELECT 
        card_id,
        list_before_name,
        list_after_name,
        action_date as entered_list_at,
        LEAD(action_date) OVER (
            PARTITION BY card_id 
            ORDER BY action_date
        ) as exited_list_at,
        TIMESTAMP_DIFF(
            LEAD(action_date) OVER (
                PARTITION BY card_id 
                ORDER BY action_date
            ),
            action_date,
            HOUR
        ) as hours_in_list
    FROM `trello_rag.trello_webhook_events`
    WHERE is_list_transition = true
        AND list_after_name IS NOT NULL
)
SELECT 
    list_after_name as list_name,
    COUNT(*) as total_transitions,
    AVG(hours_in_list) as avg_hours,
    PERCENTILE_CONT(hours_in_list, 0.5) OVER (PARTITION BY list_after_name) as median_hours,
    MIN(hours_in_list) as min_hours,
    MAX(hours_in_list) as max_hours
FROM list_transitions
WHERE hours_in_list IS NOT NULL
GROUP BY list_after_name
ORDER BY avg_hours DESC
```

### Job Throughput Rate (Cards Completed Per Day/Week)
```sql
SELECT 
    DATE(action_date) as completion_date,
    COUNT(DISTINCT card_id) as cards_completed,
    COUNT(DISTINCT CASE WHEN list_after_name = 'Completed' THEN card_id END) as completed_count
FROM `trello_rag.trello_webhook_events`
WHERE is_list_transition = true
    AND list_after_name = 'Completed'
    AND action_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY DATE(action_date)
ORDER BY completion_date DESC
```

### Cards Currently Stuck (Long Time in Same List)
```sql
WITH current_list_state AS (
    SELECT 
        card_id,
        list_name,
        MAX(action_date) as last_moved_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(action_date), HOUR) as hours_since_move
    FROM `trello_rag.trello_webhook_events`
    WHERE is_list_transition = true
        AND list_after_name IS NOT NULL
    GROUP BY card_id, list_name
)
SELECT 
    c.card_id,
    c.name,
    c.purchaser,
    cls.list_name,
    cls.hours_since_move,
    cls.last_moved_at
FROM current_list_state cls
JOIN `trello_rag.cards` c ON cls.card_id = c.card_id
WHERE cls.hours_since_move > 48  -- More than 2 days
    AND cls.list_name != 'Completed'
ORDER BY cls.hours_since_move DESC
```

### List Transition Sequence (Most Common Paths)
```sql
WITH transitions AS (
    SELECT 
        card_id,
        list_before_name,
        list_after_name,
        action_date,
        LAG(list_after_name) OVER (
            PARTITION BY card_id 
            ORDER BY action_date
        ) as previous_list
    FROM `trello_rag.trello_webhook_events`
    WHERE is_list_transition = true
)
SELECT 
    previous_list,
    list_after_name as next_list,
    COUNT(*) as transition_count,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY previous_list) as percentage
FROM transitions
WHERE previous_list IS NOT NULL
GROUP BY previous_list, list_after_name
ORDER BY transition_count DESC
LIMIT 20
```

---

## Testing Strategy

### Unit Tests
- Test extraction service with mock Gemini responses
- Test upsert SQL generation
- Test idempotency checks

### Integration Tests
- Mock Trello API responses
- Test full pipeline with sample webhook payload
- Test error scenarios

### End-to-End Tests
- Register test webhook in Trello
- Create/update test card
- Verify data appears in BigQuery
- Verify idempotency (replay same webhook)

---

## Future Enhancements

1. **Real-time Dashboard**: Show webhook events in real-time
2. **Reprocessing Tool**: Re-run extraction on failed events
3. **Backfill Pipeline**: Process historical cards via webhook events
4. **Multi-board Support**: Handle webhooks from multiple Trello boards
5. **Change Detection**: Only process if card data actually changed
6. **Streaming Analytics**: Real-time revenue/order metrics

---

## Table Structure Summary

### Revised Architecture: Immutable Master + Events

**Key Insight**: Keep master table **immutable** (INSERT only, never UPDATE) to avoid data loss risks. Track all state changes in events table.

### Three Core Tables

1. **`trello_rag.cards`** (Master/Core Table - **IMMUTABLE**)
   - **INSERT only** - never updated after initial creation
   - Contains: Static card data from first extraction
   - Fields: `card_id`, `name` (initial), `desc` (initial), `purchaser`, `order_summary`, `primary_buyer_name`, `primary_buyer_email`, `date_created`, `datetime_created`, extracted fields
   - **Primary Key**: `card_id`
   - **Use Case**: Fast lookups of card metadata, purchaser info, creation date
   - **Safety**: If extraction fails later, original data is preserved

2. **`trello_rag.line_items`** (Line Items Table)
   - References cards via `card_id` (foreign key)
   - Contains: extracted line items with pricing, materials, dimensions
   - **Primary Key**: `card_id` + `line_index`
   - **Relationship**: Many line items → One card
   - **Update Strategy**: Delete all line items for card, re-insert (on description changes)
   - **Use Case**: Revenue analysis, product breakdowns

3. **`trello_rag.trello_webhook_events`** (Events Table - **IMMUTABLE**)
   - **INSERT only** - never updated
   - Tracks ALL state changes: list transitions, card updates, etc.
   - Contains: `list_before_name`, `list_after_name`, `is_list_transition`, `action_date`, etc.
   - **Primary Key**: `event_id` (action.id)
   - **Relationship**: Many events → One card
   - **Use Case**: Track list transitions, calculate time in lists, job throughput, **current state**

### Getting Current State

Since master table is immutable, current state comes from events table:

```sql
-- Get current list for a card
SELECT 
    list_after_name as current_list,
    action_date as last_moved_at
FROM `trello_rag.trello_webhook_events`
WHERE card_id = 'abc123'
    AND is_list_transition = true
ORDER BY action_date DESC
LIMIT 1

-- Get all active jobs (current list != Completed)
WITH current_lists AS (
    SELECT 
        card_id,
        list_after_name as current_list,
        action_date as last_moved_at,
        ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY action_date DESC) as rn
    FROM `trello_rag.trello_webhook_events`
    WHERE is_list_transition = true
)
SELECT 
    c.card_id,
    c.name,
    c.purchaser,
    cl.current_list,
    cl.last_moved_at
FROM `trello_rag.cards` c
JOIN current_lists cl ON c.card_id = cl.card_id
WHERE cl.rn = 1
    AND cl.current_list != 'Completed'
    AND c.closed = false
```

### Optional: Materialized View for Performance

For faster queries, create a materialized view that refreshes periodically:

```sql
CREATE MATERIALIZED VIEW `trello_rag.cards_current_state` AS
SELECT 
    c.*,
    latest_event.list_after_name as current_list_name,
    latest_event.list_after_id as current_list_id,
    latest_event.action_date as last_moved_at
FROM `trello_rag.cards` c
LEFT JOIN (
    SELECT 
        card_id,
        list_after_name,
        list_after_id,
        action_date,
        ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY action_date DESC) as rn
    FROM `trello_rag.trello_webhook_events`
    WHERE is_list_transition = true
) latest_event ON c.card_id = latest_event.card_id AND latest_event.rn = 1
```

**Refresh**: Schedule to refresh every 5-15 minutes via BigQuery scheduled queries.

### Data Flow (Revised)
```
Webhook Event → Events Table (always inserted, never updated)
                ↓
            Fetch Full Card → Extract Data → Insert Card (if new) → Insert/Update Line Items
                                                      ↓
                                            (Only if card_id doesn't exist)
                                            (Preserves original extraction)
```

### How Tables Work Together for Your Use Case

**Goal**: Track how long cards are in certain lists, active jobs, throughput

**Example Scenario**: Card moves from "Printing" → "Installation" → "Completed"

1. **First webhook (createCard)** → Stored in `trello_webhook_events`:
   - `action_type = "createCard"`
   - `list_after_name = "Sales Working"`
   - `is_list_transition = true`
   - `action_date = "2025-01-10 09:00:00"`

2. **Card extracted** → Inserted in `trello_rag.cards` (if new):
   - `card_id = "abc123"`
   - `purchaser = "Acme Corp"`
   - `date_created = "2025-01-10"`
   - `first_extracted_at = "2025-01-10 09:05:00"`
   - **Note**: No `list_name` field - that's in events table!

3. **Second webhook (list transition)** → Stored in `trello_webhook_events`:
   - `list_before_name = "Sales Working"`
   - `list_after_name = "Printing"`
   - `action_date = "2025-01-12 14:30:00"`

4. **Query for active jobs** (using events table):
   ```sql
   WITH current_lists AS (
       SELECT 
           card_id,
           list_after_name as current_list,
           action_date as last_moved_at,
           ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY action_date DESC) as rn
       FROM trello_rag.trello_webhook_events
       WHERE is_list_transition = true
   )
   SELECT 
       c.card_id,
       c.name,
       c.purchaser,
       cl.current_list,
       cl.last_moved_at
   FROM trello_rag.cards c
   JOIN current_lists cl ON c.card_id = cl.card_id
   WHERE cl.rn = 1
       AND cl.current_list != 'Completed'
       AND c.closed = false
   ```
   → Shows all active jobs with their current list

5. **Query for time in list**:
   ```sql
   WITH current_lists AS (
       SELECT 
           card_id,
           list_after_name as current_list,
           action_date as entered_list_at,
           ROW_NUMBER() OVER (PARTITION BY card_id ORDER BY action_date DESC) as rn
       FROM trello_rag.trello_webhook_events
       WHERE is_list_transition = true
   )
   SELECT 
       c.card_id,
       c.purchaser,
       cl.current_list,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), cl.entered_list_at, HOUR) as hours_in_current_list
   FROM trello_rag.cards c
   JOIN current_lists cl ON c.card_id = cl.card_id
   WHERE cl.rn = 1
       AND cl.current_list != 'Completed'
   ```
   → Shows how long each card has been in its current list

**Key Insights**: 
- `cards` table = **immutable metadata** (purchaser, creation date, extracted fields)
- `trello_webhook_events` table = **all state changes** (list transitions, current state)
- Join them together = **powerful analytics** (throughput, bottlenecks, etc.)
- **Safety**: Original card data never overwritten, full history preserved

## Architecture Decision: Immutable Master Table

### Why Immutable Master Table?

**Risks of Updating Master Table**:
- ❌ Data loss if update fails mid-process
- ❌ Overwrites original extraction (can't recover if later extraction is wrong)
- ❌ Race conditions if multiple webhooks arrive simultaneously
- ❌ Harder to audit "what was the original data?"

**Benefits of Immutable Master Table**:
- ✅ **Zero data loss risk** - original extraction always preserved
- ✅ **Idempotent** - can safely re-run extractions
- ✅ **Simpler logic** - no UPDATE operations, just INSERT
- ✅ **Full audit trail** - can see exactly when card was first seen
- ✅ **Event sourcing pattern** - all state changes in events table

**Tradeoff**:
- ⚠️ Current state queries require joining events table (slightly more complex SQL)
- ✅ **Solution**: Materialized view for fast current-state queries (refreshes every 5-15 min)

### Performance Considerations

**Query Performance**:
- Getting current list: Requires `ROW_NUMBER()` window function on events table
- For 10,000 cards: ~100-500ms query time (acceptable)
- For real-time dashboards: Use materialized view (refreshes every 5-15 min)

**Alternative: Hybrid Approach** (if performance becomes issue):
- Keep immutable master table
- Add separate `cards_current_state` table (updated on each transition)
- Can rebuild from events if needed
- Best of both worlds: safety + performance

**Recommendation**: Start with immutable master + events table. Add materialized view if needed. Only add separate current_state table if performance becomes an issue.

---

## Questions to Resolve

1. **Table Naming**: ✅ **DECIDED** - Single master table `trello_rag.cards` (immutable, INSERT only)

2. **Update Strategy**: ✅ **DECIDED** - Master table is INSERT only. Current state from events table.

3. **Extraction Trigger**: Extract on every webhook or only on specific actions?
   - **Recommendation**: Extract on `createCard` and `updateCard` (when description changes)

4. **Line Item Updates**: How to handle when line items change?
   - **Recommendation**: Delete all line items for card, re-insert (simpler than diffing)

5. **Historical Data**: How to handle cards that existed before webhook setup?
   - **Recommendation**: Keep snapshot tables, webhook pipeline handles new/updated cards going forward

6. **Card Deletion**: How to handle archived/deleted cards?
   - **Recommendation**: Mark as `closed = true` in master table, don't delete

7. **List Transition Tracking**: ✅ **ENHANCED** - Events table includes `list_before_name`, `list_after_name`, `is_list_transition` for comprehensive tracking

---

## Next Steps

1. Review and approve this plan
2. Set up BigQuery table for webhook events
3. Start with Phase 1 implementation
4. Test with a single webhook event
5. Iterate and refine based on real-world usage
