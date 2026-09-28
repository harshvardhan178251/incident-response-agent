# Incident Response Agent

Create → AI Investigation → Hindsight Recall → Recommendation → Engineer Resolves → Hindsight Retain.

The agent remembers past incidents, root causes, resolution steps, and which
runbooks worked — then proves the memory changed its answer.

## Stack
- Frontend: React + Vite (`frontend/`)
- Backend: Python + FastAPI (`backend/`)
- LLM: Pollinations.ai free API (`openai` model, no key; heuristic fallback offline)
- Memory: Hindsight Cloud (`hindsight-client`, bank `agent`). Retain failures
  surface as errors — the app never fakes a save.

## Run (2 terminals)
```powershell
# backend (needs Python 3.14) — safe start kills stale :8010 holders,
# starts fresh, and verifies the running version matches disk code
cd incident-agent/backend
pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File start-backend.ps1

# frontend
cd incident-agent/frontend
npm install
npm run dev
```
Copy `backend/.env.example` to `backend/.env` and fill in `HINDSIGHT_API_KEY`
(never commit the live key; `backend/.env` is git-ignored). Open the Vite URL
from the terminal (port auto-picks if 5173 is busy; proxy `/api` → `http://localhost:8010`).

## Demo script (learning loop)
1. Create incident: **Payment API / Critical** / `HTTP 503 / Redis timeout / connection pool exhausted` → **Investigate**.
2. Expect: fingerprint (Redis / Connection exhaustion), root cause + evidence from
   those logs, Hindsight-ranked memories with real retrieval scores, structured
   recommendation (action / why / historical failures / confidence breakdown),
   timeline + memory-impact panels.
3. Enter actual fix + SUCCESS → **Resolve & Remember** → “Memory Updated … stored
   in Hindsight” (+ auto-generated runbook retained).
4. **Create another similar incident** with the same symptoms → Investigate → the
   just-resolved incident appears in recall with Service/Resolution/Outcome, and
   the recommendation cites it (`resembles INC-xxx`).

## API
- `GET /api/health` — status + `version` + memory/llm state
  (`hindsight` vs `hindsight-unavailable`)
- `GET /api/version` — running code version (stale-server guard)
- `POST /api/incidents` — `{service, severity, error_logs}` → `{id, ...}`
- `GET /api/incidents/{id}` — incident state
- `POST /api/incidents/{id}/investigate` — LLM analysis + fingerprint +
  Hindsight recall (short keyword query + minimal-query fallback) + structured
  recommendation (decision, counterfactual) + confidence breakdown + timeline +
  memory impact + runbooks
- `POST /api/incidents/{id}/resolve` — `{resolution, outcome}` → retained to
  Hindsight (502 if unavailable) + auto-runbook retained on SUCCESS

## Env
See `backend/.env.example`. `LLM_OFFLINE=1|true|yes` forces the heuristic.
`HINDSIGHT_BANK_ID` selects the memory bank (default `agent`).
