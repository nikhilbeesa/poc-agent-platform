"""
Tests for the feasibility assessment, the shared system profile and the required scale/security
discovery questions. Runs with no API key (mock mode) plus a scripted fake client for live mode.

    python3 src/test_feasibility_and_profile.py
"""
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
logging.disable(logging.CRITICAL)

import system_profile as sp  # noqa: E402
from agents import feasibility as feas  # noqa: E402
from context import AgentRole, ProjectContext  # noqa: E402
from discovery import run_discovery, _NFR_QUESTIONS  # noqa: E402
from export import export_all_artefacts  # noqa: E402
from orchestrator import AGENT_PIPELINE, run_full_pipeline  # noqa: E402

IDEA = "A marketplace app where people can book trusted home cleaners for one-off or recurring visits, with online payment and reviews"
ANSWERS = {
    "nfr_users_12m": "50,000–500,000",
    "nfr_peak_concurrent": "500–5,000",
    "nfr_availability": "99.9% (only minutes of downtime a month)",
    "nfr_data_sensitivity": "Personal details (names, emails, phone numbers); Payment / card data",
    "nfr_geography": "Several countries",
}


def answered_context(answers=ANSWERS, idea=IDEA, fill="Not sure yet"):
    ctx = run_discovery(ProjectContext(), idea)
    for q in ctx.discovery_questions:
        if q.id in answers:
            ctx.add_answer(q.id, answers[q.id])
        elif q.status.value == "pending":
            ctx.add_answer(q.id, (q.options[0] if q.options and fill is None else fill))
    return ctx


def test_required_questions_always_asked():
    ctx = run_discovery(ProjectContext(), IDEA)
    ids = [q.id for q in ctx.discovery_questions]
    for qid, *_ in _NFR_QUESTIONS:
        assert qid in ids, f"required question {qid} missing"
    assert ids[-1] == "additional_information", "the open-ended question must stay last"
    by_id = {q.id: q for q in ctx.discovery_questions}
    assert by_id["nfr_data_sensitivity"].multi_select is True
    assert len(by_id["nfr_users_12m"].options) >= 4


def test_profile_uses_stated_numbers_and_flags_assumptions():
    stated = sp.build_baseline_profile(answered_context())
    planning = stated["scale"]["planning"]
    assert planning["users_12m"] == 500_000 and planning["peak"] == 5_000 and planning["design_peak"] == 10_000
    assert stated["availability"]["uptime_target"] == "99.9%" and stated["availability"]["basis"] == sp.STATED
    assert stated["open_questions"] == []
    # nothing answered -> everything that is a planning default must say so
    bare = sp.build_baseline_profile(ProjectContext(business_idea_raw="x"))
    assert bare["open_questions"], "unanswered inputs must be reported as open questions"
    bases = {r["parameter"]: r["basis"] for r in bare["scale"]["rows"]}
    assert bases["Registered users — first 12 months"] == sp.ASSUMED
    assert bases["Availability target"] == sp.ASSUMED
    assert all(r["status"] == sp.DERIVED_ASSUMED for r in bare["performance_requirements"])
    assert all(r["status"] == sp.DERIVED_STATED for r in stated["performance_requirements"])


def test_open_ended_answer_plans_with_headroom():
    p = sp.build_baseline_profile(answered_context({**ANSWERS, "nfr_users_12m": "500,000+"}))
    assert p["scale"]["planning"]["users_12m"] == 1_000_000
    assert any("open-ended" in a for a in p["scale"]["assumptions"])


def test_requirement_ids_unique_and_complete():
    p = sp.build_baseline_profile(answered_context())
    for key, prefix in (("system_requirements", "SYS"), ("security_requirements", "SEC"),
                        ("performance_requirements", "PERF"), ("scalability_requirements", "SCL")):
        ids = [r["id"] for r in p[key]]
        assert ids and len(ids) == len(set(ids)) and all(i.startswith(prefix + "-") for i in ids), key
    cats = " ".join(r["category"] for r in p["security_requirements"]).lower()
    for needed in ("authentication", "encryption in transit", "audit logging", "payment security", "privacy"):
        assert needed in cats, f"security baseline missing {needed}"


