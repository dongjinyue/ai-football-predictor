# Historical Data Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable Football-Data import pipeline for all supported leagues and the five most recent completed seasons, storing matches and available pre-match markets in DuckDB.

**Architecture:** A source catalog produces immutable file requests, a downloader caches and validates raw CSV files, a pure parser creates normalized records, and a repository imports one file per transaction. A coordinator isolates file failures and records run summaries; FastAPI exposes import, latest-run, and database-summary endpoints.

**Tech Stack:** Python 3.12, FastAPI, DuckDB 1.5.5, HTTPX 0.28.1, pytest 8.4.2

**Spec:** `docs/superpowers/specs/2026-09-10-historical-data-import-design.md`

## Global Constraints

- First source is Football-Data and raw files are stored under `data/raw/football_data/`.
- Default scope is every configured public league and the five most recent completed seasons.
- Import results, 1X2 odds, over/under 2.5 odds, and Asian-handicap odds only when the source provides them.
- Keep the market schema capable of future Sports Lottery win/draw/loss, handicap, correct-score, total-goals, and half-time/full-time SP values.
- Missing odds must not prevent a valid match from being imported.
- One file failure must not roll back already completed files.
- Repeated imports must not create duplicate matches, snapshots, or outcomes.
- A CSV download timestamp is audit metadata only and must never become every historical
  market's availability timestamp. Historical closing odds without a source timestamp use
  `captured_at = available_at = kickoff_at`, `stage = closing`, and
  `time_precision = kickoff_bound`.
- Automated tests must use local fixtures or mocked HTTP and must not require network access.
- Do not implement prediction models, feature engineering, or ticket purchasing.
- Do not commit downloaded data or DuckDB files to Git.

---

## Planned File Structure

| File | Responsibility |
|---|---|
| `backend/app/schema.sql` | Baseline schema version 1 for new and existing databases |
| `backend/app/migrations/*.sql` | Ordered, transactional schema upgrades, starting with version 2 |
| `backend/app/storage.py` | Database initialization and schema readiness |
| `backend/app/imports/models.py` | Immutable source, match, market, and report value objects |
| `backend/app/imports/catalog.py` | Supported Football-Data leagues, seasons, and URL generation |
| `backend/app/imports/downloader.py` | HTTP download, retry, validation, checksum, and raw-file cache |
| `backend/app/imports/parser.py` | Pure CSV-to-domain-record conversion and row validation |
| `backend/app/imports/repository.py` | Transactional and idempotent DuckDB writes and read summaries |
| `backend/app/imports/service.py` | Multi-file orchestration and partial-failure handling |
| `backend/app/imports/router.py` | Import-related FastAPI routes and request validation |
| `backend/app/main.py` | Router wiring and dependency construction |
| `backend/tests/fixtures/football_data_e0_2324.csv` | Small deterministic source fixture |
| `backend/tests/test_import_*.py` | Unit, integration, and API coverage |
| `README.md` | Data source, import behavior, and local commands |

### Task 1: Schema Version 3 and Import Audit Storage

**Files:**
- Create: `backend/app/migrations/003_import_audit.sql`
- Modify: `backend/app/storage.py`
- Modify: `backend/tests/test_storage.py`
- Modify: `backend/tests/test_database_api.py`

**Interfaces:**
- Consumes: `initialize_database(database_path: Path) -> None`
- Produces: schema version `3` and tables `market_outcomes`, `import_runs`, `import_files`

- [ ] **Step 1: Write failing schema tests**

Add assertions that initialization creates nine tables, reports schema version 3, and enforces unique market outcomes:

```python
with duckdb.connect(str(database_path)) as connection:
    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]

assert {"market_outcomes", "import_runs", "import_files"} <= tables
assert version == 3
```

Update the API expectation to `schema_version: 3` and `table_count: 9`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run from `backend/`:

```bash
python -m pytest tests/test_storage.py tests/test_database_api.py -v
```

Expected: FAIL because the three version-3 tables do not exist and the reported version is still 2.

- [ ] **Step 3: Add the version-3 migration**

Create `backend/app/migrations/003_import_audit.sql` with:

