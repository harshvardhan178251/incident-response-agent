"""Incident Response Agent — small async API over LLM + Hindsight memory.

    POST /api/incidents                  create an incident
    POST /api/incidents/{id}/investigate LLM analysis + Hindsight recall + LLM recommendation
    POST /api/incidents/{id}/resolve     save resolution via Hindsight retain
    GET  /api/incidents/{id}             retrieve incident state
    GET  /api/health                     backend / memory / llm status
"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

import llm  # noqa: E402
import memory  # noqa: E402
import store  # noqa: E402


SEED_MARKER = Path(__file__).parent / ".hindsight_seeded"


def _seed_content(inc: dict) -> str:
    return (f"Incident {inc['id']} | Service: {inc['service']} | "
            f"Severity: {inc['severity']} | Logs: {inc['error_logs']} | "
            f"Root cause: {(inc.get('investigation') or {}).get('root_cause', '')} | "
            f"Resolution: {(inc.get('resolution') or {}).get('resolution', '')} | "
            f"Outcome: {(inc.get('resolution') or {}).get('outcome', '')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Idempotent first-ever seeding: registry seeds via store; Hindsight retain
    # runs ONCE (marker file), never on every restart.
    incidents = store.list_all()
    if not SEED_MARKER.exists():
        for inc in incidents:
            try:
                await memory.retain_memory(
                    content=_seed_content(inc),
                    metadata={"incident_id": inc["id"], "service": inc["service"],
                              "outcome": (inc.get("resolution") or {}).get("outcome", ""),
                              "resolution": (inc.get("resolution") or {}).get("resolution", "")},
                    tags=[inc["service"], (inc.get("resolution") or {}).get("outcome", "")],
                )
            except Exception as e:
                print(f"[startup] seed retain failed for {inc['id']}: {e}")
                break
        else:
            try:
                SEED_MARKER.write_text("seeded", encoding="utf-8")
            except Exception:
                pass
    yield


app = FastAPI(title="Incident Response Agent (Hindsight + Free LLM)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateIncidentRequest(BaseModel):
    service: str = Field(..., examples=["Payment API"])
    severity: str = Field("Critical", examples=["Critical"])
    error_logs: str = Field(..., examples=["HTTP 503 errors\nDB connection timeout"])


class ResolveRequest(BaseModel):
    resolution: str = Field(..., examples=["Increased pool from 50 to 100"])
    outcome: str = Field("SUCCESS", examples=["SUCCESS", "FAILED"])


CODE_VERSION = "2026-09-29-queryfix+stale-guard-v1"


@app.get("/api/version")
async def version():
    # Guard 2: lets anyone verify the RUNNING server matches disk code.
    return {"version": CODE_VERSION, "bank_id": memory.BANK_ID}


@app.get("/api/health")
async def health():
    try:
        reachable = await asyncio.wait_for(memory.hindsight_reachable(), timeout=8)
    except Exception:
        reachable = False
    return {
        "status": "ok",
        "version": CODE_VERSION,
        "memory_backend": "hindsight" if reachable else "hindsight-unavailable",
        "bank_id": memory.BANK_ID,
        "llm": llm.provider_label(),
        "incidents_stored": len(store.list_all()),
    }


@app.post("/api/incidents", status_code=201)
async def create_incident(req: CreateIncidentRequest):
    return store.create(req.service, req.severity, req.error_logs)


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = store.get(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident {incident_id}")
    return inc


@app.post("/api/incidents/{incident_id}/investigate")
async def investigate(incident_id: str):
    inc = store.get(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident {incident_id}")

    # 1. LLM analyzes the CURRENT incident logs.
    analysis = await llm.analyze_incident(inc["service"], inc["severity"], inc["error_logs"])

    # 1b. Deterministic fingerprint: symptom vs root-cause signals.
    fp = llm.classify_fingerprint(inc["service"], inc["severity"],
                                  inc["error_logs"], analysis["root_cause"])

    # 2. Real Hindsight recall (ranked, with Hindsight's own scores).
    # Short keyword query: long narrative sentences dilute retrieval to zero hits.
    query = (f"{inc['service']} {inc['error_logs']} "
             f"{fp['dependency']} {fp['failure_mode']}").strip()
    try:
        recall = await memory.recall_memories(query, top_k=10)
        memories, memory_available, memory_error = recall["memories"], True, None
        # Guard 1: zero hits -> retry with minimal fingerprint query before giving up.
        if not memories:
            short_q = f"{inc['service']} {fp['dependency']} {fp['failure_mode']}".strip()
            if short_q != query:
                retry = await memory.recall_memories(short_q, top_k=10)
                memories = retry["memories"]
    except Exception as e:
        memories, memory_available, memory_error = [], False, str(e)[:200]
        print(f"[investigate] Hindsight recall failed: {e}")
    for m in memories:
        m["age"] = llm.relative_age(m.get("occurred_start", ""))

    # 2b. Runbook recall (second query, best effort).
    runbooks: list[dict] = []
    if memory_available:
        try:
            rb = await memory.recall_memories(query + " runbook resolution steps", top_k=3)
            rbl = []
            for m in rb["memories"]:
                t = (m.get("text") or "").lower()
                if ((m.get("metadata") or {}).get("type") == "runbook"
                        or "runbook" in t):
                    rbl.append(m)
            runbooks = rbl[:2]
        except Exception as e:
            print(f"[investigate] runbook recall failed: {e}")

    # 3. LLM recommendation from CURRENT incident (service/logs/cause/evidence) + HISTORY.
    rec = await llm.build_recommendation(
        {"service": inc["service"], "severity": inc["severity"],
         "error_logs": inc["error_logs"], "root_cause": analysis["root_cause"],
         "evidence": analysis["evidence"], "dependency": fp["dependency"],
         "failure_mode": fp["failure_mode"]},
        memories,
    )
    conf = llm.confidence_from_scores(memories)

    # 3b. Deterministic splits + impact + timeline (no LLM, just outcomes).
    succ = [m for m in memories if str(m.get("outcome") or "").upper() == "SUCCESS"]
    fail = [m for m in memories if str(m.get("outcome") or "").upper() == "FAILED"]
    st = rec.get("structured") or {}
    impact = {"n": len(memories), "successful": len(succ), "failed": len(fail),
              "rec_changed": bool(st.get("resembles_incident_id")),
              "without_memory": "3 possible fixes",
              "with_memory": "1 recommended fix" if memories else "triage from first principles"}
    timeline = [{"incident_id": m.get("incident_id"), "outcome": m.get("outcome"),
                 "resolution": m.get("resolution"), "age": m.get("age"),
                 "rank": m.get("rank")} for m in memories[:5]]
    multi_cause = len({(m.get("service"), m.get("outcome")) for m in memories}) > 1
    breakdown = _confidence_breakdown(analysis, memories, succ, fail)

    investigation = {
        "root_cause": analysis["root_cause"],
        "evidence": analysis["evidence"],
        "recommendation": rec["recommendation"],
        "recommendation_structured": st,
        "confidence": {**conf, "breakdown": breakdown},
        "fingerprint": fp,
        "successful_fixes": [{"incident_id": m.get("incident_id"), "resolution": m.get("resolution"),
                               "rank": m.get("rank")} for m in succ[:4]],
        "failed_fixes": [{"incident_id": m.get("incident_id"), "resolution": m.get("resolution"),
                           "rank": m.get("rank")} for m in fail[:4]],
        "memory_impact": impact,
        "timeline": timeline,
        "multi_cause_warning": multi_cause,
        "runbooks": runbooks,
        "memories_used": [m["rank"] for m in memories],
    }
    store.update(incident_id, status="investigated", investigation=investigation)
    return {
        "incident_id": incident_id,
        "root_cause": analysis["root_cause"],
        "evidence": analysis["evidence"],
        "memories": memories,
        "memory_available": memory_available,
        "memory_error": memory_error,
        "recommendation": rec["recommendation"],
        "recommendation_structured": st,
        "confidence": {**conf, "breakdown": breakdown},
        "fingerprint": fp,
        "successful_fixes": investigation["successful_fixes"],
        "failed_fixes": investigation["failed_fixes"],
        "memory_impact": impact,
        "timeline": timeline,
        "multi_cause_warning": multi_cause,
        "runbooks": runbooks,
        "meta": {"analysis_llm": analysis.get("llm"),
                 "recommendation_llm": rec.get("llm"),
                 "memory_backend": "hindsight" if memory_available else "hindsight-unavailable"},
    }


def _confidence_breakdown(analysis: dict, memories: list[dict],
                           succ: list[dict], fail: list[dict]) -> dict:
    """4 derived components (sum to overall): evidence overlap 40 / success 30 / fail-avoid 20 / spread 10."""
    if not memories:
        return {}
    ev_toks = set(" ".join(analysis.get("evidence", []) or []).lower().split())
    top_toks = set((memories[0].get("text") or "").lower().split())
    overlap = len(ev_toks & top_toks) / max(len(ev_toks), 1)
    finals = [float((m.get("scores") or {}).get("final", 0) or 0) for m in memories]
    spread = max(0.0, finals[0] - sum(finals[1:]) / max(len(finals) - 1, 1))
    return {
        "current_evidence": round(40 * min(1.0, overlap * 3), 1),
        "successful_history": round(30 * min(1.0, len(succ) / 3), 1),
        "failed_alternatives": round(20 * min(1.0, len(fail) / 2), 1),
        "incident_similarity": round(10 * min(1.0, spread * 5), 1),
    }


@app.post("/api/incidents/{incident_id}/resolve")
async def resolve(incident_id: str, req: ResolveRequest):
    inc = store.get(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident {incident_id}")
    root_cause = (inc.get("investigation") or {}).get("root_cause", "n/a")
    outcome = req.outcome.upper()
    content = (f"Incident {incident_id} | Service: {inc['service']} | "
               f"Severity: {inc['severity']} | Logs: {inc['error_logs']} | "
               f"Root cause: {root_cause} | Resolution: {req.resolution} | "
               f"Outcome: {outcome}")
    try:
        retained = await memory.retain_memory(
            content=content,
            context=f"error logs: {inc['error_logs']}",
            metadata={"incident_id": incident_id, "service": inc["service"], "outcome": outcome,
                      "resolution": req.resolution, "root_cause": root_cause},
            tags=[inc["service"], outcome],
        )
    except Exception as e:
        print(f"[resolve] Hindsight retain failed: {e}")
        # Honest failure — never report success when retain failed.
        raise HTTPException(
            status_code=502,
            detail=("Could not save memory. Hindsight is unavailable. "
                    "Your resolution was NOT marked as saved."),
        )
    store.update(incident_id, status="resolved",
                 resolution={"resolution": req.resolution, "outcome": outcome,
                             "memory_id": retained.get("memory_id")})
    runbook = None
    if outcome == "SUCCESS":
        try:
            inc["_pending_resolution"] = req.resolution
            runbook = llm.build_runbook(inc, outcome)
            try:
                rb_text = await llm.polish_runbook(runbook) if hasattr(llm, "polish_runbook") else None
            except Exception:
                rb_text = None
            content_rb = ("RUNBOOK " + (rb_text or
                f"from {incident_id} | Problem: {runbook['problem']} | "
                f"Symptoms: {'; '.join(runbook['symptoms'])} | Diagnosis: {runbook['diagnosis']} | "
                f"Resolution: {runbook['resolution']} | Verification: {runbook['verification']} | "
                f"Avoid: {'; '.join(runbook['avoid'])}"))[:2000]
            await memory.retain_memory(
                content=content_rb,
                context=f"runbook from {incident_id}",
                metadata={"incident_id": incident_id, "service": inc["service"],
                          "outcome": outcome, "type": "runbook",
                          "resolution": req.resolution},
                tags=[inc["service"], "runbook", outcome],
            )
        except Exception as e:
            print(f"[resolve] runbook retain failed: {e}")
            runbook = runbook or llm.build_runbook(inc, outcome)
    return {
        "incident_id": incident_id,
        "saved": {"resolution": req.resolution, "outcome": outcome,
                  "memory_id": retained.get("memory_id")},
        "runbook": runbook,
        "message": (f"Memory Updated. {incident_id} has been stored in Hindsight. "
                    "This resolution can be recalled during future incident investigations."),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
