# Production-Ready Autonomous Publisher Backend — Master Engineering Specification

Act as a **Principal Python Systems Engineer** and build a production-ready, lightweight autonomous publishing backend.

The system must be reliable across restarts, safe against duplicate execution, resilient to LLM/RSS failures, and designed for a **single-process deployment with an in-process APScheduler**.

Do not optimize for unnecessary complexity. The goal is a small, maintainable system that can genuinely be run in production without Redis, Celery, PostgreSQL, or a frontend build system.

---

# 1. Technology Requirements

Use:

* Python 3.11+
* FastAPI
* Uvicorn
* APScheduler
* SQLite3 using Python's standard-library `sqlite3`
* Vanilla HTML/CSS/JavaScript
* `httpx` for HTTP/RSS retrieval if needed
* One supported LLM SDK/provider abstraction
* Python standard-library `logging`
* Pydantic/FastAPI request/response validation

Do **not** use:

* SQLAlchemy
* Django ORM
* Redis
* Celery
* RabbitMQ
* Kafka
* PostgreSQL/MySQL
* React
* Vue
* Angular
* Vite/Webpack/etc.
* Any unnecessary infrastructure service

"Zero-dependency" means **zero external infrastructure dependencies**, not literally zero Python packages. Clearly document the Python packages required in `requirements.txt`.

---

# 2. Deployment Model — IMPORTANT

This architecture uses an **in-process APScheduler**.

Therefore:

> The application MUST run as exactly one scheduler-owning process.

Do NOT support or silently allow:

```text
uvicorn --workers N
gunicorn with multiple application workers
multiple independent instances sharing the same SQLite scheduler
```

Document this explicitly.

If multiple processes are detected or documented deployment configuration would create multiple schedulers, fail clearly rather than pretending the architecture is distributed-safe.

Development reload mode must not accidentally create duplicate scheduler workers.

---

# 3. Project Structure

Use a clean structure similar to:

```text
project/
│
├── main.py
├── db.py
├── worker.py
├── schemas.py
├── discovery.py
├── llm.py
├── config.py
├── requirements.txt
├── README.md
│
├── data/
│   └── publisher.db
│
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
│
└── tests/
    ├── test_db.py
    ├── test_api.py
    ├── test_worker.py
    ├── test_deduplication.py
    └── test_restart_recovery.py
```

Keep the implementation simple.

Do not create unnecessary abstractions merely for the sake of abstraction.

---

# 4. Database Requirements

Use raw `sqlite3`.

Every SQLite connection must configure:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

Use short transactions.

Do not share unsafe global cursors across concurrent requests.

Each database operation should obtain a connection, perform its transaction, commit/rollback appropriately, and close it.

Database state must survive application restarts.

---

# 5. Database Schema

Implement schema versioning/migrations.

At minimum create:

```sql
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
```

And:

```sql
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    rationale TEXT NOT NULL,
    sources TEXT NOT NULL,
    content_hash TEXT NOT NULL,

    FOREIGN KEY (agent_id)
        REFERENCES agents(id)
        ON DELETE CASCADE,

    UNIQUE(agent_id, content_hash)
);
```

Create:

```sql
CREATE INDEX IF NOT EXISTS idx_posts_agent_created
ON posts(agent_id, created_at DESC);
```

`content_hash` must be generated deterministically from normalized published content and/or another clearly documented deduplication key.

The database must prevent duplicate publication even if the worker executes twice.

---

# 6. Database Migration

Do NOT assume:

```sql
CREATE TABLE IF NOT EXISTS
```

is sufficient for future schema changes.

Implement a minimal schema-version mechanism, for example:

```text
schema_version
```

or an equivalent migration mechanism.

Future additions such as `title`, `active`, or `content_hash` must be migratable without destroying existing data.

---

# 7. Agent API

## POST `/api/agent/init`

Request:

```json
{
  "persona": {
    "name": "String",
    "domain": "String"
  }
}
```

Response:

```json
{
  "agentId": "String"
}
```