def test_sensitive_data_adds_specific_controls():
    health = sp.build_baseline_profile(answered_context({**ANSWERS, "nfr_data_sensitivity": "Health or medical data"}))
    assert any(r["category"] == "Health data" for r in health["security_requirements"])
    none = sp.build_baseline_profile(answered_context({**ANSWERS, "nfr_data_sensitivity": "Nothing sensitive"}, idea="A tool to track my books"))
    assert not any(r["category"] in ("Health data", "Children's data", "Payment security") for r in none["security_requirements"])


def test_verdict_cannot_be_more_optimistic_than_the_flaws():
    base = {"flaws": [{"severity": "Critical", "flaw": "a"}, {"severity": "Critical", "flaw": "b"}], "feasibility": {}}
    assert feas.finalize(dict(base), llm_verdict="GO")["verdict"] == "RETHINK"
    one = {"flaws": [{"severity": "Critical", "flaw": "a"}], "feasibility": {}}
    assert feas.finalize(one, llm_verdict="GO")["verdict"] == "GO WITH CHANGES"
    minor = {"flaws": [{"severity": "Minor", "flaw": "a"}], "feasibility": {k: {"rating": "High", "assessment": "ok"} for k, _ in feas.DIMENSIONS}}
    assert feas.finalize(dict(minor))["verdict"] == "GO"
    # the model may be MORE cautious...
    assert feas.finalize(dict(minor), llm_verdict="GO WITH CHANGES")["verdict"] == "GO WITH CHANGES"
    # ...but cannot reach RETHINK without a critical flaw backing it
    assert feas.finalize(dict(minor), llm_verdict="RETHINK")["verdict"] == "GO WITH CHANGES"
    # flaws are sorted worst-first and numbered top-down
    mixed = feas.finalize({"flaws": [{"severity": "Minor", "flaw": "m"}, {"severity": "Critical", "flaw": "c"}], "feasibility": {}})
    assert [f["severity"] for f in mixed["flaws"]] == ["Critical", "Minor"] and mixed["flaws"][0]["id"] == "FLAW-01"


def test_mock_assessment_is_honest_and_catches_obvious_flaws():
    ctx = answered_context({**ANSWERS, "nfr_users_12m": "500,000+"})
    for q in ctx.discovery_questions:          # a solo founder planning for huge scale
        if "team" in f"{q.category} {q.text}".lower():
            q.answer = "Solo founder"
    out = feas._mock(ctx)
    assert "CATEGORIES" in out["evidence_note"], "mock mode must not pretend to have researched competitors"
    assert all(c["pricing_model"].startswith(("Not researched", "Free")) for c in out["competitors"])
    assert out["verdict"] in feas.VERDICTS and out["counts"]["critical"] + out["counts"]["major"] >= 1
    assert any(f["area"] == "Cold start" for f in out["flaws"]), "two-sided marketplace must raise the cold-start flaw"


def test_full_pipeline_and_export_share_the_same_numbers():
    ctx = answered_context()
    run_full_pipeline(ctx)
    assert [c.agent for c in ctx.agent_contributions][0] == AgentRole.FEASIBILITY_ASSESSMENT
    assert len(ctx.agent_contributions) == len(AGENT_PIPELINE) == 6
    assert ctx.system_profile, "profile must be built once and stored"
    ctx = export_all_artefacts(ctx)
    docs = {a.type: a.content_markdown for a in ctx.artefacts}
    assert list(docs)[0] == "feasibility_assessment" and len(docs) == 6

    fd = docs["feasibility_assessment"]
    for section in ("## 1. Verdict", "## 5. Competitive Analysis", "## 6. Competitive Advantage & Differentiators",
                    "## 7. Feasibility Assessment", "## 8. Flaws & Weaknesses in the Current Idea"):
        assert section in fd, section

    brd, prd = docs["business_requirements"], docs["prd"]
    for heading in ("### Expected scale and usage", "### Performance requirements", "### Scalability requirements"):
        assert heading in brd and heading in prd, heading
    assert "### Security requirements" in prd and "### Security requirements (SEC)" in brd
    assert "### System requirements" in prd and "### System requirements" in brd
    # identical IDs and identical numbers in both documents
    for pat in (r"PERF-\d{3}", r"SCL-\d{3}", r"SEC-\d{3}", r"SYS-\d{3}"):
        assert set(re.findall(pat, brd)) == set(re.findall(pat, prd)), pat
    for doc in (brd, prd):
        assert "10,000 concurrent users" in doc and "99.9%" in doc
    assert "Competitive positioning" in brd and "Feasibility verdict" in brd
    assert "Feasibility —" in brd, "critical/major flaws must appear in the BRD risk register"
    assert "## Feasibility Check" in docs["ai_handoff_validation"]
    assert "{{" not in "".join(docs.values()), "unfilled template placeholder leaked into a document"


