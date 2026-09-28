"""Offline unit tests: pure LLM-layer logic, no network, no Hindsight."""
import llm


def test_redis_pool_classified_as_redis():
    out = llm.heuristic_analysis("Payment API", "HTTP 503\nRedis timeout\nconnection pool exhausted")
    assert out["root_cause"] == "Redis connection pool exhaustion"
    assert out["evidence"] == ["HTTP 503", "Redis timeout", "connection pool exhausted"]


def test_db_pool_classified_as_database():
    out = llm.heuristic_analysis("Payment API", "HTTP 503 errors\nDB connection timeout")
    assert out["root_cause"] == "Database connection pool exhaustion"


def test_redis_alone_is_cache_failure():
    out = llm.heuristic_analysis("Auth API", "JWT validation timeout\nRedis unavailable")
    assert "Redis" in out["root_cause"]


def test_offline_parsing():
    import importlib
    import os
    for val, expected in [("1", True), ("true", True), ("yes", True), ("on", True),
                          ("", False), ("0", False), ("false", False)]:
        os.environ["LLM_OFFLINE"] = val
        importlib.reload(llm)
        assert llm.LLM_OFFLINE is expected, val
    del os.environ["LLM_OFFLINE"]
    importlib.reload(llm)


def test_fingerprint_db_pool():
    fp = llm.classify_fingerprint("Payment API", "Critical",
                                  "HTTP 503\nDB connection timeout\nconnection pool exhausted",
                                  "Database connection pool exhaustion")
    assert fp["error_class"] == "HTTP 5xx"
    assert fp["dependency"] == "Database"
    assert fp["failure_mode"] == "Connection exhaustion"


def test_fingerprint_redis():
    fp = llm.classify_fingerprint("Payment API", "Critical",
                                  "HTTP 503\nRedis timeout", "Redis connection pool exhaustion")
    assert fp["dependency"] == "Redis"


def test_confidence_empty_is_low():
    c = llm.confidence_from_scores([])
    assert c["confidence"] is None


def test_confidence_derived_from_scores():
    mems = [{"scores": {"final": 1.1}}, {"scores": {"final": 0.5}}, {"scores": {"final": 0.4}}]
    c = llm.confidence_from_scores(mems)
    assert 50 <= c["confidence"] <= 95
    assert c["basis"]["n"] == 3


def test_parse_rec_json_passthrough():
    raw = ('{"recommended_action": "Increase pool", "why": ["INC-001 worked"], '
           '"historical_failures": ["restart failed"], "resembles_incident_id": "INC-001", '
           '"followed_memory": true, "reason_for_change": "history supports it", '
           '"alternative": "Restart", "alternative_evidence": "LOW"}')
    p = llm._parse_rec_json(raw)
    assert p["recommended_action"] == "Increase pool"
    assert p["resembles_incident_id"] == "INC-001"
    assert p["followed_memory"] is True
