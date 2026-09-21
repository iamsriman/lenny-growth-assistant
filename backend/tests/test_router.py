import pytest

from app.agent.router import SKILL_ARTIFACT, SKILL_QA, SKILL_SHIP30, route_by_rules


@pytest.mark.parametrize("message,expected", [
    ("What did the guest say about activation?", SKILL_QA),
    ("How do growth loops decay over time?", SKILL_QA),
    ("Explain the difference between funnels and loops", SKILL_QA),
    ("Write a Ship 30 essay about pricing", SKILL_SHIP30),
    ("Turn that into a 1,250 word blog post", SKILL_SHIP30),
    ("Draft a newsletter on product-market fit", SKILL_SHIP30),
    ("Build me an HTML dashboard of the retention metrics", SKILL_ARTIFACT),
    ("Create a markdown checklist for onboarding", SKILL_ARTIFACT),
    ("Make a one-pager comparing the two pricing models", SKILL_ARTIFACT),
])
def test_rule_routing(message, expected):
    decision = route_by_rules(message)
    assert decision is not None
    assert decision.skill == expected


def test_essay_beats_generic_artifact_language():
    decision = route_by_rules("Write a Ship 30 essay and format it as a markdown doc")
    assert decision.skill == SKILL_SHIP30


def test_artifact_kind_inferred():
    assert route_by_rules("Build an HTML landing page").artifact_kind == "html"
    assert route_by_rules("Create a markdown checklist").artifact_kind == "markdown"


def test_ambiguous_message_defers_to_stage_two():
    assert route_by_rules("loops") is None


async def test_forced_skill_overrides_router(seeded_client, session_id):
    resp = await seeded_client.post("/api/chat", json={
        "session_id": session_id,
        "message": "pricing and packaging",
        "skill": "artifact",
        "artifact_kind": "markdown",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["route"]["skill"] == "artifact"
    assert body["route"]["stage"] == "forced"
    assert body["artifact"]["kind"] == "markdown"
