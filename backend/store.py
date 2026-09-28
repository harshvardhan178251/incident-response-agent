"""Local incident registry (CRUD state). The memory layer is Hindsight;
this file only tracks incident records, IDs and workflow status."""
import json
from datetime import datetime, timezone
from pathlib import Path

STORE_PATH = Path(__file__).parent / "incidents.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list[dict]:
    if STORE_PATH.exists():
        try:
            data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _save(incidents: list[dict]) -> None:
    STORE_PATH.write_text(json.dumps(incidents, indent=2), encoding="utf-8")


def _seed() -> list[dict]:
    """Seed from the legacy memory_store.json if present, else the 3 canonical demos."""
    legacy = Path(__file__).parent / "memory_store.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                seeded = []
                for m in data:
                    seeded.append({
                        "id": m.get("id"), "service": m.get("service"),
                        "severity": m.get("severity", "Critical"),
                        "error_logs": m.get("error_logs", ""),
                        "status": "resolved" if m.get("outcome") else "open",
                        "created_at": m.get("resolved_at", _now()),
                        "investigation": {"root_cause": m.get("root_cause", ""),
                                          "evidence": [], "recommendation": "",
                                          "memories_used": []} if m.get("root_cause") else None,
                        "resolution": {"resolution": m.get("resolution", ""),
                                       "outcome": m.get("outcome", ""),
                                       "memory_id": None} if m.get("outcome") else None,
                    })
                _save(seeded)
                return seeded
        except Exception:
            pass
    demo = [
        {"service": "Payment API", "severity": "Critical",
         "error_logs": "HTTP 503 errors, DB connection timeout, connection pool exhausted",
         "root_cause": "Database connection pool exhaustion",
         "resolution": "Increase pool 50 → 100", "outcome": "SUCCESS"},
        {"service": "Payment API", "severity": "Critical",
         "error_logs": "HTTP 503 errors, DB connection timeout, connection pool exhausted",
         "root_cause": "Database connection pool exhaustion",
         "resolution": "Restart service", "outcome": "FAILED"},
        {"service": "Checkout API", "severity": "High",
         "error_logs": "HTTP 503 errors, DB connection timeout, connection pool exhausted",
         "root_cause": "Database connection pool exhaustion",
         "resolution": "Increase pool 50 → 100", "outcome": "SUCCESS"},
    ]
    seeded = []
    for i, d in enumerate(demo, start=1):
        seeded.append({
            "id": f"INC-{i:03d}", "service": d["service"], "severity": d["severity"],
            "error_logs": d["error_logs"], "status": "resolved", "created_at": _now(),
            "investigation": {"root_cause": d["root_cause"], "evidence": [],
                              "recommendation": "", "memories_used": []},
            "resolution": {"resolution": d["resolution"], "outcome": d["outcome"],
                           "memory_id": None},
        })
    _save(seeded)
    return seeded


def list_all() -> list[dict]:
    incidents = _load()
    if not incidents:
        incidents = _seed()
    return incidents


def get(incident_id: str) -> dict | None:
    for inc in list_all():
        if inc.get("id") == incident_id:
            return inc
    return None


def create(service: str, severity: str, error_logs: str) -> dict:
    incidents = list_all()
    nums = [int(i["id"].split("-")[1]) for i in incidents
            if str(i.get("id", "")).startswith("INC-") and str(i["id"]).split("-")[1].isdigit()]
    new_id = f"INC-{max(nums, default=0) + 1:03d}"
    inc = {"id": new_id, "service": service, "severity": severity,
           "error_logs": error_logs, "status": "open", "created_at": _now(),
           "investigation": None, "resolution": None}
    incidents.append(inc)
    _save(incidents)
    return inc


def update(incident_id: str, **fields) -> dict | None:
    incidents = list_all()
    for inc in incidents:
        if inc.get("id") == incident_id:
            inc.update(fields)
            _save(incidents)
            return inc
    return None
