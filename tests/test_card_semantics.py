"""Tests for deterministic semantics and evidence-backed card narrative."""
import card_semantics as cs


def test_cancellation_cannot_be_headlined_as_a_win():
    assert "cancellation" in cs.semantic_reason(
        "Acme wins the supply contract", "The customer terminated the supply contract."
    )


def test_proposed_action_cannot_be_called_approved():
    assert "upgrades a proposal" in cs.semantic_reason(
        "Acme approves a new plant", "The board recommended the proposal, subject to shareholder approval."
    )


def test_correctly_preserves_cancelled_status():
    assert cs.semantic_reason(
        "Acme terminates the supply contract", "The customer terminated the supply contract."
    ) is None


def test_named_counterparty_must_be_in_the_quote():
    assert "named party" in cs.semantic_reason(
        "Acme acquires Beta Industries", "The board approved an acquisition of a majority stake."
    )


def test_narrative_rejects_quote_not_in_memory():
    out = cs.validate_narrative(
        [{"text": "Management targeted 18% EBITDA margin.", "evidence": [
            {"source": "company_memory", "quote": "Management targeted 18% EBITDA margin."}]}],
        "Current quarter EBITDA margin was 19%.", "- management call: exact quote: expected 18% EBITDA margin",
        lambda text, quotes: True,
    )
    assert out and not out[0]["shown"]
    assert "not found" in out[0]["reason"]


def test_guidance_claim_requires_both_sources_and_checks_direction():
    memory = '- 2026-04-20: management expects EBITDA margin to reach 18% (source: https://example.com/call)'
    doc = "The EBITDA margin for the quarter was 16%."
    out = cs.validate_narrative(
        [{"text": "The company achieved its 18% EBITDA margin target at 16%.", "evidence": [
            {"source": "company_memory", "quote": "management expects EBITDA margin to reach 18%"},
            {"source": "current_filing", "quote": "The EBITDA margin for the quarter was 16%."}]}],
        doc, memory, lambda text, quotes: True,
    )
    assert not out[0]["shown"]
    assert "below the target" in out[0]["reason"]


def test_narrative_requires_number_backing():
    doc = "Revenue from operations was ₹100 crore."
    out = cs.validate_narrative(
        [{"text": "Revenue was ₹120 crore.", "evidence": [
            {"source": "current_filing", "quote": "Revenue from operations was ₹100 crore."}]}],
        doc, "", lambda text, quotes: "120" in " ".join(quotes),
    )
    assert not out[0]["shown"]
    assert "number" in out[0]["reason"]
