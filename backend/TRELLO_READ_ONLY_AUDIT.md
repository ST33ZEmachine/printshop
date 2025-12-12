# Trello API Read-Only Audit

## Summary
✅ **All board data operations are READ-ONLY**. No card, list, or board data is modified.

## Board Data Operations (All Read-Only)

### 1. `get_board(board_id)` - READ ONLY
- **Method**: `GET /boards/{board_id}`
- **Purpose**: Fetch board information
- **Impact**: Read-only, no modifications

### 2. `fetch_card(card_id)` - READ ONLY
- **Method**: `GET /cards/{card_id}`
- **Purpose**: Fetch full card data (description, attachments, comments)
- **Impact**: Read-only, no modifications
- **Used by**: Webhook pipeline to get complete card data for extraction

### 3. Webhook Endpoint - READ ONLY
- **Method**: `POST /trello/webhook` (receives webhooks from Trello)
- **Purpose**: Receive webhook notifications about board changes
- **Impact**: Read-only, just receiving data that Trello sends
- **Note**: This is Trello pushing data TO us, not us modifying Trello

## Infrastructure Operations (Not Board Data)

### 4. `register_webhook()` - Infrastructure Only
- **Method**: `POST /webhooks`
- **Purpose**: Register a webhook subscription
- **Impact**: Creates webhook infrastructure (not board content)
- **Note**: This is like subscribing to notifications, not modifying board data

### 5. `delete_webhook()` - Infrastructure Only
- **Method**: `DELETE /webhooks/{webhook_id}`
- **Purpose**: Remove webhook subscription
- **Impact**: Deletes webhook infrastructure (not board content)
- **Note**: This is like unsubscribing from notifications, not modifying board data

### 6. `list_webhooks()` - READ ONLY
- **Method**: `GET /tokens/{token}/webhooks`
- **Purpose**: List webhook subscriptions
- **Impact**: Read-only, no modifications

## What We Do With the Data

All data we read from Trello is:
1. **Stored in BigQuery** (our database, not Trello)
2. **Processed for extraction** (using Gemini AI)
3. **Never written back to Trello**

## Code Evidence

The `TrelloService` class is explicitly documented as:
```python
class TrelloService:
    """Helper for Trello API interactions (non-destructive)."""
```

All board data methods use `GET` requests only:
- `get_board()` → `GET /boards/{board_id}`
- `fetch_card()` → `GET /cards/{card_id}`

## Conclusion

✅ **100% Read-Only for Board Data**
- No card modifications
- No list modifications  
- No board modifications
- Only reading data and storing it in our own database (BigQuery)

The only write operations are:
- Creating/deleting webhook subscriptions (infrastructure, not board content)
- Writing to BigQuery (our database, separate from Trello)
