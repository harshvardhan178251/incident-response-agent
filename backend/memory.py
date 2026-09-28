"""Async Hindsight memory layer.

Uses Hindsight's async methods (arecall / aretain), as recommended for
FastAPI event-loop contexts. No local scoring, no invented similarity:
recall results are returned in Hindsight's own ranked order together with
Hindsight's real retrieval scores (final / semantic / keyword).
"""
import os
import re
from dotenv import load_dotenv

load_dotenv()

BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "incident-response-bank-v2")
BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "").strip()
API_KEY = os.getenv("HINDSIGHT_API_KEY", "").strip()

INC_RE = re.compile(r"INC-\d+")


def get_client():
    """Build a Hindsight client, or None when Cloud is not configured."""
    if not BASE_URL:
        return None
    from hindsight_client import Hindsight

    kwargs = {"base_url": BASE_URL}
    if API_KEY:
        kwargs["api_key"] = API_KEY
    return Hindsight(**kwargs)


async def recall_memories(query: str, top_k: int = 5) -> dict:
    """Real Hindsight arecall. Returns ranked memories with real scores.

    Raises on failure so callers can report Hindsight as unavailable
    instead of fabricating results.
    """
    client = get_client()
    if client is None:
        raise RuntimeError("Hindsight is not configured (HINDSIGHT_BASE_URL missing)")
    try:
        resp = await client.arecall(bank_id=BANK_ID, query=query)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    out = []
    for rank, r in enumerate(list(getattr(resp, "results", []) or [])[:top_k], start=1):
        text = getattr(r, "text", str(r)) or ""
        scores = getattr(r, "scores", None)
        if scores is not None and hasattr(scores, "model_dump"):
            scores = scores.model_dump()
        elif scores is not None:
            try:
                scores = dict(scores)
            except Exception:
                scores = {}
        meta = getattr(r, "metadata", None)
        if meta is not None and hasattr(meta, "model_dump"):
            meta = meta.model_dump()
        elif meta is not None and not isinstance(meta, dict):
            try:
                meta = dict(meta)
            except Exception:
                meta = {}
        meta = meta or {}
        tags = getattr(r, "tags", None) or []
        try:
            tags = list(tags)
        except Exception:
            tags = []
        m = INC_RE.search(text or "")
        mid = m.group(0) if m else None
        if not mid and isinstance(meta.get("incident_id"), str):
            mid = meta["incident_id"] if INC_RE.match(meta["incident_id"]) else None
        # Fallback: retain content is "Incident X | Service: S | ... Resolution: R | Outcome: O"
        # when the recall result carries no metadata. Narrative summaries get keyword scan.
        def _field(name: str) -> str | None:
            v = meta.get(name.lower())
            if v:
                return str(v)
            mm = re.search(rf"{name}:\s*([^|]+)", text or "", re.IGNORECASE)
            if mm:
                return mm.group(1).strip()[:200]
            if name == "Service":
                for svc in ("Payment API", "Checkout API", "Authentication API"):
                    if svc.lower() in (text or "").lower():
                        return svc
            if name == "Outcome":
                up = (text or "").upper()
                if "SUCCESS" in up:
                    return "SUCCESS"
                if "FAILED" in up or "FAIL" in up:
                    return "FAILED"
            return None
        out.append({
            "rank": rank,
            "text": text,
            "scores": scores or {},
            "incident_id": mid,
            "occurred_start": str(getattr(r, "occurred_start", "") or ""),
            "metadata": meta,
            "tags": tags,
            "service": _field("Service"),
            "outcome": _field("Outcome"),
            "resolution": _field("Resolution"),
        })
    return {"available": True, "memories": out}


async def retain_memory(content: str, context: str = "", metadata: dict | None = None,
                        tags: list[str] | None = None) -> dict:
    """Real Hindsight aretain. Raises on failure — callers must NOT
    report success when this raises."""
    client = get_client()
    if client is None:
        raise RuntimeError("Hindsight is not configured (HINDSIGHT_BASE_URL missing)")
    try:
        resp = await client.aretain(
            bank_id=BANK_ID, content=content, context=context or None,
            metadata=metadata or None, tags=tags or None,
        )
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    rid = getattr(resp, "id", None) or getattr(resp, "memory_id", None)
    return {"retained": True, "memory_id": str(rid) if rid else None}


async def hindsight_reachable() -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        await client.aget_version()
        return True
    except Exception:
        return False
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
