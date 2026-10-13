"""The announcement-reader sample check (scripts/announcement_sample.py):
its quote and number checks and scoring, with no network and no model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import announcement_sample as a

DOC = ('the Board has approved the proposal for buy-back of up to 14,75,000 (Fourteen Lakh Seventy Five\n'
       'Thousand) fully paid-up equity shares ... at a price of ₹162/- (Rupees One Hundred Sixty Two only)')
ROW = {'symbol': 'GLOBAL', 'subject': 'Buyback',
       'expected': {'category': 'buyback_tender', 'price_per_share': 162, 'shares': 1475000}}


def test_quotes_must_be_in_the_document_and_hold_the_number():
    assert a.quote_found('buy-back of up to 14,75,000 (Fourteen Lakh Seventy Five Thousand)', DOC)  # across a line break
    assert not a.quote_found('buy-back of up to 15,00,000 shares', DOC)
    assert not a.quote_found('162', DOC)   # too short to prove anything
    assert a.digits_in_quote(1475000, 'up to 14,75,000 (Fourteen Lakh') and a.digits_in_quote(475, '₹475.00/-')
    assert not a.digits_in_quote(1475000, 'up to 14,75 shares')


def test_a_right_value_with_an_invented_quote_does_not_score():
    out = {'category': 'buyback_tender', 'fields': [
        {'name': 'price_per_share', 'value': 162, 'quote': 'at a price of ₹162/- (Rupees One Hundred Sixty Two only)'},
        {'name': 'shares', 'value': 1475000, 'quote': 'buy-back of 14,75,000 shares in total'},   # not in DOC
        {'name': 'amount', 'value': 1, 'quote': 'nowhere in the filing'}]}
    c = a.check(ROW, {'category': 'buyback_open_market', 'read_pdf': True}, out, DOC)
    assert c['score'] == [2, 3] and not c['sort_category_right']
    extra = next(f for f in c['fields'] if f['field'] == 'amount')
    assert extra['match'] is None and extra['quote_found'] is False
    assert 'held back' in a.report_markdown([c], {'read': 'r', 'sort': 's'})


def test_values_compare_as_filed_numbers_flags_and_ratios():
    assert a.same('amount', 2999999852.45, '2,99,99,99,852.45') and not a.same('shares', 150000, 15000)
    assert a.same('allottee_is_promoter', True, 'true') and a.same('entity', 'subsidiary', 'Subsidiary')
    assert a.in_units('28,200.00', 'Lakhs') == 2_820_000_000 and a.in_units('3,351', 'Million') == 3_351_000_000
    assert a.same('capacity_to', '240 KL per day', '240 KL per day')


def test_amounts_are_converted_by_our_code_and_metrics_found_by_value():
    doc = ('the consolidated orders received by the Company are worth Rs. 102 Cr out of which ... '
           'Investment Required Indian Rupees 3,351 Million')
    row = {'symbol': 'X', 'subject': 's', 'expected': {'category': 'capex', 'amount': 3_351_000_000,
                                                       'metrics': [{'label': 'order intake', 'value': 1_020_000_000}]}}
    out = {'category': 'capex', 'fields': [
        {'name': 'amount', 'value': '3,351', 'quote': 'Investment Required Indian Rupees 3,351 Million'},
        {'name': 'amount_unit', 'value': 'million', 'quote': 'Indian Rupees 3,351 Million'}],
        'metrics': [{'label': 'orders received', 'period': 'Sep 2026', 'value': 102, 'unit': 'Cr',
                     'quote': 'orders received by the Company are worth Rs. 102 Cr'}]}
    c = a.check(row, None, out, doc)
    assert c['score'] == [3, 3]
    assert a.same('ratio', '2:21', '2 : 21') and a.parse_json('```json\n{"category": "qip"}\n```') == {'category': 'qip'}
    assert a.parse_json('no json here') is None


def test_sample_file_lists_real_filings_with_their_links():
    rows = json.loads((Path(a.HERE) / 'announcement_sample_expected.json').read_text(encoding='utf-8'))
    assert len(rows) == 24 and len({r["seq_id"] for r in rows}) == 24
    assert all(r['file_url'].startswith('https://nsearchives.nseindia.com/corporate/') for r in rows)
    assert all(r['expected']['category'] in a.CATEGORIES for r in rows)
    assert all(set(r['expected']) - {'category', 'metrics'} <= set(a.FIELDS) for r in rows)