```sql
CREATE TABLE IF NOT EXISTS market_outcomes (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL REFERENCES market_snapshots(id),
    outcome_code VARCHAR NOT NULL,
    odds_value DOUBLE NOT NULL CHECK (odds_value > 0),
    normalized_probability DOUBLE CHECK (
        normalized_probability IS NULL OR
        (normalized_probability >= 0 AND normalized_probability <= 1)
    ),
    source_field VARCHAR NOT NULL,
    UNIQUE (snapshot_id, outcome_code)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    status VARCHAR NOT NULL CHECK (
        status IN ('running', 'completed', 'completed_with_errors', 'failed')
    ),
    requested_files INTEGER NOT NULL CHECK (requested_files >= 0),
    completed_files INTEGER NOT NULL DEFAULT 0 CHECK (completed_files >= 0),
    failed_files INTEGER NOT NULL DEFAULT 0 CHECK (failed_files >= 0),
    imported_matches INTEGER NOT NULL DEFAULT 0 CHECK (imported_matches >= 0),
    skipped_rows INTEGER NOT NULL DEFAULT 0 CHECK (skipped_rows >= 0),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    error_summary VARCHAR
);

CREATE TABLE IF NOT EXISTS import_files (
    id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL REFERENCES import_runs(id),
    source VARCHAR NOT NULL,
    competition_code VARCHAR NOT NULL,
    season VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    local_path VARCHAR,
    sha256 VARCHAR,
    status VARCHAR NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    imported_matches INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR,
    UNIQUE (run_id, source_url)
);

INSERT INTO schema_migrations (version) VALUES (3);
```

Add these tables to `REQUIRED_TABLES` in `storage.py`.

- [ ] **Step 4: Run focused and full backend tests**

```bash
python -m pytest tests/test_storage.py tests/test_database_api.py -v
python -m pytest tests -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the schema task**

```bash
git add backend/app/migrations/003_import_audit.sql backend/app/storage.py backend/tests/test_storage.py backend/tests/test_database_api.py
git commit -m "feat: add import audit schema"
```

### Task 2: Import Domain Models and Source Catalog

**Files:**
- Create: `backend/app/imports/__init__.py`
- Create: `backend/app/imports/models.py`
- Create: `backend/app/imports/catalog.py`
- Create: `backend/tests/test_import_catalog.py`

**Interfaces:**
- Produces: `SourceFile`, `MatchRecord`, `MarketRecord`, `ParsedFile`, `FileImportResult`, `ImportRunResult`
- Produces: `build_default_requests(today: date, seasons: int = 5) -> tuple[SourceFile, ...]`

- [ ] **Step 1: Write failing catalog tests**

Test stable URL generation, non-empty all-league coverage, unique requests, and five completed seasons:

```python
requests = build_default_requests(date(2026, 9, 10), seasons=5)

assert requests
assert len({item.url for item in requests}) == len(requests)
assert all(item.source == "football_data" for item in requests)
assert all(item.url.startswith("https://www.football-data.co.uk/mmz4281/") for item in requests)
assert len({item.season for item in requests}) == 5
```

- [ ] **Step 2: Run the test and verify failure**

```bash
python -m pytest tests/test_import_catalog.py -v
```

Expected: FAIL because `app.imports.catalog` does not exist.

- [ ] **Step 3: Implement focused immutable models**

Use frozen dataclasses with explicit fields:

```python
@dataclass(frozen=True)
class SourceFile:
    source: str
    competition_code: str
    competition_name: str
    country_code: str
    season: str
    url: str

@dataclass(frozen=True)
class MarketRecord:
    provider: str
    source: str
    market_type: str
    stage: str
    captured_at: datetime
    available_at: datetime
    time_precision: str
    line: float | None
    outcomes: tuple[tuple[str, float, str], ...]

@dataclass(frozen=True)
class MatchRecord:
    row_number: int
    source_match_id: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int
    away_score: int
    markets: tuple[MarketRecord, ...]
