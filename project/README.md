# Autonomous Publisher Backend

A lightweight autonomous publishing backend with a FastAPI API, SQLite storage, APScheduler jobs, RSS discovery, and an LLM-backed worker.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export API_KEY=dev-secret
uvicorn main:app --reload --workers 1
```

## Testing

```bash
pytest -q
```
