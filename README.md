Here is a complete `README.md` file tailored for your project folder:

```markdown
# Autonomous Tech Insights Studio

An autonomous, AI-driven technology news curation and publishing platform. Powered by **FastAPI**, **SQLite**, and **Breeth AI**, the platform automatically fetches, evaluates, and synthesizes real-time technology news from multiple RSS feeds against strict editorial standards.

---

## Key Features

* **Autonomous Editorial Agent**: Evaluates news candidates based on technical significance, domain relevance, timeliness, and evidence quality.
* **On-Demand & Scheduled Curation**: Supports both automatic background job execution and instant manual generation via web interface or REST API.
* **Resilient Architecture**: Zero external infrastructure dependencies (runs in a single Python process with SQLite WAL mode and in-process execution locking).
* **Idempotency & Deduplication**: Prevents duplicate post publications across worker ticks using deterministic content hashing and SQLite unique constraints.
* **Persona-Driven Synthesis**: Tailors editorial takeaways for AI Architects, Security Specialists, and Tech Executives.
* **Interactive Dark-Mode Dashboard**: Clean, responsive web studio for initiating news curation and viewing live briefings.

---

## System Architecture


```

┌─────────────────────────────────────────────────────────┐
│                    Web UI (Frontend)                    │
│                  static/index.html                      │
└────────────────────────────┬────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Service                       │
│        (Agents/src/website.py / main.py)                │
└──────┬──────────────────────┬────────────────────┬──────┘
│                      │                    │
▼                      ▼                    ▼
┌──────────────┐    ┌──────────────────┐   ┌──────────────┐
│  SQLite DB   │    │  Worker Pipeline │   │ Breeth AI    │
│ (publisher)  │    │  (worker.py)     │   │ (LLM Engine) │
└──────────────┘    └─────────┬────────┘   └──────────────┘
│
▼
┌──────────────────┐
│ RSS Feeds        │
│ (discovery.py)   │
└──────────────────┘

```

---

## Project Structure


```

.
├── main.py                  # Headless REST API server entry point
├── db.py                    # SQLite database access layer & schema migrations
├── worker.py                # Publishing pipeline & per-agent execution locks
├── schemas.py               # Pydantic validation models
├── discovery.py             # RSS candidate discovery & text scraper
├── config.py                # Environment configuration loader
├── requirements.txt         # Dependencies list
├── run_tests.py             # Automated test suite runner
├── Agents/
│   ├── src/
│   │   ├── website.py       # Integrated FastAPI app serving UI & API
│   │   ├── news_editor.py   # Breeth AI NewsEditorAgent evaluation logic
│   │   ├── validator.py     # Editorial decision contract validator
│   │   ├── models.py        # Internal data models
│   │   └── static/
│   │       └── index.html   # Interactive web dashboard
│   └── tests/
│       └── test_validator.py# Validator unit tests
└── tests/                   # Core system unit & integration tests

```

---

## Getting Started

### Prerequisites

* Python 3.10 or higher
* Valid Breeth AI API key

### 1. Installation

Clone the repository and install the dependencies:

```bash
git clone [https://github.com/your-org/autonomous-tech-studio.git](https://github.com/your-org/autonomous-tech-studio.git)
cd autonomous-tech-studio
pip install -r requirements.txt

```

### 2. Environment Configuration

Create a `.env` file in the root directory:

```env
# Breeth AI Configuration
BREETH_API_KEY=your_breeth_api_key_here
BREETH_API_URL=[https://api.breeth.ai/v1/chat/completions](https://api.breeth.ai/v1/chat/completions)
LLM_MODEL=gpt-4o-mini

# Database & Operational Settings
DATABASE_PATH=publisher.db
MAX_ACTIVE_AGENTS=50
WORKER_INTERVAL_MINUTES=30

# RSS Sources (comma-separated)
RSS_SOURCES=[https://hnrss.org/frontpage,https://www.theverge.com/rss/index.xml,https://feeds.arstechnica.com/arstechnica/index,https://techcrunch.com/feed/](https://hnrss.org/frontpage,https://www.theverge.com/rss/index.xml,https://feeds.arstechnica.com/arstechnica/index,https://techcrunch.com/feed/)

```

---

## Running the Application

### Option A: Web Dashboard & Studio (Recommended)

To launch the full application with the web interface, run:

```bash
python Agents/src/website.py

```

Open your browser and navigate to **`http://127.0.0.1:8000`**.

### Option B: Headless REST API Server

To run the backend API service without the web frontend:

```bash
python main.py

```

---

## REST API Reference

### 1. Initialize Agent

* **Endpoint**: `POST /api/agent/init`
* **Headers**: `Idempotency-Key` (Optional)
* **Request Body**:
```json
{
  "persona": {
    "name": "TechSage",
    "domain": "ai.com"
  }
}

```


* **Response** (HTTP 202):
```json
{
  "agentId": "a1b2c3d4-e5f6-7890-abcd-1234567890ab"
}

```



### 2. Trigger On-Demand Generation

* **Endpoint**: `POST /api/agent/generate`
* **Request Body**:
```json
{
  "agentId": "a1b2c3d4-e5f6-7890-abcd-1234567890ab"
}

```


* **Response** (HTTP 202):
```json
{
  "generationId": "gen_123456",
  "status": "QUEUED"
}

```

### 3. Check Generation Status

* **Endpoint**: `GET /api/agent/generation/{generationId}`
* **Response**:
```json
{
  "generationId": "gen_123456",
  "status": "COMPLETED",
  "postId": "post_789012",
  "error": null
}

```

### 4. Get Agent Feed

* **Endpoint**: `GET /api/agent/feed?agentId={agentId}&limit=10`
* **Response**:
```json
{
  "posts": [
    {
      "id": "post_789012",
      "createdAt": "2026-08-09T12:00:00Z",
      "text": "Critical efficiency breakthrough in LLM inference...",
      "rationale": "High technical relevance and major infrastructure impact.",
      "sources": [
        "[https://feeds.arstechnica.com/article](https://feeds.arstechnica.com/article)"
      ]
    }
  ]
}

```

### 5. Deactivate Agent

* **Endpoint**: `DELETE /api/agent/{agent_id}`
* **Response**:
```json
{
  "ok": true
}

```

---

## Running Tests

To verify database operations, deduplication, worker pipeline, and API endpoints:

```bash
python run_tests.py

```

Or using pytest:

```bash
python -m pytest

```