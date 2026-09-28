"""Async LLM layer: free Pollinations.ai chat API (no key), heuristic fallback.

Both entry points are `async` (httpx) so FastAPI endpoints never block the
event loop. The heuristic fallback is rule-based on the submitted logs, so
changing the logs always changes the answer — even offline.
"""
import json
import os

LLM_MODEL = os.getenv("LLM_MODEL", "openai")
LLM_URL = os.getenv("LLM_URL", "https://text.pollinations.ai/openai")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))
def _offline() -> bool:
    return os.getenv("LLM_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


LLM_OFFLINE = _offline()


async def _chat(prompt: str, temperature: float = 0.2, max_tokens: int = 400) -> str | None:
    if LLM_OFFLINE:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            r = await client.post(LLM_URL, json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
            r.raise_for_status()
            body = r.json()
        text = (body["choices"][0]["message"]["content"] or "").strip()
        return text or None
    except Exception as e:
        print(f"[llm] free LLM unavailable: {e}")
        return None


def heuristic_analysis(service: str, error_logs: str) -> dict:
    text = (error_logs or "").lower()
    has_redis = "redis" in text or "cache" in text
    has_pool = any(k in text for k in ("pool exhausted", "connection pool", "too many connections"))
    if has_redis and has_pool:
        root_cause = "Redis connection pool exhaustion"
    elif has_redis:
        root_cause = "Cache layer unavailable (Redis connection failure)"
    elif has_pool or "connection timeout" in text:
        root_cause = "Database connection pool exhaustion"
    elif "503" in text or "service unavailable" in text:
        root_cause = "Upstream service overload / cascading 503s"
    elif "timeout" in text:
        root_cause = "Downstream dependency timeout"
    elif "oom" in text or "out of memory" in text:
        root_cause = "Memory exhaustion (OOM)"
    else:
        root_cause = f"Unclassified failure in {service} — needs triage from error logs"
    evidence = [ln.strip() for ln in (error_logs or "").splitlines() if ln.strip()][:5] or ["Error logs attached"]
    return {"root_cause": root_cause, "evidence": evidence, "llm": "heuristic"}


async def analyze_incident(service: str, severity: str, error_logs: str) -> dict:
    """LLM analysis of the CURRENT incident logs. Returns root_cause + evidence."""
    prompt = (
        "You are an incident-response assistant. Given the service and error logs, "
        'return STRICT JSON: {"root_cause": string, "evidence": [string x3-5]}. '
        "Base the root cause ONLY on the logs below; derive evidence bullets from them.\n"
        f"Service: {service}\nSeverity: {severity}\nError/logs:\n{error_logs}"
    )
    raw = await _chat(prompt, temperature=0.2, max_tokens=400)
    if not raw:
        return heuristic_analysis(service, error_logs)
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1] if start != -1 and end != -1 else raw)
        return {
            "root_cause": data.get("root_cause", "Unknown"),
            "evidence": (data.get("evidence", []) or [])[:5],
            "llm": f"pollinations/{LLM_MODEL}",
        }
    except Exception as e:
        print(f"[llm] parse failed, heuristic fallback: {e}")
        out = heuristic_analysis(service, error_logs)
        out["llm_error"] = str(e)[:200]
        return out


def heuristic_recommendation(root_cause: str, memories: list[dict]) -> str:
    if not memories:
        return (
            f"No historical memory available. Triage '{root_cause}' from first principles "
            "and retain the outcome so the agent learns."
        )
    lines = [f"Top recalled memory (rank #{memories[0]['rank']}): {memories[0]['text']}"]
    return f"Based on '{root_cause}' and Hindsight recall. " + " ".join(lines)


def _parse_rec_json(raw: str) -> dict | None:
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1] if start != -1 and end != -1 else raw)
        if not isinstance(data, dict):
            return None
        return {
            "recommended_action": str(data.get("recommended_action", "") or "")[:500],
            "why": [str(x)[:300] for x in (data.get("why", []) or [])][:4],
            "historical_failures": [str(x)[:300] for x in (data.get("historical_failures", []) or [])][:3],
            "resembles_incident_id": str(data.get("resembles_incident_id", "") or "")[:20] or None,
            "initial_hypothesis": str(data.get("initial_hypothesis", "") or "")[:300] or None,
            "followed_memory": data.get("followed_memory", True),
            "reason_for_change": str(data.get("reason_for_change", "") or "")[:300] or None,
            "alternative": str(data.get("alternative", "") or "")[:300] or None,
            "alternative_evidence": str(data.get("alternative_evidence", "") or "")[:300] or None,
        }
    except Exception:
        return None


