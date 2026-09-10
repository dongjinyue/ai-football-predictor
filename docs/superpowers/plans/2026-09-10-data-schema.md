# Data Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a time-aware DuckDB foundation for competitions, teams, aliases, matches, and market snapshots without importing data or building prediction models.

**Architecture:** `schema.sql` is the canonical schema. `app/storage.py` owns connection, idempotent initialization, and status inspection. `create_app()` injects a database path and initializes it during FastAPI lifespan so tests use isolated temporary files.

**Tech Stack:** Python, FastAPI, DuckDB, pytest

**Spec:** `docs/superpowers/specs/2026-09-10-ai-football-prediction-design.md`

## Global Constraints

- Preserve prediction-time consistency by storing timezone-aware event, capture, and availability timestamps.
- Do not import real data, scrape websites, implement ratings, or build prediction models.
- Keep generated `.duckdb` files out of Git.
- Work on `feature/data-schema`; do not merge `main`.

---

### Task 1: Idempotent schema initialization

**Files:**
- Create: `backend/app/schema.sql`
- Create: `backend/app/storage.py`
- Create: `backend/tests/test_storage.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `initialize_database(path: Path) -> None`, `get_database_status(path: Path) -> DatabaseStatus`
- Produces tables: `schema_migrations`, `competitions`, `teams`, `team_aliases`, `matches`, `market_snapshots`

- [x] **Step 1: Write tests proving initialization creates all required tables and can run twice**
- [x] **Step 2: Run `python -m pytest tests/test_storage.py -v` and verify failure because `app.storage` is absent**
- [x] **Step 3: Add DuckDB, the canonical SQL schema, and minimal storage functions**
- [x] **Step 4: Run storage tests and verify they pass**

### Task 2: Database status API

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_database_api.py`
- Modify: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `create_app(database_path: Path | None = None) -> FastAPI`
- Produces: `GET /api/database/status` returning engine, readiness, schema version, and table count

- [x] **Step 1: Write an API test using a temporary database path**
- [x] **Step 2: Run the focused API test and verify the route is missing**
- [x] **Step 3: Add application lifespan initialization and the status route**
- [x] **Step 4: Run all backend tests and verify they pass**

### Task 3: Safety rules and handoff

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces: documented `DATABASE_PATH` configuration and safe local database handling

- [x] **Step 1: Document the database path, schema purpose, and verification command**
- [x] **Step 2: Ignore DuckDB files while retaining directory placeholders**
- [x] **Step 3: Run backend and frontend regression checks**
- [x] **Step 4: Inspect Git changes and commit the module branch without merging**
