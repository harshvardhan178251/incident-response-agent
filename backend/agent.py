"""AI investigation: free Pollinations.ai LLM (no API key), heuristic fallback otherwise.

Pollinations exposes an OpenAI-compatible chat endpoint that is free without a key:
    POST https://text.pollinations.ai/openai  {model, messages, ...}
Only stdlib (urllib) is used so no extra dependency is needed.
Set LLM_MODEL to override the default model, or LLM_OFFLINE=1 to force heuristic.
"""
import json
import os
import urllib.request

LLM_MODEL = os.getenv("LLM_MODEL", "openai")
LLM_URL = os.getenv("LLM_URL", "https://text.pollinations.ai/openai")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))


def _free_llm(prompt: str, temperature: float = 0.2, max_tokens: int = 400) -> str | None:
    if os.getenv("LLM_OFFLINE", "").strip() == "1":
        return None
    try:
        payload = json.dumps({
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            LLM_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return (body["choices"][0]["message"]["content"] or "").strip() or None
    except Exception as e:
        print(f"[agent] free LLM unavailable, using heuristic: {e}")
        return None


def heuristic_investigation(service: str, error_logs: str) -> dict:
    text = (error_logs or "").lower()
    if any(k in text for k in ("pool exhausted", "connection pool", "connection timeout", "too many connections")):
        root_cause = "Database connection pool exhaustion"
        evidence = [
            "DB connection timeout in logs",
            "Connection pool exhausted message",
            "HTTP 503 spike correlating with DB errors",
        ]
    elif "503" in text or "service unavailable" in text:
        root_cause = "Upstream service overload / cascading 503s"
        evidence = ["HTTP 503 spike", "Upstream latency in logs", "Error burst window"]
    elif "timeout" in text:
        root_cause = "Downstream dependency timeout"
        evidence = ["Timeout entries in logs", "Dependency latency", "Retriable error pattern"]
    elif "oom" in text or "out of memory" in text:
        root_cause = "Memory exhaustion (OOM)"
        evidence = ["OOM / memory entries", "Restart pattern", "Heap pressure"]
    else:
        root_cause = f"Unclassified failure in {service} — needs triage from error logs"
        evidence = [line.strip() for line in (error_logs or "").splitlines() if line.strip()][:4] or [
            "Error logs attached"
        ]
    return {"root_cause": root_cause, "evidence": evidence, "llm": "heuristic"}


def llm_investigation(service: str, severity: str, error_logs: str) -> dict:
    prompt = (
        "You are an incident-response assistant. Given the service and error logs, "
        'return STRICT JSON: {"root_cause": string, "evidence": [string x3-5]}.\n'
        f"Service: {service}\nSeverity: {severity}\nError/logs:\n{error_logs}"
    )
    raw = _free_llm(prompt, temperature=0.2, max_tokens=400)
    if not raw:
        return heuristic_investigation(service, error_logs)
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start : end + 1] if start != -1 and end != -1 else raw)
        return {
            "root_cause": data.get("root_cause", "Unknown"),
            "evidence": data.get("evidence", [])[:5],
            "llm": f"pollinations/{LLM_MODEL}",
        }
    except Exception as e:
        print(f"[agent] free LLM parse failed, heuristic fallback: {e}")
        out = heuristic_investigation(service, error_logs)
        out["llm_error"] = str(e)[:200]
        return out


def build_recommendation(root_cause: str, similar: list[dict]) -> str:
    """Rule-based synthesis first (demo-stable); free-LLM polish if available."""
    successes = [m for m in similar if str(m.get("outcome", "")).upper() == "SUCCESS"]
    failures = [m for m in similar if str(m.get("outcome", "")).upper() != "SUCCESS"]
    base_parts = []
    if similar:
        base_parts.append(f"I found {len(similar)} similar incident(s) in Hindsight memory.")
    for m in successes[:2]:
        base_parts.append(f"{m.get('id')}: {m.get('resolution')} → SUCCEEDED.")
    for m in failures[:2]:
        base_parts.append(f"{m.get('id')}: {m.get('resolution')} → FAILED.")
    if successes:
        best = successes[0]
        base_parts.append(
            f"Based on current evidence ({root_cause}) and historical outcomes, "
            f"I recommend: {best.get('resolution')} "
            f"(worked in {best.get('id')}; avoid '{failures[0].get('resolution')}' "
            f"which failed in {failures[0].get('id')})." if failures else
            f"Based on current evidence ({root_cause}) and historical outcomes, "
            f"I recommend: {best.get('resolution')} (worked in {best.get('id')})."
        )
    else:
        base_parts.append(
            f"No successful historical fix found. Triage '{root_cause}' from first principles "
            "and retain the outcome so the agent learns."
        )
    base = " ".join(base_parts)

    if not similar:
        return base
    polished = _free_llm(
        "Rewrite this incident recommendation in 3-4 crisp sentences for an on-call engineer. "
        "Keep incident IDs, what worked, what failed, and the concrete action. No preamble.\n\n" + base,
        temperature=0.3,
        max_tokens=250,
    )
    return polished or base
