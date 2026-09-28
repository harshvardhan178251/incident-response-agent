# Incident Response Agent — 1-hour prototype

Create → AI Investigation → Hindsight Recall → Recommendation → Engineer Resolves → Hindsight Retain.

## Stack
- Frontend: React + Vite (`frontend/`)
- Backend: Python + FastAPI (`backend/`)
- LLM: Pollinations.ai free API (`openai` model, no key; heuristic fallback offline)
- Memory: Hindsight (`hindsight-client`, local JSON fallback so the demo never breaks)

## Run (2 terminals)
```bash
# backend
cd incident-agent/backend
pip install -r requirements.txt
copy ..\.env .env   # Windows (or cp ../.env .env)
uvicorn main:app --reload --port 8010

# frontend
cd incident-agent/frontend
npm install
npm run dev
```
Open http://localhost:5175 (5173/5174 were taken by other projects on this machine; Vite auto-picked 5175)

## Demo script (killer flow)
1. Backend seeds INC-001 (pool increase → SUCCESS), INC-002 (restart → FAILED), INC-003 (pool increase → SUCCESS).
2. Enter: **Payment API / Critical** / `HTTP 503 / DB connection timeout / connection pool exhausted` → **Investigate**.
3. Expect: root cause = pool exhaustion, INC-001 recalled as similar-success, INC-002 as similar-failure, recommendation = increase pool.
4. Click **Resolve & Remember** (fix `Increased pool from 50 → 100`, SUCCESS) → saved to Hindsight as INC-004.
5. Say: "The next time this happens, the agent will recall this incident too." Re-investigate to prove it.

## API
- `GET /api/health` — backend/mode check
- `GET /api/incidents` — what's in memory
- `POST /api/seed` — reset the 3 demo incidents
- `POST /api/investigate` — `{service, severity, error_logs}` → root cause + evidence + similar + recommendation
- `POST /api/resolve` — `{service, severity, error_logs, root_cause, resolution, outcome}` → retained to Hindsight

## Env
See `.env`. The free Pollinations.ai LLM needs no key (set `LLM_OFFLINE=1` to force heuristic).
Without `HINDSIGHT_BASE_URL` it uses `backend/memory_store.json` with the same retain/recall interface — set the URL + key to use real Hindsight Cloud.
