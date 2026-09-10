# Project Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a testable frontend and backend foundation without implementing football prediction logic.

**Architecture:** A FastAPI application exposes a versioned health boundary at `/api/health`. A Vite-powered React and TypeScript single-page shell renders the initial dashboard navigation and project status. Root-level data, model, and test directories reserve clear future module boundaries without introducing prediction behavior.

**Tech Stack:** Python, FastAPI, pytest, Vite, React, TypeScript, Tailwind CSS, Vitest, Testing Library

**Spec:** `docs/superpowers/specs/2026-09-10-ai-football-prediction-design.md`

## Global Constraints

- Use top-level `frontend`, `backend`, `data`, `models`, and `tests` directories as required by the latest user instruction.
- Do not implement prediction models, data ingestion, database access, or betting functionality.
- Do not commit secrets, generated model artifacts, raw data, Python caches, virtual environments, or frontend dependencies/build output.
- Work on `feature/project-foundation`; do not modify or merge `main`.

---

### Task 1: FastAPI health boundary

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: no application interfaces
- Produces: `GET /api/health` returning HTTP 200 and `{\"status\": \"ok\", \"service\": \"ai-football-predictor-api\"}`

- [x] **Step 1: Write the failing health endpoint test**
- [x] **Step 2: Run `pytest backend/tests/test_health.py -v` and verify failure because the app is absent**
- [x] **Step 3: Add the minimal FastAPI application and dependency manifest**
- [x] **Step 4: Run the backend test and verify it passes**

### Task 2: Dashboard shell

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/eslint.config.js`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/App.test.tsx`
- Create: `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: browser DOM
- Produces: accessible dashboard shell with primary navigation, development-status card, disclaimer, and responsive Tailwind styling

- [x] **Step 1: Add the frontend test runner configuration and write a failing dashboard behavior test**
- [x] **Step 2: Run the focused Vitest test and verify failure because `App` is absent**
- [x] **Step 3: Add the minimal Dashboard shell and Vite/Tailwind configuration**
- [x] **Step 4: Run frontend unit tests, type checking, linting, and production build**

### Task 3: Repository foundation and verification

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `data/raw/.gitkeep`
- Create: `data/interim/.gitkeep`
- Create: `data/processed/.gitkeep`
- Create: `models/.gitkeep`
- Create: `tests/.gitkeep`

**Interfaces:**
- Consumes: local developer environment variables
- Produces: documented local setup, safe ignore rules, placeholders for future project modules

- [x] **Step 1: Add safe ignore rules, environment variable names, directory placeholders, and setup documentation**
- [x] **Step 2: Run all backend and frontend checks from a clean dependency install**
- [x] **Step 3: Inspect Git status and confirm no secrets, dependencies, caches, data files, or model artifacts are tracked**
- [x] **Step 4: Commit the completed foundation on the feature branch without merging**