Requirements:

1. Validate the request with Pydantic.
2. Reject empty strings.
3. Apply sensible maximum lengths.
4. Normalize/validate the domain.
5. Generate a cryptographically strong unique agent ID.
6. Persist the agent in SQLite.
7. Mark the agent active.
8. Register its APScheduler job.
9. Execute its first worker run immediately in the background.
10. Do NOT block the HTTP response waiting for the LLM.
11. Return the generated `agentId`.

The immediate execution must not race with the scheduled job.

---

# 8. Agent Initialization Idempotency

Account for network retries.

A client may send the initialization request twice because the first HTTP response was lost.

Do not accidentally create uncontrolled duplicate agents/jobs.

Implement a documented strategy for idempotency.

If you choose an idempotency-key mechanism, support:

```text
Idempotency-Key
```

and persist enough information to safely replay the result.

If you intentionally choose another mechanism, document why.

---

# 9. Agent Lifecycle

Agents have:

```text
active = 1
```

by default.

Only active agents should have scheduled worker jobs.

On application startup:

1. Initialize/migrate the database.
2. Start APScheduler.
3. Query all active agents.
4. Recreate their scheduled jobs.
5. Do not create duplicate jobs if the startup logic is executed more than once inside the same process.
6. Do not blindly execute thousands of startup jobs simultaneously.

Use controlled startup staggering/jitter where necessary.

---

# 10. APScheduler Configuration

Run each active agent every 30 minutes.

Configure scheduler behavior so that:

* only one instance of a given agent's worker can run at a time
* overlapping executions are prevented
* missed executions are handled intentionally
* jobs do not accumulate indefinitely
* scheduler shutdown is graceful

Use appropriate APScheduler settings such as:

```text
max_instances = 1
coalesce = True
misfire_grace_time = ...
```

Choose sensible values and explain them.

The scheduler timezone should be UTC.

---

# 11. Per-Agent Concurrency Protection

A worker must never have two simultaneous executions for the same agent.

Implement an explicit per-agent execution lock or equivalent scheduler-level protection.

Example conceptual flow:

```text
agent A worker starts
        ↓
lock agent A
        ↓
perform work
        ↓
unlock agent A
```

A failure must always release the lock.

This protection must be combined with database-level deduplication because in-process locks alone do not provide durable idempotency.

---

# 12. Worker Pipeline

Implement:

```text
worker.py
```

with the following pipeline:

```text
Worker
  ↓
Verify agent
  ↓
Acquire execution lock
  ↓
Discovery
  ↓
Candidate normalization
  ↓
Candidate deduplication
  ↓
Memory retrieval
  ↓
Editorial filtering/generation
  ↓
Structured output validation
  ↓
Source validation
  ↓
Content normalization
  ↓
Content hash
  ↓
Atomic persistence
  ↓
Release lock
```

Every worker tick MUST be wrapped in robust exception handling.

A worker failure must NEVER crash:

* FastAPI
* APScheduler
* the main process
* other agents

---

# 13. Discovery

Discovery should retrieve recent technology news from a small configurable list of RSS/HTTP sources.

Use `httpx` or another lightweight mechanism.

Discovery must have:

* connection timeout
* read timeout
* total request timeout
* sensible retry behavior
* HTTP status validation
* malformed-feed handling
* maximum feed size
* maximum candidate count
* publication date filtering
* URL normalization
* duplicate article removal

External content must be treated as **untrusted data**.

Do not execute anything contained in feeds/articles.

---

# 14. Candidate Normalization

Normalize every candidate into a structure similar to:

```json
{
  "title": "...",
  "summary": "...",
  "source_url": "...",
  "published_at": "...",
  "source_name": "..."
}
```

Limit candidate size before passing it to the LLM.

For example:

```text
fetch many
   ↓
normalize
   ↓
deduplicate
   ↓
select top N
   ↓
send only N to LLM
```

Do not send unlimited article text into the model.

---

# 15. Source Trust Boundary