```

Define `ParsedFile`, `FileImportResult`, and `ImportRunResult` with tuple-based errors and integer counters so later tasks do not exchange untyped dictionaries.

- [ ] **Step 4: Implement the configured source catalog**

Define each Football-Data competition once as `(code, name, country_code, season_style)`. Generate URLs as `https://www.football-data.co.uk/mmz4281/{season}/{code}.csv`. For September 2026, completed split-year seasons are `2526` through `2122`; calendar-year competitions use their corresponding last completed calendar years.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/test_import_catalog.py -v
git add backend/app/imports backend/tests/test_import_catalog.py
git commit -m "feat: add Football-Data source catalog"
```

Expected: catalog tests PASS before commit.

### Task 3: Pure Football-Data CSV Parser

**Files:**
- Create: `backend/app/imports/parser.py`
- Create: `backend/tests/fixtures/football_data_e0_2324.csv`
- Create: `backend/tests/test_import_parser.py`

**Interfaces:**
- Consumes: `SourceFile`, `MatchRecord`, `MarketRecord`, `ParsedFile`
- Produces: `parse_football_data_csv(source_file: SourceFile, content: bytes) -> ParsedFile`

- [ ] **Step 1: Add a minimal real-shape fixture and failing parser tests**

The fixture contains two valid matches and one invalid row. Include `Date`, `Time`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`, `HTHG`, `HTAG`, `AvgH`, `AvgD`, `AvgA`, `Avg>2.5`, `Avg<2.5`, `AHh`, `AvgAHH`, and `AvgAHA`.

Assert that the parser:

```python
parsed = parse_football_data_csv(source_file, fixture_bytes)

assert len(parsed.matches) == 2
assert parsed.skipped_rows == 1
assert parsed.matches[0].kickoff_at.tzinfo is not None
assert {market.market_type for market in parsed.matches[0].markets} == {
    "match_result",
    "over_under_2_5",
    "asian_handicap",
}
```

- [ ] **Step 2: Run the parser tests and verify failure**

```bash
python -m pytest tests/test_import_parser.py -v
```

Expected: FAIL because the parser is absent.

- [ ] **Step 3: Implement header, score, date, and odds parsing**

Use `csv.DictReader` and small pure helpers:

```python
def parse_football_data_csv(
    source_file: SourceFile,
    content: bytes,
) -> ParsedFile:
    text = content.decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(text))
    # Validate required headers once, parse each row independently,
    # collect safe row errors, and return immutable records.
```

Treat team names and full-time scores as required. Treat time, half-time scores, and all odds as optional. Use noon UTC when a historical row lacks kickoff time. For Football-Data historical odds, set `captured_at = available_at = kickoff_at`, `stage = "closing"`, and `time_precision = "kickoff_bound"`; never pass the downloader's `downloaded_at` into market availability fields.

Map average odds preferentially; if average columns are absent, use a supported bookmaker triplet only when the complete triplet exists. Never combine outcomes from different providers into one snapshot.

- [ ] **Step 4: Add edge-case tests**

Cover UTF-8 BOM, `dd/mm/yy` and `dd/mm/yyyy`, blank odds, non-positive odds, missing required headers, home/away equality, and invalid scores. Expected behavior is either a file-level `SourceFormatError` for missing headers or a row-level skip with a stable error code.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/test_import_parser.py -v
git add backend/app/imports/parser.py backend/tests/fixtures backend/tests/test_import_parser.py
git commit -m "feat: parse Football-Data match files"
```

### Task 4: Validated Downloader and Raw Cache

**Files:**
- Create: `backend/app/imports/downloader.py`
- Create: `backend/tests/test_import_downloader.py`

**Interfaces:**
- Consumes: `SourceFile`
- Produces: `DownloadedFile(path: Path, content: bytes, sha256: str, downloaded_at: datetime, from_cache: bool)`
- Produces: `FootballDataDownloader(client: httpx.Client, raw_root: Path, max_attempts: int = 3)` with `download(request: SourceFile) -> DownloadedFile`

- [ ] **Step 1: Write mocked HTTP failure and cache tests**

Use `httpx.MockTransport` to assert:

- HTTP 200 CSV writes a deterministic path;
- a second request uses the cached file;
- HTTP 503 retries up to `max_attempts`;
- HTML content, empty content, and missing required CSV headers raise `DownloadValidationError`;
- the returned SHA-256 matches the bytes.

- [ ] **Step 2: Run tests and verify failure**

```bash
python -m pytest tests/test_import_downloader.py -v
```

Expected: FAIL because the downloader is absent.

- [ ] **Step 3: Implement download validation and cache paths**

Store files at:

```python
path = raw_root / request.competition_code / request.season / "matches.csv"
```

Use a 10-second connect timeout and 30-second read timeout. Retry only timeouts, connection errors, HTTP 429, and HTTP 5xx responses. Write to a sibling `.part` path and atomically replace the final path only after validation succeeds.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/test_import_downloader.py -v
git add backend/app/imports/downloader.py backend/tests/test_import_downloader.py
git commit -m "feat: download and cache historical data"
```

