"""
Generate HTML Review Viewer

Creates an HTML file to review extraction and judgment results in a browser.
Shows original card data, extracted fields, and judge evaluations.

Usage:
    python generate_review_html.py [--input JUDGED_FILE] [--output OUTPUT_HTML]
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_grade_color(grade: str) -> str:
    """Get color for grade."""
    colors = {
        "A": "#10b981",  # green
        "B": "#3b82f6",  # blue
        "C": "#f59e0b",  # amber
        "D": "#ef4444",  # red
        "F": "#dc2626",  # dark red
    }
    return colors.get(grade.upper(), "#6b7280")


def get_score_color(score: float) -> str:
    """Get color for score (0-100)."""
    if score >= 80:
        return "#10b981"  # green
    elif score >= 60:
        return "#f59e0b"  # amber
    else:
        return "#ef4444"  # red


def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;"))


def format_text(text: str, max_length: int = 500) -> str:
    """Format text with line breaks and truncation."""
    if not text:
        return "<em>No description</em>"
    text = escape_html(text)
    if len(text) > max_length:
        return text[:max_length] + f"<span class='truncated'>... ({len(text) - max_length} more characters)</span>"
    return text.replace("\n", "<br>")


def generate_html(cards: List[Dict[str, Any]], stats: Dict[str, Any] = None) -> str:
    """Generate HTML content for review."""
    
    # Calculate summary stats
    total_cards = len(cards)
    cards_with_extraction = sum(1 for c in cards if c.get("buyer_names") or c.get("buyer_emails"))
    cards_with_judgment = sum(1 for c in cards if c.get("judgment"))
    
    if stats:
        grade_dist = stats.get("grade_distribution", {})
        avg_scores = {
            "accuracy": stats.get("average_accuracy", 0),
            "completeness": stats.get("average_completeness", 0),
            "overall": stats.get("average_overall", 0),
        }
    else:
        grade_dist = {}
        avg_scores = {"accuracy": 0, "completeness": 0, "overall": 0}
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Extraction Review - Buyer Information</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            color: #1f2937;
            line-height: 1.6;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        
        .header h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}
        
        .header .subtitle {{
            opacity: 0.9;
            font-size: 1rem;
        }}
        
        .stats-bar {{
            background: white;
            padding: 1.5rem 2rem;
            display: flex;
            gap: 2rem;
            flex-wrap: wrap;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }}
        
        .stat-item {{
            display: flex;
            flex-direction: column;
        }}
        
        .stat-label {{
            font-size: 0.875rem;
            color: #6b7280;
            margin-bottom: 0.25rem;
        }}
        
        .stat-value {{
            font-size: 1.5rem;
            font-weight: 600;
            color: #1f2937;
        }}
        
        .filters {{
            background: white;
            padding: 1rem 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            align-items: center;
        }}
        
        .filter-group {{
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }}
        
        .filter-group label {{
            font-size: 0.875rem;
            color: #6b7280;
        }}
        
        .filter-group select {{
            padding: 0.5rem;
            border: 1px solid #d1d5db;
            border-radius: 0.375rem;
            font-size: 0.875rem;
        }}
        
        .cards-container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 2rem 2rem;
        }}
        
        .card {{
            background: white;
            border-radius: 0.5rem;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: box-shadow 0.2s;
        }}
        
        .card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid #e5e7eb;
        }}
        
        .card-title {{
            font-size: 1.25rem;
            font-weight: 600;
            color: #1f2937;
            flex: 1;
        }}
        
        .card-id {{
            font-size: 0.75rem;
            color: #9ca3af;
            font-family: monospace;
        }}
        
        .grade-badge {{
            display: inline-block;
            padding: 0.5rem 1rem;
            border-radius: 0.375rem;
            font-weight: 600;
            font-size: 1.25rem;
            color: white;
            margin-left: 1rem;
        }}
        
        .section {{
            margin-bottom: 1.5rem;
        }}
        
        .section-title {{
            font-size: 1rem;
            font-weight: 600;
            color: #374151;
            margin-bottom: 0.75rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .section-title::before {{
            content: '';
            width: 4px;
            height: 1.25rem;
            background: #667eea;
            border-radius: 2px;
        }}
        
        .description-box {{
            background: #f9fafb;
            padding: 1rem;
            border-radius: 0.375rem;
            border-left: 4px solid #667eea;
            white-space: pre-wrap;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.875rem;
            line-height: 1.6;
        }}
        
        .extraction-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1rem;
        }}
        
        .extraction-item {{
            background: #f9fafb;
            padding: 1rem;
            border-radius: 0.375rem;
            border: 1px solid #e5e7eb;
        }}
        
        .extraction-label {{
            font-size: 0.75rem;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }}
        
        .extraction-value {{
            font-size: 0.875rem;
            color: #1f2937;
        }}
        
        .extraction-value ul {{
            list-style: none;
            padding: 0;
        }}
        
        .extraction-value li {{
            padding: 0.25rem 0;
        }}
        
        .judgment-scores {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        
        .score-item {{
            text-align: center;
            padding: 1rem;
            background: #f9fafb;
            border-radius: 0.375rem;
        }}
        
        .score-label {{
            font-size: 0.75rem;
            color: #6b7280;
            margin-bottom: 0.5rem;
        }}
        
        .score-value {{
            font-size: 1.5rem;
            font-weight: 600;
        }}
        
        .issues-list {{
            list-style: none;
            padding: 0;
        }}
        
        .issues-list li {{
            padding: 0.5rem;
            margin-bottom: 0.5rem;
            background: #fef2f2;
            border-left: 3px solid #ef4444;
            border-radius: 0.25rem;
        }}
        
        .suggestions-list {{
            list-style: none;
            padding: 0;
        }}
        
        .suggestions-list li {{
            padding: 0.5rem;
            margin-bottom: 0.5rem;
            background: #f0fdf4;
            border-left: 3px solid #10b981;
            border-radius: 0.25rem;
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.75rem;
            font-weight: 500;
            margin: 0.25rem;
        }}
        
        .badge-success {{
            background: #d1fae5;
            color: #065f46;
        }}
        
        .badge-warning {{
            background: #fef3c7;
            color: #92400e;
        }}
        
        .badge-error {{
            background: #fee2e2;
            color: #991b1b;
        }}
        
        .truncated {{
            color: #6b7280;
            font-style: italic;
        }}
        
        .empty-state {{
            text-align: center;
            padding: 3rem;
            color: #9ca3af;
        }}
        
        .hidden {{
            display: none;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Extraction Review Dashboard</h1>
        <div class="subtitle">Buyer Information Extraction & Quality Assessment</div>
    </div>
    
    <div class="stats-bar">
        <div class="stat-item">
            <div class="stat-label">Total Cards</div>
            <div class="stat-value">{total_cards}</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">With Extraction</div>
            <div class="stat-value">{cards_with_extraction} ({cards_with_extraction/total_cards*100:.1f}%)</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">With Judgment</div>
            <div class="stat-value">{cards_with_judgment} ({cards_with_judgment/total_cards*100:.1f}%)</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">Avg Accuracy</div>
            <div class="stat-value" style="color: {get_score_color(avg_scores['accuracy'])}">{avg_scores['accuracy']:.1f}</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">Avg Completeness</div>
            <div class="stat-value" style="color: {get_score_color(avg_scores['completeness'])}">{avg_scores['completeness']:.1f}</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">Avg Overall</div>
            <div class="stat-value" style="color: {get_score_color(avg_scores['overall'])}">{avg_scores['overall']:.1f}</div>
        </div>
    </div>
    
    <div class="filters">
        <div class="filter-group">
            <label for="gradeFilter">Filter by Grade:</label>
            <select id="gradeFilter" onchange="filterCards()">
                <option value="">All Grades</option>
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
                <option value="D">D</option>
                <option value="F">F</option>
            </select>
        </div>
        <div class="filter-group">
            <label for="hasIssuesFilter">Show Issues:</label>
            <select id="hasIssuesFilter" onchange="filterCards()">
                <option value="">All Cards</option>
                <option value="yes">With Issues</option>
                <option value="no">No Issues</option>
            </select>
        </div>
        <div class="filter-group">
            <label for="hasExtractionFilter">Extraction:</label>
            <select id="hasExtractionFilter" onchange="filterCards()">
                <option value="">All Cards</option>
                <option value="yes">With Extraction</option>
                <option value="no">No Extraction</option>
            </select>
        </div>
    </div>
    
    <div class="cards-container" id="cardsContainer">
"""
    
    # Generate card HTML
    for i, card in enumerate(cards):
        card_id = card.get("id", f"card-{i}")
        card_name = card.get("name", "Untitled Card")
        card_desc = card.get("desc", "")
        
        # Extraction data
        buyer_names = card.get("buyer_names", [])
        buyer_emails = card.get("buyer_emails", [])
        primary_name = card.get("primary_buyer_name")
        primary_email = card.get("primary_buyer_email")
        buyer_confidence = card.get("buyer_confidence", "low")
        buyer_notes = card.get("buyer_notes", "")
        
        # Judgment data
        judgment = card.get("judgment", {})
        grade = judgment.get("grade", "N/A")
        accuracy_score = judgment.get("accuracy_score", 0)
        completeness_score = judgment.get("completeness_score", 0)
        overall_score = judgment.get("overall_score", 0)
        false_positives = judgment.get("false_positives", [])
        false_negatives = judgment.get("false_negatives", [])
        primary_correct = judgment.get("primary_buyer_correct", False)
        issues = judgment.get("issues", [])
        suggestions = judgment.get("suggestions", [])
        judge_notes = judgment.get("judge_notes", "")
        
        has_issues = len(issues) > 0 or len(false_positives) > 0 or len(false_negatives) > 0
        has_extraction = len(buyer_names) > 0 or len(buyer_emails) > 0
        
        # Determine card classes for filtering
        card_classes = ["card"]
        if grade:
            card_classes.append(f"grade-{grade}")
        if has_issues:
            card_classes.append("has-issues")
        else:
            card_classes.append("no-issues")
        if has_extraction:
            card_classes.append("has-extraction")
        else:
            card_classes.append("no-extraction")
        
        html += f"""
        <div class="{' '.join(card_classes)}" data-grade="{grade}" data-has-issues="{str(has_issues).lower()}" data-has-extraction="{str(has_extraction).lower()}">
            <div class="card-header">
                <div>
                    <div class="card-title">{escape_html(card_name)}</div>
                    <div class="card-id">ID: {card_id[:20]}...</div>
                </div>
                {f'<div class="grade-badge" style="background: {get_grade_color(grade)}">{grade}</div>' if grade and grade != "N/A" else ''}
            </div>
            
            <div class="section">
                <div class="section-title">Original Description</div>
                <div class="description-box">{format_text(card_desc)}</div>
            </div>
            
            <div class="section">
                <div class="section-title">Extracted Buyer Information</div>
                <div class="extraction-grid">
                    <div class="extraction-item">
                        <div class="extraction-label">Buyer Names</div>
                        <div class="extraction-value">
                            {f'<ul>{"".join([f"<li>• {escape_html(name)}</li>" for name in buyer_names])}</ul>' if buyer_names else '<em>None found</em>'}
                        </div>
                    </div>
                    <div class="extraction-item">
                        <div class="extraction-label">Buyer Emails</div>
                        <div class="extraction-value">
                            {f'<ul>{"".join([f"<li>• {escape_html(email)}</li>" for email in buyer_emails])}</ul>' if buyer_emails else '<em>None found</em>'}
                        </div>
                    </div>
                    <div class="extraction-item">
                        <div class="extraction-label">Primary Buyer</div>
                        <div class="extraction-value">
                            <strong>Name:</strong> {escape_html(primary_name) if primary_name else '<em>None</em>'}<br>
                            <strong>Email:</strong> {escape_html(primary_email) if primary_email else '<em>None</em>'}
                        </div>
                    </div>
                    <div class="extraction-item">
                        <div class="extraction-label">Extraction Metadata</div>
                        <div class="extraction-value">
                            <span class="badge badge-{'success' if buyer_confidence == 'high' else 'warning' if buyer_confidence == 'medium' else 'error'}">{buyer_confidence}</span><br>
                            {f'<small style="color: #6b7280;">{escape_html(buyer_notes)}</small>' if buyer_notes else ''}
                        </div>
                    </div>
                </div>
            </div>
"""
        
        # Judgment section
        if judgment:
            html += f"""
            <div class="section">
                <div class="section-title">Quality Judgment</div>
                <div class="judgment-scores">
                    <div class="score-item">
                        <div class="score-label">Accuracy</div>
                        <div class="score-value" style="color: {get_score_color(accuracy_score)}">{accuracy_score}</div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Completeness</div>
                        <div class="score-value" style="color: {get_score_color(completeness_score)}">{completeness_score}</div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Overall</div>
                        <div class="score-value" style="color: {get_score_color(overall_score)}">{overall_score}</div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Primary Correct</div>
                        <div class="score-value" style="color: {'#10b981' if primary_correct else '#ef4444'}">{'✓' if primary_correct else '✗'}</div>
                    </div>
                </div>
"""
            
            if false_positives:
                html += f"""
                <div style="margin-bottom: 1rem;">
                    <strong style="color: #ef4444;">False Positives:</strong>
                    <ul class="issues-list">
                        {''.join([f'<li>{escape_html(fp)}</li>' for fp in false_positives])}
                    </ul>
                </div>
"""
            
            if false_negatives:
                html += f"""
                <div style="margin-bottom: 1rem;">
                    <strong style="color: #f59e0b;">False Negatives:</strong>
                    <ul class="issues-list">
                        {''.join([f'<li>{escape_html(fn)}</li>' for fn in false_negatives])}
                    </ul>
                </div>
"""
            
            if issues:
                html += f"""
                <div style="margin-bottom: 1rem;">
                    <strong>Issues Found:</strong>
                    <ul class="issues-list">
                        {''.join([f'<li>{escape_html(issue)}</li>' for issue in issues])}
                    </ul>
                </div>
"""
            
            if suggestions:
                html += f"""
                <div style="margin-bottom: 1rem;">
                    <strong>Suggestions:</strong>
                    <ul class="suggestions-list">
                        {''.join([f'<li>{escape_html(suggestion)}</li>' for suggestion in suggestions])}
                    </ul>
                </div>
"""
            
            if judge_notes:
                html += f"""
                <div style="background: #f9fafb; padding: 1rem; border-radius: 0.375rem; margin-top: 1rem;">
                    <strong>Judge Notes:</strong> {escape_html(judge_notes)}
                </div>
"""
            
            html += """
            </div>
"""
        
        html += """
        </div>
"""
    
    html += """
    </div>
    
    <script>
        function filterCards() {
            const gradeFilter = document.getElementById('gradeFilter').value;
            const issuesFilter = document.getElementById('hasIssuesFilter').value;
            const extractionFilter = document.getElementById('hasExtractionFilter').value;
            const cards = document.querySelectorAll('.card');
            
            cards.forEach(card => {
                let show = true;
                
                if (gradeFilter && card.dataset.grade !== gradeFilter) {
                    show = false;
                }
                
                if (issuesFilter === 'yes' && card.dataset.hasIssues !== 'true') {
                    show = false;
                } else if (issuesFilter === 'no' && card.dataset.hasIssues !== 'false') {
                    show = false;
                }
                
                if (extractionFilter === 'yes' && card.dataset.hasExtraction !== 'true') {
                    show = false;
                } else if (extractionFilter === 'no' && card.dataset.hasExtraction !== 'false') {
                    show = false;
                }
                
                card.style.display = show ? 'block' : 'none';
            });
        }
    </script>
</body>
</html>
"""
    
    return html


def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML review viewer for extraction and judgment results"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="rDbSqbLq - board-archive-2021-0707_buyer_enriched_judged.json",
        help="Input judged JSON file path"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output HTML file path (default: input filename with .html extension)"
    )
    
    args = parser.parse_args()
    
    # Determine output path
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}.html"
    
    logger.info(f"Input file: {input_path}")
    logger.info(f"Output file: {output_path}")
    
    # Load judged JSON
    logger.info("Loading judged JSON file...")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON file: {e}")
        return
    
    cards = data.get("cards", [])
    logger.info(f"Loaded {len(cards)} cards")
    
    # Get statistics from metadata
    stats = None
    if "extraction_metadata" in data and "judgment" in data["extraction_metadata"]:
        stats = data["extraction_metadata"]["judgment"].get("statistics")
    
    # Generate HTML
    logger.info("Generating HTML...")
    html_content = generate_html(cards, stats)
    
    # Save HTML
    logger.info(f"Saving HTML to {output_path}...")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Successfully saved HTML to {output_path}")
        logger.info(f"\nOpen in browser: file://{output_path.absolute()}")
    except Exception as e:
        logger.error(f"Failed to save HTML file: {e}")


if __name__ == "__main__":
    main()

