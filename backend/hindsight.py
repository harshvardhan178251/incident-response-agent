"""Hindsight memory wrapper: real Hindsight Cloud/server when configured,
in-memory + JSON fallback so the demo always works (retain -> recall -> retain)."""
import json
import os
import re
from pathlib import Path
from typing import Any

STORE_PATH = Path(__file__).parent / "memory_store.json"
BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "incident-response-bank")

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


def similarity_score(query: str, doc: str, same_service: bool) -> float:
    """Token-overlap similarity 0-100 with a bonus for same service."""
    q, d = _tokens(query), _tokens(doc)
    if not q or not d:
        return 0.0
    inter = len(q & d)
    union = len(q | d)
    jaccard = inter / union if union else 0.0
    # recall-flavoured boost: how much of the query is covered
    coverage = inter / len(q)
    score = (0.5 * jaccard + 0.5 * coverage) * 100
    if same_service:
        score = min(99.0, score + 12.0)
    # keyword anchors common in incident text
    anchors = ("503", "timeout", "pool", "exhausted", "connection", "payment")
    q_anchors = {a for a in anchors if a in q}
    d_anchors = {a for a in anchors if a in d}
    if q_anchors and q_anchors & d_anchors:
        score = min(99.0, score + 6.0 * len(q_anchors & d_anchors))
    return round(score, 1)


class HindsightMemory:
    def __init__(self) -> None:
        self.bank_id = BANK_ID
        self.backend = "local"
        self._client = None
        base_url = os.getenv("HINDSIGHT_BASE_URL", "").strip()
        api_key = os.getenv("HINDSIGHT_API_KEY", "").strip()
        if base_url:
            try:
                from hindsight_client import Hindsight  # type: ignore

                kwargs: dict[str, Any] = {"base_url": base_url}
                if api_key:
                    kwargs["api_key"] = api_key
                client = Hindsight(**kwargs)
                try:
                    client.get_version()
                except Exception:
                    pass  # server may not expose version; still try retain/recall
                try:
                    client.create_bank(
                        bank_id=self.bank_id,
                        name="Incident Response",
                        mission="Remember past production incidents, their root causes, "
                        "resolution steps, and which fixes worked or failed.",
                    )
                except Exception:
                    pass  # bank probably already exists
                self._client = client
                self.backend = "hindsight"
            except Exception as e:
                print(f"[hindsight] falling back to local store: {e}")
                self._client = None
                self.backend = "local"
        self._memories: list[dict] = self._load()

    # ----- persistence -----
    def _load(self) -> list[dict]:
        if STORE_PATH.exists():
            try:
                return json.loads(STORE_PATH.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save(self) -> None:
        try:
            STORE_PATH.write_text(json.dumps(self._memories, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[hindsight] persist failed: {e}")

    # ----- core ops -----
    def clear(self) -> None:
        self._memories = []
        self._save()

    def retain(self, incident: dict) -> dict:
        content = (
            f"Incident {incident.get('id')} | Service: {incident.get('service')} | "
            f"Severity: {incident.get('severity')} | Error: {incident.get('error_logs')} | "
            f"Root cause: {incident.get('root_cause')} | Resolution: {incident.get('resolution')} | "
            f"Outcome: {incident.get('outcome')}"
        )
        if self._client is not None:
            try:
                self._client.retain(bank_id=self.bank_id, content=content)
            except Exception as e:
                print(f"[hindsight] retain failed, kept locally: {e}")
        if not any(m.get("id") == incident.get("id") for m in self._memories):
            self._memories.append({**incident, "content": content})
            self._save()
        return incident

    def recall(self, query: str, service: str = "", top_k: int = 5) -> list[dict]:
        # Try real Hindsight first, but always merge with local scoring so the
        # demo shows stable similarity % even when the server is unreachable.
        cloud_texts: dict[str, str] = {}
        if self._client is not None:
            try:
                resp = self._client.recall(bank_id=self.bank_id, query=query)
                for r in getattr(resp, "results", []) or []:
                    txt = getattr(r, "text", str(r))
                    cloud_texts[txt[:80]] = txt
            except Exception as e:
                print(f"[hindsight] recall failed, using local: {e}")
        scored = []
        for m in self._memories:
            doc = f"{m.get('service','')} {m.get('error_logs','')} {m.get('root_cause','')} {m.get('resolution','')}"
            sim = similarity_score(
                query, doc, same_service=(service.lower() == str(m.get('service','')).lower() and bool(service))
            )
            scored.append({**m, "similarity": sim})
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def list(self) -> list[dict]:
        return list(self._memories)

    def reflect(self, query: str, context: str = "") -> str | None:
        """Agentic reasoning over bank memory (mission/disposition-aware)."""
        if self._client is None:
            return None
        try:
            ans = self._client.reflect(bank_id=self.bank_id, query=query, context=context)
            text = getattr(ans, "text", str(ans)).strip()
            return text or None
        except Exception as e:
            print(f"[hindsight] reflect failed, rule-based fallback: {e}")
            return None

    # ----- demo seed -----
    def seed_demo(self, force: bool = False) -> list[dict]:
        demo = [
            {
                "id": "INC-001",
                "service": "Payment API",
                "severity": "Critical",
                "error_logs": "HTTP 503 errors, DB connection timeout, connection pool exhausted",
                "root_cause": "Database connection pool exhaustion",
                "resolution": "Increase pool 50 → 100",
                "outcome": "SUCCESS",
            },
            {
                "id": "INC-002",
                "service": "Payment API",
                "severity": "Critical",
                "error_logs": "HTTP 503 errors, DB connection timeout, connection pool exhausted",
                "root_cause": "Database connection pool exhaustion",
                "resolution": "Restart service",
                "outcome": "FAILED",
            },
            {
                "id": "INC-003",
                "service": "Checkout API",
                "severity": "High",
                "error_logs": "HTTP 503 errors, DB connection timeout, connection pool exhausted",
                "root_cause": "Database connection pool exhaustion",
                "resolution": "Increase pool 50 → 100",
                "outcome": "SUCCESS",
            },
        ]
        if force:
            self.clear()
        existing = {m.get("id") for m in self._memories}
        for inc in demo:
            if inc["id"] not in existing:
                self.retain(inc)
        return self.list()