def _parse_rec_text(text: str) -> dict:
    """Fallback: split legacy 'Recommendation:/Why:/Warning:' blob into sections."""
    rec, why, warn = text.strip(), [], []
    try:
        parts = {"rec": "", "why": "", "warn": ""}
        low = text.lower()
        i_why = low.find("why:")
        i_warn = low.find("warning:")
        if i_why != -1:
            parts["rec"] = text[:i_why]
            if i_warn != -1:
                parts["why"] = text[i_why:i_warn]
                parts["warn"] = text[i_warn:]
            else:
                parts["why"] = text[i_why:]
        elif i_warn != -1:
            parts["rec"] = text[:i_warn]
            parts["warn"] = text[i_warn:]
        else:
            parts["rec"] = text
        for k in ("rec", "why", "warn"):
            parts[k] = parts[k].split(":", 1)[-1].strip() if ":" in parts[k] else parts[k].strip()
        rec = parts["rec"] or text.strip()
        why = [s.strip(" -•\n") for s in parts["why"].split("\n") if s.strip()][:3]
        warn = [s.strip(" -•\n") for s in parts["warn"].split("\n") if s.strip()][:3]
    except Exception:
        pass
    return {"recommended_action": rec[:500], "why": why, "historical_failures": warn,
            "resembles_incident_id": None}


def confidence_from_scores(memories: list[dict]) -> dict:
    """Honest retrieval confidence derived ONLY from Hindsight scores (never invented).
    top final vs rest spread -> 50..95. No memories -> Low."""
    if not memories:
        return {"confidence": None, "label": "Low — no history",
                "basis": {"n": 0}}
    finals = [float((m.get("scores") or {}).get("final", 0) or 0) for m in memories]
    top, rest = finals[0], finals[1:] or [0]
    mean_rest = sum(rest) / max(len(rest), 1)
    spread = max(0.0, top - mean_rest)
    conf = int(round(max(50, min(95, 50 + 40 * spread))))
    return {"confidence": conf, "label": f"{conf}% (retrieval)",
            "basis": {"top_final": round(top, 3), "mean_rest": round(mean_rest, 3),
                      "n": len(memories)}}
def classify_fingerprint(service: str, severity: str, error_logs: str, root_cause: str) -> dict:
    """Deterministic incident fingerprint: symptom vs cause signals for recall + UI."""
    text = (error_logs or "").lower()
    if "503" in text or "5xx" in text:
        error_class = "HTTP 5xx"
        symptom = "HTTP 503" if "503" in text else "HTTP 5xx errors"
    elif "timeout" in text:
        error_class = "Timeout"
        symptom = "Dependency timeout"
    elif "oom" in text or "out of memory" in text:
        error_class = "OOM"
        symptom = "Out of memory"
    else:
        error_class = "Unclassified"
        symptom = (error_logs or "").splitlines()[0][:80] if (error_logs or "").strip() else "Unknown symptom"
    rc = (root_cause or "").lower()
    if "redis" in text or "redis" in rc or "cache" in rc:
        dependency, failure_mode = "Redis", "Connection exhaustion" if "pool" in text or "pool" in rc else "Unavailable"
    elif "database" in rc or "db " in text or "pool" in text:
        dependency, failure_mode = "Database", "Connection exhaustion" if "pool" in text else "Timeout"
    elif "upstream" in rc or "overload" in rc:
        dependency, failure_mode = "Upstream", "Overload"
    elif "memory" in rc or "oom" in text:
        dependency, failure_mode = "Self", "Memory exhaustion"
    else:
        dependency, failure_mode = "Unknown", "Unclassified"
    pattern = ("Capacity exhaustion" if "exhaust" in failure_mode.lower() else failure_mode)
    return {"service": service, "severity": severity, "error_class": error_class,
            "symptom": symptom, "dependency": dependency, "failure_mode": failure_mode,
            "pattern": pattern, "root_cause": root_cause}


def relative_age(iso: str) -> str:
    try:
        from datetime import datetime, timezone
        s = (iso or "").replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days} days ago"
        if days < 365:
            return f"{days // 30}mo ago"
        return f"{days // 365}y ago"
    except Exception:
        return ""