def test_feasibility_is_not_rerun_by_gap_correction():
    ctx = answered_context()
    run_full_pipeline(ctx)
    n = sum(1 for c in ctx.agent_contributions if c.agent == AgentRole.FEASIBILITY_ASSESSMENT)
    assert n == 1


# ---------------------------------------------------------------------------------------------
# LIVE mode with a scripted client (no network)
# ---------------------------------------------------------------------------------------------
class FakeClient:
    def __init__(self, market_reply=None, assess_reply=None):
        self.prompts = []
        self.market_reply, self.assess_reply = market_reply, assess_reply

    def generate(self, prompt, max_tokens=800):
        self.prompts.append(prompt)
        if "[[TASK:feasibility.market]]" in prompt:
            return self.market_reply or json.dumps(MARKET)
        if "[[TASK:feasibility.assess]]" in prompt:
            return self.assess_reply or json.dumps(ASSESS)
        if "[[TASK:profile.system_security]]" in prompt:
            return "Sure! ```json\n" + json.dumps(SYS_SEC) + "\n```"          # fenced + chatty: must still parse
        if "[[TASK:profile.performance_scalability]]" in prompt:
            return json.dumps(PERF_SCL)
        raise AssertionError("unexpected prompt: " + prompt[:80])


MARKET = {
    "idea_summary": "Marketplace for booking home cleaners.", "target_market": "Urban households in India and the UAE.",
    "demand_signals": ["Growing dual-income households"], "market_risks": ["Well-funded incumbents"],
    "competitors": [
        {"name": "Urban Company", "type": "direct", "what_they_do": "Home services marketplace", "strengths": "Brand", "weaknesses": "Fees",
         "pricing_model": "Commission", "threat_level": "high"},
        {"name": "WhatsApp groups", "type": "Substitute", "what_they_do": "Informal", "strengths": "Free", "weaknesses": "No trust",
         "pricing_model": "Unknown", "threat_level": "weird-value"}],
    "competitive_gaps": ["Recurring-visit continuity"],
    "differentiators": [{"differentiator": "Same cleaner every visit", "description": "d", "competitors_lacking": "Most", "defensibility": "strong", "risk_if_copied": "r"}],
    "positioning_statement": "For busy households ...",
}
ASSESS = {
    "feasibility": {"desirability": {"rating": "High", "assessment": "Clear need."}, "technical": {"rating": "High", "assessment": "Standard."},
                    "operational": {"rating": "Medium", "assessment": "Needs vetting ops."}, "financial": {"rating": "Medium", "assessment": "Margins thin."},
                    "legal": {"rating": "nonsense", "assessment": "Labour rules."}},
    "flaws": [{"severity": "minor", "area": "Ops", "flaw": "Vetting is manual", "why_it_matters": "w", "recommended_change": "c",
               "related_question_ids": ["bp_providers"]},
              {"severity": "Critical", "area": "Economics", "flaw": "Take rate cannot cover support cost", "why_it_matters": "Loses money",
               "recommended_change": "Raise take rate or cut support",
               "related_question_ids": ["nfr_users_12m", "made_up_id", "nfr_users_12m", "additional_information"]},
              {"severity": "Major", "area": "Trust", "flaw": "No vetting of providers", "why_it_matters": "Safety", "recommended_change": "Vet them",
               "related_question_ids": "not-a-list"}],
    "assumptions_to_validate": [{"assumption": "a", "how_to_validate": "h", "risk_if_wrong": "r"}],
    "recommended_changes": ["Fix unit economics first"], "must_confirm_before_build": ["Labour law per country"],
    "verdict": "GO", "verdict_rationale": "Looks fine overall.", "confidence": "high",
}
SYS_SEC = {"system_requirements": [{"category": "Hosting & infrastructure", "requirement": "Run in two regions (UAE and India) with a CDN.", "priority": "P0"}],
           "security_requirements": [{"category": "Authentication", "requirement": "Phone-number OTP plus device binding for cleaners.", "verification": "Pen test", "priority": "p0"}]}