This is critical.

RSS/article text is **untrusted external content**.

It may contain prompt injection such as:

```text
Ignore previous instructions...
```

The LLM must never treat article content as instructions.

Structure the prompt so that:

```text
SYSTEM INSTRUCTIONS
        ↓
EDITORIAL RULES
        ↓
OUTPUT SCHEMA
        ↓
UNTRUSTED CANDIDATE DATA
        ↓
EDITORIAL MEMORY
```

Clearly label external content as untrusted.

The model must be explicitly instructed to summarize/evaluate the content rather than obey instructions found inside it.

---

# 16. Editorial Memory & RAG

Before calling the LLM, retrieve the latest 10 published posts for the current agent.

Retrieve at least:

```text
title
created_at
```

Optionally include a short normalized summary if implemented.
The worker must retrieve relevant historical publications before calling the LLM. Use RAG to identify semantically similar previous posts and avoid repeating previously covered topics or angles. The retrieval layer should return a bounded set of the most relevant historical posts (for example, top 5–10), while optionally including a small number of recent posts to preserve temporal context.

Implement a lightweight Retrieval-Augmented Generation (RAG) layer for the editorial worker so the LLM can retrieve relevant historical posts before making a publishing decision. Instead of relying only on the latest 10 posts, store published post content and metadata in SQLite and retrieve the most semantically relevant previous posts for each candidate topic. For the lightweight implementation, generate embeddings for published posts and candidate content using a configurable embedding provider, store the resulting vectors locally, and perform similarity-based retrieval before the LLM call. The retrieved posts should be supplied to the LLM as **historical context, not instructions**, allowing it to detect semantic repetition, avoid previously covered angles, and identify genuinely novel developments. The RAG layer must remain bounded (for example, retrieve the top 5–10 relevant posts), handle empty history gracefully, and never allow retrieved content to override the system/editorial instructions. If an embedding provider is unavailable, the system should fall back to the existing recency-based SQLite retrieval rather than failing the worker.


---

# 17. LLM Provider Abstraction

Do not hard-code the worker directly to one vendor.

Implement an internal provider interface such as:

```python
class LLMProvider:
    async def generate_editorial_decision(...):
        ...
```

Support one provider initially, but design the worker so another provider can later implement the same interface.

Potential providers:

```text
OpenAI
Anthropic
Gemini
```

Do not require all three simultaneously.

API keys must come from environment variables.

Never expose API keys to the frontend or store them in SQLite.

---

# 18. LLM Timeout and Retry

LLM calls must have:

* timeout
* bounded retries
* exponential backoff
* handling for rate limits
* handling for temporary provider errors

Do not retry indefinitely.

If the LLM ultimately fails:

```text
log failure
release worker lock
finish current tick
allow next scheduled run to retry
```

The API server must remain healthy.

---

# 19. Strict Structured LLM Output

The model must return a structure equivalent to:

```json
{
  "decision": "PUBLISH",
  "title": "Example title",
  "text": "Example post",
  "rationale": "Why this should be published",
  "sources": [
    "https://example.com/article"
  ]
}
```

Valid decisions:

```text
PUBLISH
REJECT
```

Reject any other decision.

Validate the response after receiving it.

Do not trust the LLM merely because the provider claims to support structured output.

Validation must verify:

* JSON structure
* decision enum
* title exists
* text exists
* rationale exists
* sources is an array
* source URLs are valid
* length limits
* required source count
* no empty fields

Malformed output must never reach the database.

---

# 20. Source Integrity

The LLM must NOT invent sources.

The model should only be allowed to select source URLs from the discovered candidate set.

After receiving the LLM decision:

```text
LLM sources
     ↓
compare against discovered URLs
     ↓
reject unknown URLs
```

If a source wasn't discovered by the backend, do not trust it automatically.

---

# 21. Editorial Quality Rules

Before publication enforce configurable constraints such as:

```text
minimum title length
maximum title length
minimum post length
maximum post length
minimum number of sources
maximum number of sources
```

