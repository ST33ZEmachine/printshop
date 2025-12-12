# Scripts

Utility and evaluation scripts for the project.

## Evaluation Scripts

- **eval_queries.py** - Test queries against the agent and compare with BigQuery ground truth
- **eval_extraction_accuracy.py** - Validate extraction pipeline accuracy

## Usage

```bash
# From project root
python scripts/eval_queries.py
python scripts/eval_extraction_accuracy.py
```

## Requirements

These scripts require:
- BigQuery access configured
- `BIGQUERY_PROJECT` environment variable set
- Project dependencies installed (`pip install -r requirements.txt`)
