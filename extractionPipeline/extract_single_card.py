#!/usr/bin/env python3
"""
Single Card Extraction Service

Extracts data from a single Trello card using Gemini LLM.
Reuses logic from extract_trello_data.py for consistency.

Usage:
    from extract_single_card import CardExtractionService
    
    service = CardExtractionService(project_id="...", model_id="...")
    extracted = await service.extract_single_card(card_data)
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from pathlib import Path
from google import genai
from google.genai import types

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

# System prompt (same as batch extraction)
SYSTEM_PROMPT = """Extract line items from signage orders. For each card return JSON:
{"card_id":"...", "items":[{"qty":1, "price":100.00, "price_type":"total", "desc":"item description"}], "buyer_name":"...", "buyer_email":"..."}

price_type: "per_unit" if price has "ea"/"each", otherwise "total".
Return JSON array, one object per card."""

ENRICH_PROMPT = """Classify line items from a signage company.

For each line item, determine:

1. **business_line** - Choose ONE:
   - "Signage" - Signs, banners, decals, vehicle wraps, channel letters, pylons, ACP panels, coroplast, building signage, vinyl graphics
   - "Printing" - Business cards, flyers, brochures, booklets, invoices, forms, apparel printing, promotional items, labels
   - "Engraving" - Engraved plaques, nameplates, trophies, awards, laser-cut items, etched materials

2. **material** - Extract the material (e.g., "Aluminum", "Acrylic", "Vinyl", "Coroplast", "14PT Coated", "ACP", "Foamcore") or null

3. **dimensions** - Extract dimensions as string (e.g., "36x24", "3.5x2", "96x48") or null

Return JSON array matching input order:
[{"business_line": "Signage", "material": "Vinyl", "dimensions": "36x24"}, ...]
"""


def extract_title_fields(card_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract purchaser and order_summary from card title."""
    if not card_name or "|" not in card_name:
        return None, None
    parts = [p.strip() for p in card_name.split("|")]
    purchaser = parts[0] if len(parts) > 0 and parts[0] else None
    order_summary = parts[1] if len(parts) > 1 and parts[1] else None
    return purchaser, order_summary


def calculate_prices(raw_price: Optional[float], quantity: Optional[int], price_type: str) -> Dict[str, Any]:
    """Calculate unit_price and total_revenue from extracted data."""
    if raw_price is None:
        return {'unit_price': None, 'total_revenue': None}
    
    if quantity is None or quantity <= 0:
        quantity = 1
    
    if price_type == 'per_unit':
        unit_price = raw_price
        total_revenue = round(unit_price * quantity, 2)
    else:
        total_revenue = raw_price
        unit_price = round(total_revenue / quantity, 2)
    
    return {'unit_price': unit_price, 'total_revenue': total_revenue}


def extract_created_date(card_id: str) -> Dict[str, Any]:
    """
    Extract creation timestamp from Trello card ID.
    
    First 8 hex characters = Unix timestamp of card creation.
    Returns dict with timestamp and formatted dates.
    """
    from datetime import datetime
    
    if not card_id or len(card_id) < 8:
        return {
            'date_created': None,
            'datetime_created': None,
            'year_created': None,
            'month_created': None,
            'year_month': None,
            'unix_timestamp': None
        }
    
    try:
        # First 8 chars are hex timestamp
        hex_timestamp = card_id[:8]
        unix_timestamp = int(hex_timestamp, 16)
        
        # Convert to datetime
        dt = datetime.fromtimestamp(unix_timestamp)
        
        return {
            'date_created': dt.strftime('%Y-%m-%d'),
            'datetime_created': dt.isoformat(),
            'year_created': dt.year,
            'month_created': dt.month,
            'year_month': dt.strftime('%Y-%m'),
            'unix_timestamp': unix_timestamp
        }
    except (ValueError, OSError):
        # Invalid hex or timestamp out of range
        return {
            'date_created': None,
            'datetime_created': None,
            'year_created': None,
            'month_created': None,
            'year_month': None,
            'unix_timestamp': None
        }


