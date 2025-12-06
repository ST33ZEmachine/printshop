# Bourquin Signs - Data Context

## Overview
This BigQuery project contains data extracted from a Trello board that tracks signage orders for Bourquin Signs. The data is organized into two main tables with a parent-child relationship.

## Project Details
- **GCP Project**: `maxprint-479504`
- **Dataset**: `trello_rag`
- **Data Snapshot Date**: December 5, 2024

---

## Table Architecture

```
┌─────────────────────────────────────────┐
│  bourquin_05122025_snapshot             │
│  (CARDS - Master/Dimension Table)       │
│  ~12,500 rows                           │
├─────────────────────────────────────────┤
│  card_id (PK)                           │
│  name, desc, list_name, purchaser       │
│  buyer_name, buyer_email, etc.          │
└───────────────┬─────────────────────────┘
                │
                │ 1:N relationship
                │ (order_id = card_id)
                ▼
┌─────────────────────────────────────────┐
│  bourquin_05122025_snapshot_lineitems   │
│  (LINE ITEMS - Fact Table)              │
│  ~19,200 rows                           │
├─────────────────────────────────────────┤
│  order_id (FK to card_id)               │
│  line_index, price, quantity            │
│  material, dimensions, etc.             │
└─────────────────────────────────────────┘
```

---

## Table 1: bourquin_05122025_snapshot (Cards Master)

### Description
Contains one row per Trello card (order). This is the master record for each order with customer information, status, and metadata.

### Key Columns
| Column | Type | Description |
|--------|------|-------------|
| `card_id` | STRING | **Primary Key** - Unique identifier for the card/order |
| `name` | STRING | Card title (often contains: "Customer \| Product \| ID") |
| `desc` | STRING | Full card description with order details |
| `list_name` | STRING | Current status/stage (e.g., "New", "In Progress", "Complete") |
| `purchaser` | STRING | Company/customer name (parsed from title) |
| `order_summary` | STRING | Brief order description (parsed from title) |
| `primary_buyer_name` | STRING | Contact person name (LLM extracted) |
| `primary_buyer_email` | STRING | Contact email (LLM extracted) |
| `buyer_confidence` | STRING | Confidence of buyer extraction: high/medium/low |
| `dateLastActivity` | TIMESTAMP | Last update timestamp |
| `shortUrl` | STRING | Link to Trello card |

### Data Quality
- ~12,500 cards total
- ~88% have parseable order content
- Buyer info extracted via LLM with confidence scoring

---

## Table 2: bourquin_05122025_snapshot_lineitems (Line Items)

### Description
Contains extracted order line items from card descriptions. Each row represents one product/service within an order. Generated via LLM extraction with regex fallback.

### Key Columns
| Column | Type | Description |
|--------|------|-------------|
| `order_id` | STRING | **Foreign Key** - Links to `card_id` in cards table |
| `line_index` | INTEGER | Position within the order (1, 2, 3...) |
| `order_class` | STRING | "Supply", "Install", or "Supply & Install" |
| `quantity` | INTEGER | Number of items |
| `price` | FLOAT | Unit price in dollars |
| `raw_price_text` | STRING | Original price text for verification |
| `price_validated` | BOOLEAN | TRUE if price verified against source |
| `width_in` | FLOAT | Width in inches |
| `height_in` | FLOAT | Height in inches |
| `raw_dimensions_text` | STRING | Original dimension text (e.g., "24x36") |
| `material` | STRING | Product material (e.g., "Aluminum Composite Panel", "Coroplast") |
| `description` | STRING | Item description |
| `colour` | STRING | Color if specified |
| `extra_notes` | STRING | Additional notes, flags |
| `raw_line_text` | STRING | Original source text |
| `llm_confidence` | STRING | Extraction confidence: high/medium/low |

### Data Quality
- **19,203 line items** extracted
- **99.3% price accuracy** (verified via spot-check)
- **$1,954,895 total order value** captured
- Use `price_validated = TRUE` for highest confidence pricing data

