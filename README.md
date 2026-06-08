# Polymarket Bot

Quant-style Polymarket trading system: multi-source ingestion → feature engine → LightGBM → optional LLM reasoning → quarter-Kelly risk → paper/live execution.

**Default mode: paper trading** (no wallet required).

## Architecture

```
Polymarket (Gamma + Data + CLOB)
        ↓
Feature Engine → LightGBM → Risk Engine → Paper/Live Executor
                      ↑
              Ollama LLM (optional)
```

## Quick start

### 1. Prerequisites

- Docker Desktop
- Python 3.11+ (for local dev without Docker)

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` if needed. Paper mode works out of the box.

### 3. Start infrastructure

```bash
docker compose up -d postgres redis
```

### 4. Install Python deps

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 5. Run migrations

```bash
set PYTHONPATH=.
alembic upgrade head
```

### 6. Run one cycle (test)

```bash
set PYTHONPATH=.
python scripts/run_once.py
```

### 7. Start API + worker

```bash
# Terminal 1
set PYTHONPATH=.
uvicorn backend.app.main:app --reload --port 8000

# Terminal 2
set PYTHONPATH=.
python -m workers.scheduler
```

Or via Docker:

```bash
docker compose up --build
```

### 8. Run backend + frontend together

From the repo root:

```bash
npm run dev
```

That starts the FastAPI backend on `http://localhost:8000` and the Vite frontend on `http://localhost:5173`.

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Status + trading mode |
| `GET /api/markets` | Synced markets |
| `GET /api/markets/{id}/orderbook/latest` | Latest book snapshot |
| `GET /api/signals` | Trade signals |
| `GET /api/portfolio` | Paper positions |

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard at http://localhost:5173

## Enable LLM (optional)

1. Install [Ollama](https://ollama.com)
2. Pull a model that fits your GPU VRAM:
   - **~12 GB** (e.g. RTX 5070): `ollama pull qwen3:8b`
   - **24 GB+**: `ollama pull qwen3:32b`
3. Set `ENABLE_LLM=true` and `OLLAMA_MODEL` in `.env` to match the tag you pulled

## Live trading

Requires Polymarket CLOB V2 credentials:

```env
TRADING_MODE=live
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_FUNDER_ADDRESS=0x...
```

Use `py-clob-client-v2` integration (not wired in v0.1 — paper only).

## Risk defaults

| Parameter | Default |
|-----------|---------|
| Quarter-Kelly | 25% of full Kelly |
| Max position | 5% bankroll |
| Max exposure | 30% bankroll |
| Min edge | 3% |

## Project layout

```
backend/app/     FastAPI, models, services, ML, risk, LLM
workers/         Scheduled jobs (1m / 5m)
ml/              Training scripts
frontend/        React dashboard
alembic/         DB migrations
scripts/         One-off utilities
```

## Next steps

1. Collect resolved markets for real LightGBM training (`python -m ml.train`)
2. Add NewsAPI / Reddit ingestors
3. Weather adapter (NOAA → contract mapping)
4. Backtest framework
5. CLOB V2 live executor