Reject obvious empty/garbage output.

The exact limits should be defined in configuration rather than hard-coded throughout the worker.

---

# 22. Deduplication / Idempotency

This is mandatory.

Before inserting a post:

1. Normalize the generated title/text.
2. Calculate a deterministic content hash.
3. Attempt atomic database insertion.
4. Rely on the SQLite UNIQUE constraint to prevent duplicate publication.

If the same worker runs twice:

```text
first execution → INSERT succeeds
second execution → UNIQUE constraint prevents duplicate
```

Treat duplicate detection as a normal outcome, not an application crash.

---

# 23. Persistence

For a `PUBLISH` decision, atomically persist:

```text
id
agent_id
created_at
title
text
rationale
sources JSON
content_hash
```

The `sources` field must contain valid JSON.

Use a database transaction.

Do not generate the post ID and assume that makes the publication idempotent.

---

# 24. REJECT Behavior

For:

```json
{
  "decision": "REJECT"
}
```

do not create a post.

Log:

```text
timestamp
agent_id
decision
rationale
```

using Python's `logging` module.

Do not use raw `print()` for operational logging.

If rejection history is intentionally non-persistent, explicitly document that.

---

# 25. Feed API

## GET `/api/agent/feed?agentId=...`

This endpoint MUST be strictly passive.

It must:

* query SQLite
* return posts
* never trigger generation
* never call the LLM
* never scrape RSS
* never schedule jobs
* never modify database state

Response:

```json
{
  "posts": [
    {
      "id": "String",
      "createdAt": "ISO8601 UTC String",
      "text": "String",
      "rationale": "String",
      "sources": ["String"]
    }
  ]
}
```

Posts must be newest first.

Use deterministic ordering:

```sql
ORDER BY created_at DESC, id DESC
```

If a valid agent exists but has no posts:

```json
{
  "posts": []
}
```

If the agent does not exist, return an appropriate `404`.

Do not confuse:

```text
valid agent + zero posts
```

with:

```text
nonexistent agent
```

---

# 26. Feed Scalability

Do not allow the feed to return unlimited historical data.

Implement a sensible maximum result size.

If appropriate, support:

```text
limit
cursor/before
```

while preserving the required basic response format.

Document the pagination strategy.

---

# 27. Authentication / Authorization

Do NOT leave the production API completely unauthenticated.

At minimum, design an authentication boundary for:

```text
POST /api/agent/init
GET /api/agent/feed
```

The implementation may use a simple API-key mechanism for this lightweight deployment.

Never expose secrets to the frontend.

The backend must ensure one client cannot freely access another user's private agents merely by guessing an `agentId`.

If the application is intentionally deployed as a private/internal service, document that assumption explicitly.

---

# 28. Rate Limiting / Resource Protection

Protect the system from:

```text
agent creation spam
feed abuse
LLM cost amplification
scheduler explosion
```

Implement reasonable limits for:

* agent creation
* maximum active agents
* immediate worker executions
* discovery candidates
* LLM calls
* generated content size

Do not allow an attacker to create thousands of agents and therefore thousands of scheduler jobs.

If a full distributed rate limiter is inappropriate because Redis is prohibited, use a simple in-process limiter and clearly document that it only protects a single process.

---

# 29. Frontend

Serve:

```text
GET /
```

using FastAPI static files.

The frontend must be plain:

```text
HTML
CSS
Vanilla JavaScript
```

No React/Vue/etc.

Read:

```text
?agentId=xyz
```

from the URL.

Poll:

```text
GET /api/agent/feed?agentId=xyz
```

every 10 seconds.

Display:

* post text
* timestamp
* rationale
* sources

Use a clean dark-mode UI.

Handle:

```text
missing agentId
invalid agent
network failure
empty feed
loading state
```

without crashing.

Do not put authentication secrets into frontend JavaScript.

---

# 30. Time Handling

All server timestamps must be timezone-aware UTC.

Use a single canonical ISO8601 representation.

