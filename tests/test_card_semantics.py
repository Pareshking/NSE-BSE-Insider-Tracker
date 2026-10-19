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
    assert "overstates the exemption" in cs.semantic_reason(
        "ANB Metal Cast exempt from corporate governance",
        "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026.",
    )


def test_precisely_scoped_report_exemption_is_not_flagged():
    assert cs.semantic_reason(
        "ANB Metal Cast not required to file Corporate Governance Report",
        "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026.",
        issuer_names=("ANB Metal Cast",),
    ) is None


def test_non_applicability_headline_must_preserve_regulation_scope():
    assert "overstates the exemption" in cs.semantic_reason(
        "ANB Metal Cast certifies non-applicability of corporate governance",
        "Certificate of Non-Applicability of Corporate Governance provisions under Regulation 27 of SEBI Listing Obligations and Disclosure Requirements Regulations, 2015.",
        issuer_names=("ANB Metal Cast",),
    )


def test_regulation_27_scope_is_preserved_when_headline_names_it():
    assert cs.semantic_reason(
        "ANB Metal Cast confirms Regulation 27 corporate governance provisions are not applicable",
        "Certificate of Non-Applicability of Corporate Governance provisions under Regulation 27 of SEBI Listing Obligations and Disclosure Requirements Regulations, 2015.",
        issuer_names=("ANB Metal Cast",),
    ) is None


def test_narrative_holds_unsupported_causal_explanation():
    out = cs.validate_narrative(
        [{"text": "Rossari Biotech achieved record quarterly revenue of Rs. 698 crores, driven by domestic business momentum and international expansion.",
          "evidence": [{"source": "current_filing",
                        "quote": "We delivered robust consolidated growth of 19% YoY in Q2FY27, achieving a record quarterly revenue of Rs. 698 crores."}]}],
        "We delivered robust consolidated growth of 19% YoY in Q2FY27, achieving a record quarterly revenue of Rs. 698 crores.",
        "", lambda text, quotes: True,
        issuer_names=("Rossari Biotech",),
    )
    assert not out[0]["shown"]
    assert "causal explanation" in out[0]["reason"]


def test_narrative_keeps_causal_explanation_when_quote_supports_it():
    out = cs.validate_narrative(
        [{"text": "Revenue rose due to stronger domestic demand and international expansion.",
          "evidence": [{"source": "current_filing",
                        "quote": "Revenue rose due to stronger domestic demand and international expansion."}]}],
        "Revenue rose due to stronger domestic demand and international expansion.",
        "", lambda text, quotes: True,
    )
    assert out[0]["shown"]


def test_record_revenue_achievement_is_not_misclassified_as_guidance():
    out = cs.validate_narrative(
        [{"text": "Rossari Biotech achieved record quarterly revenue of Rs. 697.6 crores in Q2 FY27, growing 19.0% year-on-year.",
          "evidence": [{"source": "current_filing",
                        "quote": "Highest-ever quarterly revenue of Rs. 697.6 crores, a 19.0% growth on y-o-y basis"}]}],
        "Highest-ever quarterly revenue of Rs. 697.6 crores, a 19.0% growth on y-o-y basis",
        "", lambda text, quotes: True,
        issuer_names=("Rossari Biotech",),
    )
    assert out[0]["shown"]

def test_broad_exemption_is_held_when_headline_quote_is_only_sme_listing():
    reason = cs.semantic_reason(
        "ANB Metal Cast is exempt from corporate governance provisions because its securities are listed on the SME Platform",
        "The company has listed its specified securities on SME Platform of National Stock Exchange of India Limited.",
        doc=("Certificate of Non-Applicability of Corporate Governance provisions under Regulation 27. "
             "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026."),
        issuer_names=("ANB Metal Cast",),
    )
    assert reason and "overstates the exemption" in reason

def test_generic_exemption_subtitle_is_held_when_filing_only_exempts_report():
    reason = cs.semantic_reason(
        "Exemption applies as specified securities are listed on SME Platform of NSE",
        "The company, ANB Metal Cast Limited has listed its specified securities on SME Platform of National Stock Exchange of India Limited.",
        doc=("Certificate of Non-Applicability of Corporate Governance provisions under Regulation 27. "
             "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026."),
        issuer_names=("ANB Metal Cast",),
    )
    assert reason and "overstates the exemption" in reason

def test_corporate_governance_exemption_headline_preserves_report_scope():
    reason = cs.semantic_reason(
        "ANB Metal Cast confirms corporate governance exemption",
        "As the company falls under the ambit of the aforesaid exemption, a compliance with the Corporate Governance provision specified in the aforesaid Regulation shall not be applicable to the Company.",
        doc=("Certificate of Non-Applicability of Corporate Governance provisions under Regulation 27. "
             "Therefore, it is not required to submit Corporate Governance Report for the quarter ended September 30, 2026."),
        issuer_names=("ANB Metal Cast",),
    )
    assert reason and "overstates the exemption" in reason


def test_legal_entity_suffix_is_not_misread_as_an_unsupported_named_party():
    reason = cs.semantic_reason(
        "UltraTech Cement approved a corporate guarantee for UHG Holdings IFSC Private Limited",
        "UltraTech Cement approved a corporate guarantee for UHG Holdings IFSC",
        issuer_names=("UltraTech Cement",),
    )
    assert reason is None


def test_management_role_is_not_misread_as_an_unsupported_named_party():
    reason = cs.semantic_reason(
        "Kailash Chandra Jhanwar transitions from Managing Director to Non-Executive Vice Chairman",
        "Kailash Chandra Jhanwar will transition to Non-Executive Vice Chairman effective January 1, 2027",
        issuer_names=("UltraTech Cement",),
    )
    assert reason is None