class CardExtractionService:
    """Service for extracting data from a single Trello card."""
    
    def __init__(
        self,
        project_id: Optional[str] = None,
        model_id: Optional[str] = None,
        location: str = "us-central1",
    ):
        self.project_id = project_id or os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.model_id = model_id or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
        self.location = location or os.environ.get("GCP_LOCATION", "us-central1")
        
        if not self.project_id:
            raise ValueError("project_id must be provided or set in BIGQUERY_PROJECT/GOOGLE_CLOUD_PROJECT")
        
        # Initialize Gemini client
        self.client = genai.Client(vertexai=True, project=self.project_id, location=self.location)
        logger.info(f"Initialized CardExtractionService (project: {self.project_id}, model: {self.model_id})")
    
    def extract_single_card(
        self,
        card: Dict[str, Any],
        enrich: bool = True,
    ) -> Dict[str, Any]:
        """
        Extract data from a single card using Gemini LLM.
        
        Args:
            card: Trello card data dict with 'id', 'name', 'desc' fields
            enrich: If True, also enrich line items with business_line, material, dimensions
            
        Returns:
            Enriched card dict with:
            - purchaser, order_summary (from title parsing)
            - primary_buyer_name, primary_buyer_email (from LLM extraction)
            - line_items (list of extracted line items with pricing)
            - line_item_count
            - If enrich=True: line items also have business_line, material, dimensions
        """
        # Prepare card input (same format as batch extraction)
        card_input = {
            "id": card.get("id", ""),
            "name": card.get("name", ""),
            "desc": (card.get("desc", "") or "")[:2000]  # Truncate long descriptions
        }
        
        prompt = f"""Cards:\n{json.dumps([card_input])}\n\nReturn JSON array."""
        
        try:
            # Call Gemini API (synchronous for now, can be made async later)
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )
            
            # Parse response
            response_text = response.text.strip()
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                lines = [l for l in lines if not l.strip().startswith('```')]
                response_text = '\n'.join(lines)
            
            results = json.loads(response_text)
            if not isinstance(results, list):
                results = [results]
            
            # Get result for this card
            result = results[0] if results else {}
            card_id = card.get('id', '')
            if result.get('card_id') != card_id:
                # Try to find matching result
                result = next((r for r in results if r.get('card_id') == card_id), {})
            
            # Build enriched card
            enriched = card.copy()
            
            # Extract dates from card ID
            card_id = card.get('id', '')
            date_info = extract_created_date(card_id)
            enriched.update(date_info)
            
            # Title fields
            purchaser, order_summary = extract_title_fields(card.get('name', ''))
            enriched['purchaser'] = purchaser
            enriched['order_summary'] = order_summary
            
            # Buyer info
            enriched['primary_buyer_name'] = result.get('buyer_name')
            enriched['primary_buyer_email'] = result.get('buyer_email')
            
            # Line items
            items = result.get('items', [])
            processed_items = []
            
            for idx, item in enumerate(items, 1):
                raw_price = item.get('price')
                if raw_price is not None:
                    try:
                        raw_price = float(raw_price)
                    except (ValueError, TypeError):
                        raw_price = None
                
                quantity = item.get('qty', 1)
                try:
                    quantity = int(quantity)
                except (ValueError, TypeError):
                    quantity = 1
                
                price_type = (item.get('price_type') or 'total').lower()
                calc = calculate_prices(raw_price, quantity, price_type)
                
                processed_items.append({
                    'line_index': idx,
                    'quantity': quantity,
                    'raw_price': raw_price,
                    'price_type': price_type,
                    'unit_price': calc['unit_price'],
                    'total_revenue': calc['total_revenue'],
                    'description': item.get('desc', '')
                })
            
            enriched['line_items'] = processed_items
            enriched['line_item_count'] = len(processed_items)
            
            # Optional: Enrich line items with business_line, material, dimensions
            if enrich and processed_items:
                enriched['line_items'] = self._enrich_line_items(processed_items)
            
            logger.debug(f"Extracted card {card_id}: {len(processed_items)} line items")
            return enriched
            
        except Exception as e:
            logger.error(f"Extraction error for card {card.get('id', 'unknown')}: {e}")
            # Return card with error flag
            enriched = card.copy()
            enriched['extraction_error'] = str(e)
            enriched['line_items'] = []
            enriched['line_item_count'] = 0
            enriched['primary_buyer_name'] = None
            enriched['primary_buyer_email'] = None
            return enriched
    
    def _enrich_line_items(self, line_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich line items with business_line, material, dimensions.
        
        This is a second LLM pass that classifies each line item.
        """
        if not line_items:
            return line_items
        
        # Prepare input for enrichment
        items_input = []
        for item in line_items:
            items_input.append({
                "description": (item.get("description") or "")[:200],
                "quantity": item.get("quantity"),
                "revenue": item.get("total_revenue", 0)
            })
        
        prompt = f"""Classify these {len(items_input)} line items:

{json.dumps(items_input)}

Return JSON array with business_line, material, dimensions for each (same order as input)."""
        
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=ENRICH_PROMPT,
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )
            
            text = response.text.strip()
            if text.startswith('```'):
                text = '\n'.join(l for l in text.split('\n') if not l.strip().startswith('```'))
            
            results = json.loads(text)
            if not isinstance(results, list):
                results = [results]
            
            # Merge enrichment results back into line items
            enriched_items = []
            for i, item in enumerate(line_items):
                enriched_item = item.copy()
                if i < len(results):
                    result = results[i]
                    enriched_item['business_line'] = result.get('business_line')
                    enriched_item['material'] = result.get('material')
                    enriched_item['dimensions'] = result.get('dimensions')
                else:
                    # No result for this item
                    enriched_item['business_line'] = None
                    enriched_item['material'] = None
                    enriched_item['dimensions'] = None
                enriched_items.append(enriched_item)
            
            logger.debug(f"Enriched {len(enriched_items)} line items")
            return enriched_items
            
        except Exception as e:
            logger.warning(f"Enrichment error: {e}, returning items without enrichment")
            # Return items without enrichment on error
            for item in line_items:
                item.setdefault('business_line', None)
                item.setdefault('material', None)
                item.setdefault('dimensions', None)
            return line_items


def format_card_for_bigquery(
    card: Dict[str, Any],
    board_id: Optional[str] = None,
    board_name: Optional[str] = None,
    list_id: Optional[str] = None,
    list_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format extracted card data for BigQuery insertion.
    
    Converts Trello card format to BigQuery schema format.
    Handles date parsing, label formatting, etc.
    
    Args:
        card: Extracted card dict (from extract_single_card)
        board_id: Board ID (if not in card)
        board_name: Board name (if not in card)
        list_id: List ID (if not in card)
        list_name: List name (if not in card)
    """
    # Process labels
    label_names = []
    for lbl in card.get("labels", []):
        if isinstance(lbl, dict):
            name = (lbl.get("name") or "").strip()
        elif isinstance(lbl, str):
            name = lbl.strip()
        else:
            name = str(lbl).strip()
        if name:
            label_names.append(name)
    labels_str = ", ".join(label_names) if label_names else None
    
    # Get list info (prefer provided params, then card fields)
    final_list_id = list_id or card.get("idList") or card.get("list_id")
    final_list_name = list_name or card.get("list_name")
    
    # Format dates (should already be extracted from card ID)
    date_last_activity = card.get("dateLastActivity")
    datetime_created = card.get("datetime_created")
    date_created = card.get("date_created")
    
    # Build BigQuery row
    row = {
        "card_id": card.get("id") or card.get("card_id"),
        "name": card.get("name"),
        "desc": card.get("desc"),
        "labels": labels_str,
        "closed": card.get("closed", False),
        "dateLastActivity": date_last_activity,
        "purchaser": card.get("purchaser"),
        "order_summary": card.get("order_summary"),
        "primary_buyer_name": card.get("primary_buyer_name"),
        "primary_buyer_email": card.get("primary_buyer_email"),
        "date_created": date_created,
        "datetime_created": datetime_created,
        "year_created": card.get("year_created"),
        "month_created": card.get("month_created"),
        "year_month": card.get("year_month"),
        "unix_timestamp": card.get("unix_timestamp"),
        "line_item_count": card.get("line_item_count", 0),
        # List/board tracking
        "list_id": final_list_id,
        "list_name": final_list_name,
        "board_id": board_id or card.get("board_id") or card.get("idBoard"),
        "board_name": board_name or card.get("board_name"),
    }
    
    return row


def format_line_items_for_bigquery(card_id: str, line_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format extracted line items for BigQuery insertion.
    
    Args:
        card_id: The card ID
        line_items: List of line item dicts from extraction
        
    Returns:
        List of formatted line item rows for BigQuery
    """
    rows = []
    for item in line_items:
        rows.append({
            "card_id": card_id,
            "line_index": item.get("line_index"),
            "quantity": item.get("quantity"),
            "raw_price": item.get("raw_price"),
            "price_type": item.get("price_type"),
            "unit_price": item.get("unit_price"),
            "total_revenue": item.get("total_revenue"),
            "description": item.get("description"),
            "business_line": item.get("business_line"),  # May be None if not enriched
            "material": item.get("material"),  # May be None if not enriched
            "dimensions": item.get("dimensions"),  # May be None if not enriched
        })
    return rows
