"""The card audit's independent unit and currency re-check (scripts/card_audit.py)."""
import card_audit as ca


def test_a_claim_that_keeps_the_quotes_unit_and_currency_has_no_flag():
    assert ca.unit_problems('Income of Rs 86.5 crore, up 12%', 'Q2 income at Rs. 86.5 Crore, up 12% y-o-y') == []
    assert ca.unit_problems('allotted 5,30,000 shares', 'allotted 5,30,000 (1.72%) Equity Shares') == []


def test_a_changed_unit_is_flagged_because_crore_lakh_and_million_get_mixed_up():
    out = ca.unit_problems('Order of Rs 50 crore', 'Order worth 50 million')
    assert any(x.startswith('UNIT') and 'million' in x for x in out)
    assert ca.unit_problems('Rs 5 crore', 'Rs 50 lakh')[0].startswith('UNIT')


def test_a_number_without_its_unit_in_the_quote_is_flagged_for_a_look_at_the_table_header():
    out = ca.unit_problems('Revenue Rs 86.5 crore', 'Revenue from operations 86.5')
    assert out and 'table header' in out[0]


def test_rupees_claimed_for_a_dollar_quote_is_flagged():
    out = ca.unit_problems('Capex of Rs 15.5 billion', 'investment of USD 15.5 billion by 2030')
    assert any(x.startswith('CURRENCY') for x in out)