### Task 5: Transactional and Idempotent Repository

**Files:**
- Create: `backend/app/imports/repository.py`
- Create: `backend/tests/test_import_repository.py`

**Interfaces:**
- Consumes: `SourceFile`, `ParsedFile`, `FileImportResult`, `ImportRunResult`
- Produces: `ImportRepository(database_path: Path)`
- Produces methods: `start_run`, `start_file`, `import_parsed_file`, `fail_file`, `finish_run`, `latest_run`, `data_summary`

- [ ] **Step 1: Write failing repository integration tests**

Using a temporary DuckDB database, assert that one parsed file creates one competition, two teams, two aliases, one match, all market snapshots and outcomes. Import the same file twice and assert every table count remains unchanged except audit rows for the second run.

Add a forced failure test and assert no partial competition, team, match, or market rows remain from the failed file transaction.

- [ ] **Step 2: Run tests and verify failure**

```bash
python -m pytest tests/test_import_repository.py -v
```

Expected: FAIL because `ImportRepository` is absent.

- [ ] **Step 3: Implement stable identities and normalization**

Use UUIDv5 with a fixed application namespace and source-owned natural keys:

```python
def stable_id(kind: str, *parts: str) -> str:
    key = ":".join((kind, *parts))
    return str(uuid.uuid5(APPLICATION_NAMESPACE, key))
```

Normalize aliases with Unicode NFKC, stripping, case-folding, and collapsing whitespace. A source match identity must include source, competition, season, normalized home team, normalized away team, and UTC kickoff time.

- [ ] **Step 4: Implement one-file transactions and upserts**

Begin a transaction before entity writes, use `INSERT OR IGNORE` for stable immutable entities, replace neither existing source facts nor timestamps silently, commit only after all matches and markets succeed, and roll back on any exception.

Keep audit state updates outside the data transaction so the failed-file reason remains visible after rollback.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/test_import_repository.py -v
git add backend/app/imports/repository.py backend/tests/test_import_repository.py
git commit -m "feat: persist historical imports idempotently"
```

### Task 6: Multi-File Import Coordinator

**Files:**
- Create: `backend/app/imports/service.py`
- Create: `backend/tests/test_import_service.py`

**Interfaces:**
- Consumes: downloader `download`, parser `parse_football_data_csv`, and all repository methods
- Produces: `ImportService.run(requests: tuple[SourceFile, ...]) -> ImportRunResult`

- [ ] **Step 1: Write failing orchestration tests with fakes**

Provide three requests where the middle download raises `DownloadError`. Assert the first and third files import, the run status is `completed_with_errors`, `completed_files == 2`, `failed_files == 1`, and the public error summary contains a stable code but no local absolute path or traceback.

Also test all-success and all-failed status calculation.

- [ ] **Step 2: Run tests and verify failure**

```bash
python -m pytest tests/test_import_service.py -v
```

Expected: FAIL because `ImportService` is absent.

- [ ] **Step 3: Implement sequential failure-isolated orchestration**

Use this control flow:

```python
run_id = repository.start_run(source="football_data", requested_files=len(requests))
for request in requests:
    file_id = repository.start_file(run_id, request)
    try:
        downloaded = downloader.download(request)
        parsed = parse_football_data_csv(request, downloaded.content)
        repository.import_parsed_file(file_id, request, downloaded, parsed)
    except ImportPipelineError as exc:
        repository.fail_file(file_id, exc.code)