PERF_SCL = {"performance_requirements": [{"metric": "Booking confirmation", "target": "under 1.5 s p95", "condition": "at 10,000 concurrent users", "measurement": "APM", "priority": "P0"}],
            "scalability_requirements": []}


def test_live_mode_parses_normalises_and_cannot_be_talked_into_go():
    ctx = answered_context()
    client = FakeClient()
    out = feas._live(ctx, client)
    assert out["verdict"] == "GO WITH CHANGES", "model said GO but a critical flaw exists"
    assert out["competitors"][0]["type"] == "Direct" and out["competitors"][0]["threat_level"] == "High"
    assert out["competitors"][1]["threat_level"] == "Medium", "garbage enum values must be normalised"
    assert out["feasibility"]["legal"]["rating"] == "Medium"
    assert out["flaws"][0]["severity"] == "Critical" and out["flaws"][0]["id"] == "FLAW-01"
    assert "NOT been verified" in out["evidence_note"] or "NOT" in out["evidence_note"]
    # the profile prompt carries the fixed numbers; the assessment prompt sees the competitor analysis
    profile_prompts = [p for p in client.prompts if "TASK:profile." in p]
    assert profile_prompts and all("10,000" in p or "5,000" in p for p in profile_prompts)
    assert any("Urban Company" in p for p in client.prompts if "TASK:feasibility.assess" in p)


def test_questions_to_revisit_only_real_ids_only_critical_major():
    ctx = answered_context()
    out = feas._live(ctx, FakeClient())
    rev = out["questions_to_revisit"]
    ids = [r["question_id"] for r in rev]
    assert ids == ["nfr_users_12m"], ids                      # invented id, duplicate, free-text id and non-list all dropped
    assert "bp_providers" not in ids, "Minor flaws must not pull questions into the popup"
    assert rev[0]["severity"] == "Critical" and rev[0]["current_answer"] == ANSWERS["nfr_users_12m"]
    assert rev[0]["reasons"][0]["flaw"].startswith("Take rate")
    # every flaw carries a validated list
    assert all(isinstance(f["related_question_ids"], list) for f in out["flaws"])


def test_mock_flaws_point_at_the_answers_behind_them():
    ctx = answered_context(fill=None)       # answer with real options (not "Not sure yet"), so we test the mapping not the undecided-flaw
    out = feas._mock(ctx)
    by_area = {f["area"]: f for f in out["flaws"]}
    assert "nfr_data_sensitivity" in by_area["Regulatory"]["related_question_ids"]
    assert "nfr_geography" in by_area["Regulatory"]["related_question_ids"]
    cold = by_area["Cold start"]["related_question_ids"]
    assert cold and all("onboard" in next(q.text for q in ctx.discovery_questions if q.id == i).lower() for i in cold), \
        "cold-start must point only at the provider-onboarding question, not every question that mentions providers"
    rev_ids = {r["question_id"] for r in out["questions_to_revisit"]}
    valid = {q.id for q in ctx.discovery_questions}
    assert rev_ids and rev_ids <= valid and "additional_information" not in rev_ids
    # far fewer than the whole questionnaire — that is the point of the popup
    assert len(rev_ids) < len(ctx.discovery_questions) / 2
    # a major flaw with no matching question is reported separately instead of silently disappearing
    unlinked = {u["flaw"] for u in out["unlinked_flaws"]}
    assert by_area["Differentiation"]["flaw"] in unlinked and by_area["Differentiation"]["related_question_ids"] == []


def test_revisit_reaches_the_ui_summary_and_the_document():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
    import server
    ctx = answered_context()
    run_full_pipeline(ctx)
    summary = server._feasibility_summary(ctx)
    assert summary["revisit"] and set(summary["revisit"][0]) == {"question_id", "severity", "reasons"}
    assert all(r["question_id"] in {q.id for q in ctx.discovery_questions} for r in summary["revisit"])
    ctx = export_all_artefacts(ctx)
    doc = next(a for a in ctx.artefacts if a.type == "feasibility_assessment").content_markdown
    assert "**Discovery answers worth revisiting**" in doc
    first_q = next(q.text for q in ctx.discovery_questions if q.id == summary["revisit"][0]["question_id"])
    assert first_q in doc


