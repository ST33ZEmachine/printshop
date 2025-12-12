# Trello Webhook Pipeline - Final Architecture

## Table Schemas

### 1. `trello_rag.cards` (Master - Immutable)

**Purpose**: Original extraction when card was first created. Never updated.

**Schema**:
```python
[
    bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),  # Primary key
    bigquery.SchemaField("name", "STRING"),  # Initial name
    bigquery.SchemaField("desc", "STRING"),  # Initial description
    bigquery.SchemaField("labels", "STRING"),  # Comma-separated
    bigquery.SchemaField("closed", "BOOLEAN"),
    bigquery.SchemaField("dateLastActivity", "TIMESTAMP"),
    bigquery.SchemaField("board_id", "STRING"),
    bigquery.SchemaField("board_name", "STRING"),
    bigquery.SchemaField("list_id", "STRING"),  # Initial list
    bigquery.SchemaField("list_name", "STRING"),  # Initial list name
    # Enriched fields - title parsing
    bigquery.SchemaField("purchaser", "STRING"),
    bigquery.SchemaField("order_summary", "STRING"),
    # Enriched fields - buyer extraction
    bigquery.SchemaField("primary_buyer_name", "STRING"),
    bigquery.SchemaField("primary_buyer_email", "STRING"),
    # Date fields
    bigquery.SchemaField("date_created", "DATE"),
    bigquery.SchemaField("datetime_created", "TIMESTAMP"),
    bigquery.SchemaField("year_created", "INTEGER"),
    bigquery.SchemaField("month_created", "INTEGER"),
    bigquery.SchemaField("year_month", "STRING"),
    bigquery.SchemaField("unix_timestamp", "INTEGER"),
    # Summary
    bigquery.SchemaField("line_item_count", "INTEGER"),
    # Metadata
    bigquery.SchemaField("first_extracted_at", "TIMESTAMP"),
    bigquery.SchemaField("first_extraction_event_id", "STRING"),
]
```

---

### 2. `trello_rag.cards_current` (Current State - Updated)

**Purpose**: Latest state of all cards. Updated on any card change.

**Schema**: Same as `cards` table, plus:
```python
[
    # ... all fields from cards table ...
    bigquery.SchemaField("last_updated_at", "TIMESTAMP"),  # When current record was last updated
    bigquery.SchemaField("last_extracted_at", "TIMESTAMP"),  # When LLM extraction last ran
    bigquery.SchemaField("last_extraction_event_id", "STRING"),  # Event that triggered last extraction
]
```

**Update Logic**:
- **Description changed**: Re-extract with LLM → Update all fields
- **Metadata changed** (list, labels, name, etc.): Update metadata fields only (no LLM)

---

### 3. `trello_rag.line_items` (Master - Immutable)

**Purpose**: Original line items extraction. Never updated.

**Schema**:
```python
[
    bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),  # Foreign key to cards
    bigquery.SchemaField("line_index", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("quantity", "INTEGER"),
    bigquery.SchemaField("raw_price", "FLOAT"),
    bigquery.SchemaField("price_type", "STRING"),  # "per_unit" or "total"
    bigquery.SchemaField("unit_price", "FLOAT"),
    bigquery.SchemaField("total_revenue", "FLOAT"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("business_line", "STRING"),  # "Signage", "Printing", "Engraving"
    bigquery.SchemaField("material", "STRING"),
    bigquery.SchemaField("dimensions", "STRING"),
]
```

---

### 4. `trello_rag.line_items_current` (Current State - Updated)

**Purpose**: Latest line items extraction. Updated only when description changes.

**Schema**: Same as `line_items` table.