Scheduler timezone must also be UTC.

Never rely on the machine's local timezone.

---

# 31. Graceful Shutdown

Use FastAPI's:

```python
@asynccontextmanager
async def lifespan(app):
    ...
```

On startup:

```text
initialize database
run migrations
start scheduler
restore active jobs
```

On shutdown:

```text
stop accepting new scheduled executions
shutdown scheduler gracefully
allow currently running work to finish within a timeout
close resources
```

A shutdown must not corrupt the database.

---

# 32. Startup Recovery

On restart:

```text
application starts
      ↓
database initialized
      ↓
active agents loaded
      ↓
jobs reconstructed
```

The application must NOT assume APScheduler persisted its jobs.

The SQLite `agents` table is the source of truth for active agents.

Avoid a startup storm if many agents exist.

Use staggered scheduling or another controlled strategy.

---

# 33. Logging / Observability

Use Python's `logging`.

Every worker execution should include enough information to trace:

```text
agent_id
worker execution
start/end
candidate count
LLM success/failure
decision
publication ID
duplicate detection
errors
duration
```

Do not log:

* API keys
* authentication credentials
* sensitive secrets

Use appropriate log levels:

```text
INFO
WARNING
ERROR
DEBUG
```

---

# 34. Error Isolation

A failure for Agent A must never prevent Agent B from running.

Example:

```text
Agent A
RSS failure
    ↓
log
    ↓
finish A
    ↓
Agent B continues normally
```

Never allow one worker exception to escape into the scheduler in a way that disables the scheduler.

---

# 35. Failure Scenarios That MUST Be Handled

Design and test these explicitly:

### RSS unavailable

Expected:

```text
worker logs failure
no post published
next scheduled run remains intact
```

### RSS returns malformed data

Expected:

```text
invalid candidates discarded
worker continues or safely exits
```

### LLM returns malformed JSON

Expected:

```text
validation failure
no post inserted
```

### LLM times out

Expected:

```text
bounded retry
then failure
no process crash
```

### LLM returns unknown source URL

Expected:

```text
reject publication
```

### Two workers attempt same publication

Expected:

```text
SQLite UNIQUE constraint prevents duplicate
```

### Server restarts

Expected:

```text
active agents restored
scheduled jobs reconstructed
posts remain available
```

### Server crashes during post insertion

Expected:

```text
SQLite transaction either commits or rolls back
```

### Multiple feed requests

Expected:

```text
database remains consistent
```

### Missing agent

Expected:

```text
404
```

### Valid agent with no posts

Expected:

```json
{"posts":[]}
```

---

# 36. Security Requirements

Treat all of the following as untrusted:

```text
HTTP request bodies
query parameters
RSS content
article titles
article summaries
LLM output
source URLs
```

Validate all of them.

Prevent:

* prompt injection
* SQL injection
* arbitrary file access
* secret exposure
* uncontrolled agent creation
* duplicate publication
* unbounded request sizes
* unbounded LLM output
* unbounded RSS payloads

Use parameterized SQLite queries everywhere.

Never concatenate user input into SQL.

---

# 37. Configuration

Put operational settings into configuration/environment variables:

```text
DATABASE_PATH
LLM_PROVIDER
LLM_API_KEY
LLM_MODEL
WORKER_INTERVAL_MINUTES
LLM_TIMEOUT
LLM_MAX_RETRIES
MAX_ACTIVE_AGENTS
MAX_CANDIDATES
MAX_POST_LENGTH
MIN_POST_LENGTH
```

Provide safe defaults where appropriate.

Never hard-code secrets.

---

# 38. Testing Requirements

Write tests for:

### Database

* schema initialization
* migrations
* WAL mode
* foreign keys
* insert/retrieve posts
* duplicate content prevention

### API

* valid agent initialization
* invalid persona
* feed for valid agent
* feed with no posts
* nonexistent agent
* passive feed behavior

### Worker