def test_live_profile_keeps_baseline_topics_the_model_omitted():
    ctx = answered_context()
    prof = sp.build_live_profile(ctx, FakeClient())
    assert prof["generated_by"] == "baseline+llm"
    sec_text = " ".join(r["requirement"] for r in prof["security_requirements"])
    assert "Phone-number OTP" in sec_text, "tailored model item kept"
    cats = {r["category"] for r in prof["security_requirements"]}
    assert {"Encryption in transit", "Audit logging", "Payment security"} <= cats, "mandatory topics restored from the baseline"
    assert prof["security_requirements"][0]["priority"] == "P0", "priority case normalised"
    assert prof["scalability_requirements"], "empty model list falls back to the baseline"
    ids = [r["id"] for r in prof["security_requirements"]]
    assert len(ids) == len(set(ids))


def test_live_refuses_an_empty_assessment():
    ctx = answered_context()
    bad = FakeClient(assess_reply=json.dumps({**ASSESS, "flaws": []}))
    try:
        feas._live(ctx, bad)
    except RuntimeError as e:
        assert "no flaws" in str(e)
    else:
        raise AssertionError("an assessment with zero flaws must be rejected")


def test_downstream_prompts_receive_the_shared_numbers_and_findings():
    import chunked as ch
    ctx = answered_context()
    run_full_pipeline(ctx)
    block = ch.idea_block(ctx)
    assert "PLANNING TARGETS" in block and "FEASIBILITY FINDINGS" in block


def _contradiction_assess(notes):
    a = json.loads(json.dumps(ASSESS))
    flaw = {"severity": "Critical", "area": "Economics", "flaw": "Platform-supplied cleaning products contradict the promise of cheaper prices and lower commission",
            "why_it_matters": "Margin", "recommended_change": "Require cleaners or customers to provide supplies"}
    if notes:
        flaw["related_questions"] = [{"id": "nfr_users_12m", "why": "Supplies shipped by the platform raise cost per visit", "change": "Make supplies the cleaner's responsibility"},
                                     {"id": "nfr_geography", "why": "Competing on cheaper prices is hard to keep if the platform also pays for supplies", "change": "Pick a differentiator other than price"}]
    else:
        flaw["related_question_ids"] = ["nfr_users_12m", "nfr_geography"]
    a["flaws"] = [flaw]
    return json.dumps(a)


def test_flaw_linked_to_two_answers_is_not_repeated_word_for_word():
    ctx = answered_context()
    # model gave an explanation per answer -> each answer shows ITS OWN reason and change
    out = feas._live(ctx, FakeClient(assess_reply=_contradiction_assess(notes=True)))
    rev = {r["question_id"]: r for r in out["questions_to_revisit"]}
    a, b = rev["nfr_users_12m"]["reasons"][0], rev["nfr_geography"]["reasons"][0]
    assert a["flaw"] != b["flaw"] and a["suggestion"] != b["suggestion"] and a["specific"] and b["specific"]
    assert "price" in b["flaw"].lower() and b["shared_with"] == ["nfr_users_12m"]
    # legacy shape (ids only) -> only the FIRST answer carries the suggestion; the other is marked as sharing the problem
    ctx.feasibility_history = []          # an independent first round, not a re-run of the one above
    out = feas._live(ctx, FakeClient(assess_reply=_contradiction_assess(notes=False)))
    rev = {r["question_id"]: r for r in out["questions_to_revisit"]}
    first, second = rev["nfr_users_12m"]["reasons"][0], rev["nfr_geography"]["reasons"][0]
    assert first["primary"] and first["suggestion"] and not second["primary"] and second["suggestion"] == ""
    assert second["shared_with"] == ["nfr_users_12m"]
    # the prompt now demands answer-specific reasons and forbids topic-only links


def test_prompt_requires_answer_specific_links():
    client = FakeClient()
    feas._live(answered_context(), client)
    p = next(x for x in client.prompts if "TASK:feasibility.assess" in x)
    assert "related_questions" in p and "ONLY if changing THAT answer" in p and "contradiction between two answers" in p