### Extraction Methods
- **98% LLM extracted** (Gemini 2.5 Flash)
- **2% Regex extracted** (fallback for edge cases, marked with `[REGEX_EXTRACTED]` in extra_notes)

---

## Common Query Patterns

### Total Order Value
```sql
SELECT 
  SUM(price * COALESCE(quantity, 1)) as total_value,
  COUNT(*) as line_items
FROM `maxprint-479504.trello_rag.bourquin_05122025_snapshot_lineitems`
WHERE price_validated = TRUE;
```

### Revenue by Customer
```sql
SELECT 
  c.purchaser,
  COUNT(DISTINCT c.card_id) as orders,
  COUNT(*) as line_items,
  SUM(li.price * COALESCE(li.quantity, 1)) as total_value
FROM `maxprint-479504.trello_rag.bourquin_05122025_snapshot_lineitems` li
JOIN `maxprint-479504.trello_rag.bourquin_05122025_snapshot` c 
  ON li.order_id = c.card_id
WHERE li.price_validated = TRUE
GROUP BY c.purchaser
ORDER BY total_value DESC
LIMIT 20;
```

### Revenue by Material Type
```sql
SELECT 
  material,
  COUNT(*) as line_items,
  SUM(price * COALESCE(quantity, 1)) as total_value,
  AVG(price) as avg_unit_price
FROM `maxprint-479504.trello_rag.bourquin_05122025_snapshot_lineitems`
WHERE material IS NOT NULL AND price_validated = TRUE
GROUP BY material
ORDER BY total_value DESC;
```

### Orders by Status
```sql
SELECT 
  c.list_name as status,
  COUNT(DISTINCT c.card_id) as orders,
  SUM(li.price * COALESCE(li.quantity, 1)) as total_value
FROM `maxprint-479504.trello_rag.bourquin_05122025_snapshot` c
LEFT JOIN `maxprint-479504.trello_rag.bourquin_05122025_snapshot_lineitems` li
  ON c.card_id = li.order_id
GROUP BY c.list_name
ORDER BY orders DESC;
```

### High-Value Orders
```sql
SELECT 
  c.card_id,
  c.purchaser,
  c.name as order_name,
  SUM(li.price * COALESCE(li.quantity, 1)) as order_total
FROM `maxprint-479504.trello_rag.bourquin_05122025_snapshot` c
JOIN `maxprint-479504.trello_rag.bourquin_05122025_snapshot_lineitems` li
  ON c.card_id = li.order_id
WHERE li.price_validated = TRUE
GROUP BY c.card_id, c.purchaser, c.name
HAVING order_total > 1000
ORDER BY order_total DESC
LIMIT 50;
```

### Product Size Analysis
```sql
SELECT 
  CASE 
    WHEN width_in * height_in > 2000 THEN 'Large (>2000 sq in)'
    WHEN width_in * height_in > 500 THEN 'Medium (500-2000 sq in)'
    ELSE 'Small (<500 sq in)'
  END as size_category,
  COUNT(*) as items,
  AVG(price) as avg_price
FROM `maxprint-479504.trello_rag.bourquin_05122025_snapshot_lineitems`
WHERE width_in IS NOT NULL AND height_in IS NOT NULL
GROUP BY size_category;
```

---

## Important Notes

### Price Data Confidence
- **Use `price_validated = TRUE`** for financial analysis
- ~0.3% of prices may have extraction errors (batch processing artifacts)
- Validated prices were cross-checked against original source text

### Joining Tables
- Always join on `order_id = card_id`
- One card can have multiple line items (avg 1.7 per card)
- Some cards have no line items (non-order cards like notes, measurements)

### Common Materials
- Aluminum Composite Panel (ACP)
- Coroplast (corrugated plastic)
- Vinyl (cut vinyl, printed vinyl)
- Acrylic
- Sintra
- Lexan
- Styrene

### Order Classes
- **Supply**: Materials/products only
- **Install**: Installation labor only
- **Supply & Install**: Both materials and installation

---

## Future Tables (Planned)

### card_events (Event-Driven Data)
Will capture real-time Trello webhooks:
- Card created/updated/moved/archived events
- Workflow timing analytics
- Status change history