return repository.finish_run(run_id)
```

Convert unexpected exceptions to a generic `internal_error` code after server-side logging; do not expose traceback text through API results.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/test_import_service.py -v
git add backend/app/imports/service.py backend/tests/test_import_service.py
git commit -m "feat: coordinate partial historical imports"
```

### Task 7: FastAPI Import and Summary Endpoints

**Files:**
- Create: `backend/app/imports/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_import_api.py`

**Interfaces:**
- Consumes: `build_default_requests`, `ImportService.run`, `ImportRepository.latest_run`, `ImportRepository.data_summary`
- Produces: `create_import_router(service: ImportService, repository: ImportRepository) -> APIRouter`

- [ ] **Step 1: Write failing API tests**

Inject a fake service into `create_app` and test:

```python
response = client.post("/api/data/import", json={"competition_codes": ["E0"], "seasons": ["2324"]})
assert response.status_code == 200
assert response.json()["status"] == "completed"

assert client.get("/api/data/imports/latest").status_code == 200
assert client.get("/api/data/summary").json()["matches"] >= 0
```

Also assert unknown competition codes return HTTP 422, more than five explicitly requested seasons return HTTP 422, and internal errors return a safe HTTP 500 body.

- [ ] **Step 2: Run tests and verify failure**

```bash
python -m pytest tests/test_import_api.py -v
```

Expected: FAIL because the router and dependency injection hooks are absent.

- [ ] **Step 3: Implement typed request and response models**

Define Pydantic models with bounded lists and explicit status fields. An empty request selects the default catalog. A supplied list selects only known codes and exact supported seasons. Return the run ID and counters from `POST /api/data/import`.

- [ ] **Step 4: Wire dependencies without global test state**

Extend the app factory:

```python
def create_app(
    database_path: Path | None = None,
    import_service: ImportService | None = None,
) -> FastAPI:
```

Build the real repository, downloader, and service only when no service is injected. Include the router under `/api/data` while preserving health and database status behavior.

- [ ] **Step 5: Run API and full backend tests, then commit**

```bash
python -m pytest tests/test_import_api.py -v
python -m pytest tests -q
git add backend/app/imports/router.py backend/app/main.py backend/tests/test_import_api.py
git commit -m "feat: expose historical import API"
```

### Task 8: Documentation, Offline Verification, and Controlled Network Smoke Test

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `docs/superpowers/plans/2026-09-10-historical-data-import.md`

**Interfaces:**
- Consumes: completed import pipeline and API
- Produces: reproducible local operating instructions and verification evidence

- [ ] **Step 1: Document source, storage, limits, and endpoints**

Add `FOOTBALL_DATA_RAW_PATH=data/raw/football_data` to `.env.example`. Ensure `.gitignore` excludes raw downloaded CSV files while preserving committed test fixtures. Document attribution, default five-season scope, supported market limitations, and all three API endpoints.

- [ ] **Step 2: Run all offline verification**

From `backend/`:

```bash
python -m pytest tests -q
```

From the repository root:

```bash
npm --prefix frontend test -- --run
npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check
```

Expected: backend and frontend tests PASS, lint exits 0, Vite production build succeeds, and `git diff --check` prints no errors.

- [ ] **Step 3: Run one controlled live source smoke test**

Import one known league-season file into a temporary DuckDB path, not the default project database. Verify at least one match and one market outcome are stored. If the external source is unavailable, record the network failure separately; offline tests remain the release gate.

- [ ] **Step 4: Verify Git safety**

```bash
git status --short
git check-ignore data/raw/football_data/E0/2324/matches.csv
git ls-files data/raw data/processed
```

Expected: downloaded raw files and DuckDB files are ignored, and no runtime data appears in tracked files.

- [ ] **Step 5: Mark plan checkboxes, commit docs, and inspect branch**

```bash
git add README.md .env.example .gitignore docs/superpowers/plans/2026-09-10-historical-data-import.md
git commit -m "docs: explain historical data imports"
git status --short --branch
git log --oneline --decorate -10
```

Expected: branch is `feature/historical-data-import`, worktree is clean, and all implementation commits are ahead of `feature/data-schema` without merging `main`.
