# Trello Order Data Context

## Overview
This BigQuery project contains data extracted from a Trello board that tracks orders made to the business. The data structure reflects how orders are organized in Trello.

## Data Source
- **Source**: Trello board
- **Purpose**: Track and manage business orders
- **Data Type**: Order information, customer details, order statuses

## Understanding Trello Data Structure

### Key Concepts
- **Cards**: Represent individual orders
- **Lists**: Represent order statuses/stages (e.g., "New Orders", "In Progress", "Completed", "Shipped")
- **Labels**: May represent order types, priorities, or categories
- **Members**: May represent assigned staff or customers
- **Custom Fields**: May contain order-specific data like amounts, quantities, dates

### Common Data Patterns

#### Order Information
- Order IDs (may be card IDs or custom fields)
- Order dates (card creation date, due dates)
- Order status (list name where card resides)
- Order amounts/pricing (custom fields or card descriptions)
- Customer information (card members, custom fields, or descriptions)

#### Status Tracking
- Order status is typically represented by which Trello list the card is in
- Common statuses might include:
  - New/Received
  - Processing/In Progress
  - Pending
  - Completed/Fulfilled
  - Shipped
  - Cancelled

#### Date Fields
- **Created Date**: When the order was first created (card creation)
- **Due Date**: When the order should be completed
- **Last Activity**: When the order was last updated
- **Completion Date**: When the order moved to completed status

## Querying Tips

### Finding Orders
- Look for tables with names like: `orders`, `cards`, `trello_cards`, `order_data`
- Order IDs might be in columns like: `order_id`, `card_id`, `id`, `order_number`

### Finding Status Information
- Status might be in: `status`, `list_name`, `list_id`, `stage`, `order_status`
- May need to join with a lists/statuses table

### Finding Customer Information
- Customer data might be in: `customer_name`, `member_name`, `client`, `customer_id`
- Could be in the same table as orders or a separate customers table

### Finding Order Values
- Amounts might be in: `amount`, `total`, `price`, `value`, `cost`
- Could be in custom fields or card descriptions

## Common Query Patterns

### Order Status Summary
```sql
-- Example: Count orders by status
SELECT status, COUNT(*) as order_count
FROM orders
GROUP BY status
ORDER BY order_count DESC
```

### Orders by Date Range
```sql
-- Example: Orders in a date range
SELECT *
FROM orders
WHERE order_date BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY order_date DESC
```

### Customer Order History
```sql
-- Example: Orders by customer
SELECT customer_name, COUNT(*) as total_orders, SUM(amount) as total_value
FROM orders
GROUP BY customer_name
ORDER BY total_value DESC
```

## Notes
- Table and column names may vary based on how Trello data was exported
- Some data might be in JSON format if custom fields were preserved
- Date formats may need conversion depending on export format
- Always verify actual table and column names using schema discovery tools