* successful publish
* rejection
* RSS failure
* malformed LLM response
* invalid source
* LLM timeout
* duplicate publication

### Recovery

Simulate:

```text
start application
create agent
create post
stop application
restart application
```

and verify:

```text
agent still exists
post still exists
scheduled job is recreated
```

---

# 39. Documentation

Create a `README.md` containing:

1. Architecture overview
2. Installation
3. Environment variables
4. Database location
5. Running locally
6. Running in production
7. Explicit single-process scheduler requirement
8. API examples
9. Worker lifecycle
10. LLM configuration
11. Security assumptions
12. Backup recommendations
13. Failure behavior
14. Testing instructions

Clearly state:

> Do not deploy multiple application processes with independent APSchedulers against the same SQLite database.

---

# 40. Backup

SQLite persistence across restarts is required, but also document that persistence does not protect against disk loss.

Provide a lightweight backup recommendation using SQLite's backup functionality rather than copying a live WAL database blindly.

Do not introduce an external database solely for backups.

---

# 41. Code Quality Requirements

The code must be:

* typed where practical
* modular
* readable
* heavily commented only where comments explain non-obvious decisions
* free of dead code
* free of placeholder implementations
* free of fake API responses
* free of silent exception swallowing

Do not write giant functions.

Use explicit names.

Use constants/configuration instead of magic numbers.

---

# 42. Important Implementation Principle

Do NOT simply produce code that satisfies the happy path.

Before writing the implementation, reason through:

```text
concurrency
restart recovery
duplicate execution
database locking
LLM failure
RSS failure
malicious external content
authentication
rate limiting
startup storms
shutdown
schema evolution
```

Then implement the protections.

---

# 43. Required Deliverable

Return the complete implementation for:

```text
main.py
db.py
worker.py
schemas.py
discovery.py
llm.py
config.py
static/index.html
static/style.css
static/app.js
requirements.txt
README.md
tests/
```

The implementation must be internally consistent and runnable.

Do NOT give pseudocode where working code is required.

Do NOT omit imports.

Do NOT invent SDK APIs that do not exist.

If a specific LLM provider requires provider-specific code, isolate it behind the LLM provider interface and clearly document the required environment variables.

---

# 44. Final Acceptance Criteria

The system is considered complete only if all of these are true:

```text
[ ] SQLite uses WAL
[ ] SQLite foreign keys enabled
[ ] SQLite busy timeout configured
[ ] Database survives restart
[ ] Schema migrations exist
[ ] Active agents are restored on startup
[ ] Scheduler runs every 30 minutes
[ ] First run executes asynchronously
[ ] Worker execution cannot overlap for one agent
[ ] Multiple scheduler jobs aren't accidentally created
[ ] Deployment explicitly requires one scheduler process
[ ] LLM output is schema validated
[ ] LLM sources cannot invent arbitrary URLs
[ ] External content is treated as untrusted
[ ] Duplicate posts are prevented at DB level
[ ] Feed is passive
[ ] Feed returns newest first
[ ] Empty feed returns {"posts":[]}
[ ] Missing agent returns 404
[ ] Authentication boundary exists
[ ] Agent creation is rate limited
[ ] Active agent count is bounded
[ ] RSS failures don't crash the app
[ ] LLM failures don't crash the app
[ ] Scheduler failures don't crash FastAPI
[ ] Graceful shutdown exists
[ ] Startup storm is controlled
[ ] API keys aren't exposed
[ ] Frontend contains no secrets
[ ] Frontend handles missing/invalid agentId
[ ] Logging is implemented
[ ] Tests cover restart recovery
[ ] Tests cover duplicate publication
[ ] README documents deployment limitations
```

## Engineering Priority

When trade-offs arise, prioritize in this order:

```text
1. Correctness
2. Data integrity
3. Security
4. Idempotency
5. Failure isolation
6. Restart recovery
7. Observability
8. Maintainability
9. Performance
10. Feature richness
```

Do not add infrastructure merely to achieve scalability that this lightweight architecture does not require.