**Update Logic**:
- **Description changed**: Delete all line items for card → Insert new ones from extraction
- **Metadata changed**: No update (line items don't change)

---

### 5. `trello_rag.trello_webhook_events` (Events Log - Immutable)

**Purpose**: Complete audit trail of all webhook events.

**Schema**:
```python
[
    bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),  # action.id (idempotency key)
    bigquery.SchemaField("action_type", "STRING"),  # "createCard", "updateCard", etc.
    bigquery.SchemaField("action_date", "TIMESTAMP"),  # When action occurred in Trello
    bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("board_id", "STRING"),
    bigquery.SchemaField("board_name", "STRING"),
    # List transition tracking
    bigquery.SchemaField("list_id", "STRING"),
    bigquery.SchemaField("list_name", "STRING"),
    bigquery.SchemaField("list_before_id", "STRING"),
    bigquery.SchemaField("list_before_name", "STRING"),
    bigquery.SchemaField("list_after_id", "STRING"),
    bigquery.SchemaField("list_after_name", "STRING"),
    bigquery.SchemaField("is_list_transition", "BOOLEAN"),
    # Metadata
    bigquery.SchemaField("member_creator_id", "STRING"),
    bigquery.SchemaField("member_creator_username", "STRING"),
    bigquery.SchemaField("raw_payload", "JSON"),  # Full webhook payload
    # Processing status
    bigquery.SchemaField("processed", "BOOLEAN"),
    bigquery.SchemaField("processed_at", "TIMESTAMP"),
    bigquery.SchemaField("extraction_triggered", "BOOLEAN"),  # Did this trigger LLM extraction?
    bigquery.SchemaField("error_message", "STRING"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),  # When we received webhook
]
```

**Partitioning**: By `created_at` (daily)
**Clustering**: By `card_id`, `action_type`, `is_list_transition`

---

## End-to-End Process Flow

### Step 1: Webhook Arrives

```
Trello → POST /trello/webhook
  ↓
FastAPI Router receives webhook payload
  ↓
Validate payload (TrelloWebhookPayload)
  ↓
Return 200 OK (acknowledge to Trello)
```

### Step 2: Store Raw Event

```
Publisher.publish(action)
  ↓
Check idempotency: Does event_id exist in events table?
  ↓
If exists → Skip (already processed)
If not → Continue
  ↓
Insert into trello_webhook_events:
  - event_id, action_type, action_date
  - card_id, board_id, list info
  - raw_payload (full JSON)
  - processed = false
  - created_at = NOW()
```

### Step 3: Process Event (Async)

```
Background task: _process_event(action)
  ↓
Only process card-related actions:
  - createCard
  - updateCard
  - (others logged but not processed)
  ↓
Fetch full card data from Trello API:
  GET /cards/{card_id}?fields=all&attachments=true
  ↓
Determine what changed:
```

### Step 4: Determine Processing Logic

```
Check action_type:
  ↓
┌─────────────────────────────────────────┐
│ createCard                               │
│ → Card doesn't exist in master          │
│ → Extract with LLM                       │
│ → Insert into cards (master)             │
│ → Insert into cards_current              │
│ → Insert into line_items (master)        │
│ → Insert into line_items_current         │
└─────────────────────────────────────────┘
  ↓
┌─────────────────────────────────────────┐
│ updateCard                               │
│ → Check: Did description change?        │
│   (Compare with last desc from events)  │
│                                          │
│   YES → Description Changed:            │
│     → Re-extract with LLM               │
│     → Update cards_current (all fields) │
│     → Delete line_items_current         │
│     → Insert new line_items_current     │
│                                          │
│   NO → Metadata Only Changed:            │
│     → Update cards_current (metadata)   │
│     → Skip line_items (no change)       │
└─────────────────────────────────────────┘
```

### Step 5: LLM Extraction (If Description Changed)

```
Extract with Gemini API:
  ↓
Input: Card name + description
  ↓
Output: JSON with:
  - purchaser, order_summary
  - buyer_name, buyer_email
  - line_items array:
    - quantity, price, price_type
    - description
    - (business_line, material, dimensions - if enriched)
  ↓
Calculate: unit_price, total_revenue
```

### Step 6: Update Database Tables

#### For createCard:
```python
# Insert into master (immutable)
insert_cards_master(extracted_card)
insert_line_items_master(extracted_card.line_items)

# Insert into current (same data initially)
insert_cards_current(extracted_card)
insert_line_items_current(extracted_card.line_items)
```

#### For updateCard (description changed):
```python
# Master tables unchanged (immutable)

# Update current cards
upsert_cards_current(extracted_card)  # MERGE statement

# Update current line items (delete + re-insert)
delete_line_items_current(card_id)
insert_line_items_current(extracted_card.line_items)
```

#### For updateCard (metadata only):
```python
# Update cards_current metadata only
update_cards_current_metadata(card_id, {
    'list_name': new_list_name,
    'list_id': new_list_id,
    'labels': new_labels,
    'name': new_name,
    # etc.
})
# line_items_current unchanged
```

### Step 7: Mark Event as Processed

```
Update trello_webhook_events:
  - processed = true
  - processed_at = NOW()
  - extraction_triggered = true/false
  - error_message = NULL (if success)
```

### Step 8: Agent Queries Data

```
User asks question via chat API
  ↓
Agent queries BigQuery:
  ↓
For current state queries:
  SELECT * FROM trello_rag.cards_current
  JOIN trello_rag.line_items_current
  WHERE ...
  ↓
For list transition queries:
  SELECT * FROM trello_rag.trello_webhook_events
  WHERE is_list_transition = true
  ORDER BY action_date DESC
  ↓
Agent returns answer to user
```

---

## Key Decision Points

### When to Extract with LLM:
- ✅ Card created (`createCard`)
- ✅ Description field changed (`updateCard` with desc change)
- ❌ List moved (metadata only)
- ❌ Labels changed (metadata only)
- ❌ Name changed (metadata only)

### When to Update Current Tables:
- ✅ Always update `cards_current` (metadata or full update)
- ✅ Only update `line_items_current` when description changes
- ❌ Never update master tables (immutable)

### Idempotency:
- Use `event_id` (action.id) as unique key
- Check before processing
- Skip if already processed

### Error Handling:
- Store errors in `events.error_message`
- Mark `processed = false` on error
- Can reprocess failed events later

---

## Example Scenarios

### Scenario 1: New Card Created

```
1. Webhook: createCard
2. Store event in events table
3. Fetch full card from Trello API
4. Extract with LLM
5. Insert into cards (master)
6. Insert into cards_current
7. Insert into line_items (master)
8. Insert into line_items_current
9. Mark event processed
```

### Scenario 2: Card Moved to New List

```
1. Webhook: updateCard (list changed)
2. Store event in events table
3. Fetch full card from Trello API
4. Check: Description changed? NO
5. Update cards_current (list_name, list_id only)
6. Skip line_items (no change)
7. Mark event processed
```

### Scenario 3: Description Updated (Pricing Changed)

```
1. Webhook: updateCard (desc changed)
2. Store event in events table
3. Fetch full card from Trello API
4. Check: Description changed? YES
5. Re-extract with LLM
6. Update cards_current (all fields)
7. Delete + re-insert line_items_current
8. Mark event processed (extraction_triggered = true)
```

---

## Table Relationships

```
cards (master)
  ↓ (card_id)
line_items (master)
  ↓ (card_id)
cards_current ←→ line_items_current (card_id)
  ↓ (card_id)
trello_webhook_events (many events per card)
```

---

## Query Patterns

### Get Current Active Jobs
```sql
SELECT 
    c.card_id,
    c.name,
    c.purchaser,
    c.list_name as current_list,
    SUM(li.total_revenue) as total_revenue
FROM trello_rag.cards_current c
LEFT JOIN trello_rag.line_items_current li ON c.card_id = li.card_id
WHERE c.closed = false
    AND c.list_name != 'Completed'
GROUP BY c.card_id, c.name, c.purchaser, c.list_name
```

### Get List Transition History
```sql
SELECT 
    card_id,
    list_before_name,
    list_after_name,
    action_date,
    TIMESTAMP_DIFF(
        LEAD(action_date) OVER (PARTITION BY card_id ORDER BY action_date),
        action_date,
        HOUR
    ) as hours_in_list
FROM trello_rag.trello_webhook_events
WHERE is_list_transition = true
ORDER BY card_id, action_date
```

### Get Current Revenue by Customer
```sql
SELECT 
    c.purchaser,
    SUM(li.total_revenue) as total_revenue,
    COUNT(DISTINCT c.card_id) as order_count
FROM trello_rag.cards_current c
JOIN trello_rag.line_items_current li ON c.card_id = li.card_id
WHERE c.closed = false
GROUP BY c.purchaser
ORDER BY total_revenue DESC
```

---

## Summary

**5 Tables**:
1. `cards` - Master (immutable)
2. `cards_current` - Current state (updated)
3. `line_items` - Master (immutable)
4. `line_items_current` - Current state (updated on desc change)
5. `trello_webhook_events` - Event log (immutable)

**Process**:
1. Webhook → Store event
2. Check idempotency
3. Fetch full card data
4. Determine if extraction needed
5. Update current tables
6. Mark processed

**Agent**:
- Queries `cards_current` + `line_items_current` for current state
- Queries `trello_webhook_events` for history/transitions
