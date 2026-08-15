"""Demo mode scenario tests."""
from __future__ import annotations

import pytest

SCENARIOS_EXPECTED = {
    "high_confidence": "HIGH_CONFIDENCE",
    "low_confidence": "REVIEW_REQUIRED",
    "no_match": "NO_MATCH",
    "multiple_faces": "MULTIPLE_FACES",
    "poor_quality": "POOR_QUALITY",
    "gps_unavailable": "HIGH_CONFIDENCE",
}


def test_scenarios_list(client):
    r = client.get("/api/demo/scenarios")
    assert r.status_code == 200
    scenarios = r.json()
    assert len(scenarios) == 6
    assert {s["id"] for s in scenarios} == set(SCENARIOS_EXPECTED)


def test_unknown_scenario_404(client):
    r = client.post("/api/demo/run", json={"scenario_id": "nope"})
    assert r.status_code == 404


@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS_EXPECTED))
def test_scenario_outcome(client, scenario_id):
    r = client.post("/api/demo/run", json={"scenario_id": scenario_id, "latitude": 28.6139, "longitude": 77.209})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"]
    assert body["preview_image"]
    assert body["identification"]["status"] == SCENARIOS_EXPECTED[scenario_id]


def test_demo_run_into_existing_session(client):
    start = client.post("/api/emergency/start", json={}).json()
    r = client.post("/api/demo/run", json={"scenario_id": "high_confidence", "session_id": start["session_id"]})
    assert r.status_code == 200
    assert r.json()["session_id"] == start["session_id"]
