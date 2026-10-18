"""Tests for deterministic semantics and evidence-backed card narrative."""
import card_semantics as cs


def test_cancellation_cannot_be_headlined_as_a_win():
    assert "negates" in cs.semantic_reason(
        "Acme wins the supply contract", "The customer terminated the supply contract."
    )


def test_negated_approval_cannot_be_reported_as_approved():
    assert "negates" in cs.semantic_reason(
        "Acme approves the acquisition", "The board did not approve the acquisition."
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
    memory = '- 2026-04-20: management expects consolidated EBITDA margin to reach 18% in Q2 FY27 (source: https://example.com/call)'
    doc = "Consolidated EBITDA margin for Q2 FY27 was 16%."
    out = cs.validate_narrative(
        [{"text": "The company achieved its 18% EBITDA margin target at 16%.", "evidence": [
            {"source": "company_memory", "quote": "management expects consolidated EBITDA margin to reach 18% in Q2 FY27"},
            {"source": "current_filing", "quote": "Consolidated EBITDA margin for Q2 FY27 was 16%."}]}],
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


def test_valid_margin_guidance_comparison_is_allowed():
    memory = '- management call 2026-04-20: management expects consolidated EBITDA margin to reach 18% in Q2 FY27 (source: https://example.com/call)'
    doc = "Consolidated EBITDA margin for Q2 FY27 was 19%."
    out = cs.validate_narrative(
        [{"text": "The company exceeded its 18% EBITDA margin target at 19%.", "evidence": [
            {"source": "company_memory", "quote": "management expects consolidated EBITDA margin to reach 18% in Q2 FY27"},
            {"source": "current_filing", "quote": "Consolidated EBITDA margin for Q2 FY27 was 19%."}]}],
        doc, memory, lambda text, quotes: True,
    )
    assert out[0]["shown"]


def test_forward_fy_guidance_can_be_shown_without_claiming_achievement():
    doc = "Management targets an EBITDA margin of 28% by FY28."
    out = cs.validate_narrative(
        [{"text": "Management has set a FY28 EBITDA margin target of 28%.", "evidence": [
            {"source": "current_filing", "quote": doc}]}],
        doc, "", lambda text, quotes: True,
    )
    assert out[0]["shown"]


def test_annual_target_is_not_judged_against_an_earlier_quarter():
    memory = '- management call 2026-04-20: management targets consolidated EBITDA margin of 28% by FY28 (source: https://example.com/call)'
    doc = "Consolidated EBITDA margin for Q2 FY27 was 19%."
    out = cs.validate_narrative(
        [{"text": "The company missed its FY28 EBITDA margin target of 28% at 19%.", "evidence": [
            {"source": "company_memory", "quote": "management targets consolidated EBITDA margin of 28% by FY28"},
            {"source": "current_filing", "quote": "Consolidated EBITDA margin for Q2 FY27 was 19%."}]}],
        doc, memory, lambda text, quotes: True,
    )
    assert not out[0]["shown"]
    assert "different fiscal years" in out[0]["reason"]


def test_guidance_comparison_is_held_when_accounting_basis_differs():
    memory = '- management call 2026-04-20: management expects consolidated EBITDA margin to reach 18% in Q2 FY27 (source: https://example.com/call)'
    doc = "Standalone EBITDA margin for Q2 FY27 was 19%."
    out = cs.validate_narrative(
        [{"text": "The company exceeded its 18% EBITDA margin target at 19%.", "evidence": [
            {"source": "company_memory", "quote": "management expects consolidated EBITDA margin to reach 18% in Q2 FY27"},
            {"source": "current_filing", "quote": "Standalone EBITDA margin for Q2 FY27 was 19%."}]}],
        doc, memory, lambda text, quotes: True,
    )
    assert not out[0]["shown"]
    assert "basis" in out[0]["reason"]


def test_cleaned_table_quote_is_checked_against_original_source_with_reader_quote_matcher():
    out = cs.validate_narrative(
        [{"text": "Revenue was 1,234.", "evidence": [
            {"source": "current_filing", "quote": "Revenue | 1,234"}]}],
        "Revenue       1,234", "", lambda text, quotes: True,
        current_quote_check=lambda quote: quote == "Revenue | 1,234",
    )
    assert out[0]["shown"]


def test_report_filing_exemption_is_not_a_blanket_governance_exemption():
    assert "blanket exemption" in cs.semantic_reason(
        "ANB Metal Cast exempt from corporate governance",
        "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026.",
    )


def test_precisely_scoped_report_exemption_is_not_flagged():
    assert cs.semantic_reason(
        "ANB Metal Cast not required to file Corporate Governance Report",
        "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026.",
        issuer_names=("ANB Metal Cast",),
    ) is None