def test_export_points_a_shared_answer_at_the_one_with_the_fix():
    ctx = answered_context()
    out = feas._live(ctx, FakeClient(assess_reply=_contradiction_assess(notes=False)))
    rev = out["questions_to_revisit"]
    second = next(r for r in rev if r["question_id"] == "nfr_geography")
    first = next(r for r in rev if r["question_id"] == "nfr_users_12m")
    from export import _revisit_suggestion
    assert _revisit_suggestion(first, rev).startswith("Require cleaners")
    assert _revisit_suggestion(second, rev) == "Resolve together with: " + first["question"]


def test_rerun_never_re_asks_an_answer_already_reviewed():
    """Round 2 must not put the same answers in front of the founder again (changed OR kept), and must not loop."""
    ctx = answered_context(answers={"nfr_users_12m": "50,000–500,000"}, fill=None)
    first = feas._mock(ctx)
    asked = {r["question_id"] for r in first["questions_to_revisit"]}
    assert asked and first["review_round"] == 1 and len(ctx.feasibility_history) == 1
    by_id = {q.id: q for q in ctx.discovery_questions}
    changed = next(iter(asked))
    ctx.add_answer(changed, next(o for o in by_id[changed].options if o != by_id[changed].answer))
    ctx.system_profile = None                     # a fresh run rebuilds it, as the server does
    second = feas._mock(ctx)
    assert second["review_round"] == 2
    assert not asked & {r["question_id"] for r in second["questions_to_revisit"]}, "already-reviewed answers were asked again"
    mem = {r["question_id"]: r for r in second["already_reviewed"]}
    assert set(mem) == asked and mem[changed]["changed"] is True
    assert all(set(f["question_ids"]) <= asked for f in second["reviewed_flaws"])
    # a third run with nothing new to review converges: still nothing to ask
    third = feas._mock(ctx)
    assert not asked & {r["question_id"] for r in third["questions_to_revisit"]}


def test_following_the_mock_suggestion_actually_removes_the_flaw():
    ctx = answered_context(fill=None)
    sev = {f["area"]: f["severity"] for f in feas._mock(ctx)["flaws"]}
    assert sev["Cold start"] == "Major"
    ctx.add_answer("bp_providers", "Fully vetted/curated by us")
    ctx.system_profile = None
    sev = {f["area"]: f["severity"] for f in feas._mock(ctx)["flaws"]}
    assert sev["Cold start"] == "Minor", "taking the suggested change must reduce the flaw, not repeat it"


def test_live_prompt_remembers_changes_and_removed_options():
    ctx = answered_context()
    feas._live(ctx, FakeClient())                                  # round 1 flags nfr_users_12m
    ctx.add_answer("nfr_users_12m", "5,000–50,000")
    client = FakeClient()
    out = feas._live(ctx, client)                                  # the fake model links nfr_users_12m AGAIN
    prompt = next(p for p in client.prompts if "TASK:feasibility.assess" in p)
    assert "EARLIER ROUNDS OF THIS CHECK" in prompt and "CHANGED by the founder" in prompt
    assert "Options the founder REMOVED: '50,000–500,000'" in prompt
    assert "do NOT suggest going back" in prompt
    assert "nfr_users_12m" not in {r["question_id"] for r in out["questions_to_revisit"]}, "the code must hold even if the model does not"
    assert out["reviewed_flaws"] and out["reviewed_flaws"][0]["question_ids"] == ["nfr_users_12m"]


def test_review_history_survives_save_and_reopen():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "webapp"))
    import server
    from agents.base import BaseAgent  # noqa: F401
    ctx = answered_context(answers={"nfr_users_12m": "50,000–500,000"}, fill=None)
    out = feas._mock(ctx)
    from context import AgentContribution
    ctx.add_contribution(AgentContribution(agent=AgentRole.FEASIBILITY_ASSESSMENT, summary="s", output=out))
    rec = server._record_from_ctx(ctx)
    assert rec["feasibility"]["history"] == ctx.feasibility_history and rec["feasibility"]["round"] == 1
    again = server._ctx_from_record(rec)
    assert again.feasibility_history == ctx.feasibility_history
    assert set(feas.review_memory(again)) == {r["question_id"] for r in out["questions_to_revisit"]}


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