async def build_recommendation(current: dict, memories: list[dict]) -> dict:
    """LLM recommendation from CURRENT incident (service/logs/cause/evidence) + HISTORY."""
    root_cause = current.get("root_cause", "Unknown")
    if not memories:
        raw = heuristic_recommendation(root_cause, memories)
        return {"recommendation": raw,
                "structured": {"recommended_action": raw, "why": [], "historical_failures": [],
                               "resembles_incident_id": None},
                "llm": "heuristic (no history)"}
    history = "\n".join(f"[rank #{m['rank']}] {m['text']}" for m in memories)
    cur = (f"Service: {current.get('service', '')}\nSeverity: {current.get('severity', '')}\n"
           f"Logs:\n{current.get('error_logs', '')}\nRoot cause: {root_cause}\n"
           f"Evidence: {'; '.join(current.get('evidence', []) or [])}\n"
           f"Dependency: {current.get('dependency', '')} | Failure mode: {current.get('failure_mode', '')}")
    prompt = (
        "You are an on-call incident-response assistant. Here is the CURRENT incident "
        "and ranked HISTORICAL memories from Hindsight (rank #1 = most relevant).\n\n"
        f"CURRENT:\n{cur}\n\nHISTORY:\n{history}\n\n"
        'Return STRICT JSON with keys: "recommended_action" (string), "why" (2-3 bullets citing '
        'current evidence + past incident IDs/outcomes), "historical_failures" (1-2 bullets on what '
        'failed and must be avoided), "resembles_incident_id" ("INC-xxx or null"), '
        '"followed_memory" (true if history supports the action, false if current evidence overrides history), '
        '"reason_for_change" (one sentence: why history was followed or overridden), '
        '"alternative" (the main fix you did NOT pick), "alternative_evidence" ("HIGH/LOW" + one clause '
        'citing the IDs that support or condemn it). '
        "Ground every claim in CURRENT + HISTORY. If the top memory's dependency differs from the "
        "current dependency, set followed_memory=false and refuse to copy the old fix. No preamble."
    )
    text = await _chat(prompt, temperature=0.3, max_tokens=500)
    if not text:
        raw = heuristic_recommendation(root_cause, memories)
        return {"recommendation": raw,
                "structured": _heuristic_structured(current, memories, raw),
                "llm": "heuristic (LLM unavailable)"}
    parsed = _parse_rec_json(text)
    if parsed is None:
        base = _parse_rec_text(text)
        parsed = {**base, **_heuristic_decision(current, memories)}
    raw = (f"Recommended: {parsed['recommended_action']}\nWhy: {'; '.join(parsed['why'])}\n"
           f"Historical failures: {'; '.join(parsed['historical_failures'])}")
    return {"recommendation": raw, "structured": parsed, "llm": f"pollinations/{LLM_MODEL}"}


def _heuristic_decision(current: dict, memories: list[dict]) -> dict:
    """Deterministic followed/override + counterfactual from outcomes (no LLM)."""
    cur_dep = (current.get("dependency") or "").lower()
    top_dep = ""
    for m in memories[:3]:
        t = (m.get("text") or "").lower()
        if "redis" in t:
            top_dep = "redis"
            break
        if "database" in t or "db " in t or "pool" in t:
            top_dep = "database"
            break
    followed = not (cur_dep and top_dep and cur_dep not in top_dep and top_dep not in cur_dep)
    fails = [m for m in memories if str(m.get("outcome") or "").upper() == "FAILED"]
    succ = [m for m in memories if str(m.get("outcome") or "").upper() == "SUCCESS"]
    alt = "Restart service"
    alt_ev = "LOW — failed before" if fails else "unknown — no failures on record"
    if fails:
        alt_ev = f"LOW — failed in {fails[0].get('incident_id') or 'a past incident'}"
    reason = ("Historical outcomes support this over alternatives."
              if followed else
              "Current dependency differs from top memories — old fix not reused.")
    if succ:
        reason += f" {len(succ)} similar success(es) on record."
    return {"followed_memory": followed, "reason_for_change": reason[:300],
            "alternative": alt, "alternative_evidence": alt_ev[:200],
            "initial_hypothesis": current.get("root_cause", "Unknown")}


def _heuristic_structured(current: dict, memories: list[dict], raw: str) -> dict:
    base = {"recommended_action": raw[:500], "why": [], "historical_failures": [],
            "resembles_incident_id": (memories[0].get("incident_id") if memories else None)}
    return {**base, **_heuristic_decision(current, memories)}


async def polish_runbook(runbook: dict) -> str | None:
    """One optional LLM pass to tighten the auto-runbook; None -> use template."""
    prompt = ("Condense this incident into a 6-line runbook (Problem/Symptoms/Diagnosis/"
              "Resolution/Verification/Avoid), concrete and terse. No preamble.\n"
              + json.dumps(runbook)[:1500])
    return await _chat(prompt, temperature=0.2, max_tokens=300)


def build_runbook(incident: dict, outcome: str) -> dict:
    """Template runbook from resolved incident fields (LLM polishes when available)."""
    logs = [ln.strip() for ln in (incident.get("error_logs") or "").splitlines() if ln.strip()][:5]
    return {
        "problem": (incident.get("investigation") or {}).get("root_cause", "See incident"),
        "symptoms": logs or ["See error logs"],
        "diagnosis": f"Check {incident.get('service')} dependency health and capacity metrics.",
        "resolution": incident.get("_pending_resolution", ""),
        "verification": "Confirm error rate returns to baseline and stays flat.",
        "avoid": ["Restarting the service alone without addressing capacity."],
        "source_incident": incident.get("id"), "outcome": outcome,
    }
