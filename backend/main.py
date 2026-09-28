"""FastAPI backend: Create Incident -> AI Investigation -> Hindsight Recall ->
Recommendation -> Engineer Resolves -> Hindsight Retain."""
import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

from agent import build_recommendation, llm_investigation  # noqa: E402
from hindsight import HindsightMemory  # noqa: E402

app = FastAPI(title="Incident Response Agent (Hindsight + Free LLM)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

memory = HindsightMemory()
memory.seed_demo()


class InvestigateRequest(BaseModel):
    service: str = Field(..., examples=["Payment API"])
    severity: str = Field("Critical", examples=["Critical"])
    error_logs: str = Field(..., examples=["HTTP 503 errors\nDB connection timeout"])


class ResolveRequest(BaseModel):
    service: str
    severity: str = "Critical"
    error_logs: str
    root_cause: str
    resolution: str = Field(..., examples=["Increased pool from 50 → 100"])
    outcome: str = Field("SUCCESS", examples=["SUCCESS", "FAILED"])


@app.get("/api/health")
def health():
    offline = bool(os.getenv("LLM_OFFLINE", "").strip())
    return {
        "status": "ok",
        "memory_backend": memory.backend,
        "bank_id": memory.bank_id,
        "llm": "heuristic" if offline else f"pollinations/{os.getenv('LLM_MODEL', 'openai')}",
        "incidents_stored": len(memory.list()),
        "time": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/incidents")
def list_incidents():
    return {"incidents": memory.list(), "backend": memory.backend}


@app.post("/api/seed")
def seed():
    incidents = memory.seed_demo(force=True)
    return {"seeded": len(incidents), "incidents": incidents}


@app.post("/api/investigate")
def investigate(req: InvestigateRequest):
    analysis = llm_investigation(req.service, req.severity, req.error_logs)
    query = f"{req.service} {req.error_logs} {analysis['root_cause']}"
    similar = memory.recall(query, service=req.service, top_k=5)
    successes = [m for m in similar if str(m.get("outcome", "")).upper() == "SUCCESS"]
    failures = [m for m in similar if str(m.get("outcome", "")).upper() != "SUCCESS"]
    # Hindsight reflect: disposition-aware recommendation grounded in recalled memory.
    # Falls back to the local rule-based synthesis if reflect is unavailable.
    hist = "; ".join(
        f"{m.get('id')}: {m.get('resolution')} -> {m.get('outcome')}" for m in similar
    )
    reflected = memory.reflect(
        query=(
            f"New incident in {req.service} ({req.severity}). Likely root cause: "
            f"{analysis['root_cause']}. Historical outcomes: {hist}. "
            "What fix should the on-call engineer apply, and what should they avoid?"
        ),
        context=f"error logs: {req.error_logs}",
    )
    recommendation = reflected or build_recommendation(analysis["root_cause"], similar)
    return {
        "root_cause": analysis["root_cause"],
        "evidence": analysis["evidence"],
        "similar": similar,
        "worked": successes,
        "failed": failures,
        "recommendation": recommendation,
        "meta": {"llm": analysis.get("llm"), "memory_backend": memory.backend},
    }


@app.post("/api/resolve")
def resolve(req: ResolveRequest):
    existing_ids = [m.get("id", "") for m in memory.list()]
    nums = [int(i.split("-")[1]) for i in existing_ids if i.startswith("INC-") and i.split("-")[1].isdigit()]
    new_id = f"INC-{max(nums, default=0) + 1:03d}"
    incident = {
        "id": new_id,
        "service": req.service,
        "severity": req.severity,
        "error_logs": req.error_logs,
        "root_cause": req.root_cause,
        "resolution": req.resolution,
        "outcome": req.outcome.upper(),
        "resolved_at": datetime.utcnow().isoformat() + "Z",
    }
    memory.retain(incident)
    return {
        "saved": incident,
        "message": f"{new_id} stored in Hindsight. The next similar incident will recall it.",
        "total_incidents": len(memory.list()),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
