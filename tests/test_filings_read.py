"""The Brief's "Filings read" card (streamlit_app/screens/filings_read.py): only checked values, each with
its quote and evidence; held-back values counted with their reasons; nothing before the reader has data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
from screens import filings_read as fr  # noqa: E402

FIELDS = [
    {'name': 'price_per_share', 'value': '165.65', 'number': 165.65, 'quote': 'at the issue price of Rs. 165.65',
     'evidence': 'exact', 'shown': True},
    {'name': 'amount', 'value': '15.5', 'number': 15.5e9, 'unit': 'billion', 'quote': 'USD 15.5 billion',
     'evidence': 'table', 'shown': True, 'currency': 'USD'},
    {'name': 'currency', 'value': 'USD', 'quote': 'USD 15.5 billion', 'evidence': 'exact', 'shown': True},
    {'name': 'entity', 'value': 'listed', 'quote': 'the Company', 'shown': False, 'reason': 'entity labels not shown yet'},
    {'name': 'shares', 'value': '10', 'number': 10, 'quote': 'ten', 'shown': False, 'reason': 'number not in its quote'}]


def row(**kw):
    return {'event_id': 'nse:1', 'exchange': 'NSE', 'symbol': 'HYUNDAI', 'company': 'Hyundai Motor India Ltd',
            'subject': 'Press Release', 'category': 'capex', 'status': 'read', 'shown': 3, 'held': 2,
            'broadcast_at': '2026-10-13T10:15:00+05:30', 'broadcast_date': '2026-10-13',
            'file_url': 'https://nsearchives.nseindia.com/corporate/x.pdf', 'reader': 'nvidia:moonshotai/kimi-k3',
            'fields': json.dumps(FIELDS), 'metrics': '[]', 'agreed': json.dumps({'price_per_share': True}), **kw}


def test_card_shows_checked_values_with_quotes_and_counts_the_rest():
    html = fr.card_html(row())
    assert 'Price a share' in html and 'USD 15.50 bn' in html and 'at the issue price of Rs. 165.65' in html
    assert 'in the filing' in html and 'table row' in html and '2 readers agree' in html
    assert 'listed' not in html.split('held back')[0]   # entity kept back
    assert '1 value held back: number not in its quote' in html and 'entity labels' not in html   # by design, not held
    assert '13 Oct, 10:15 · NSE' in html and 'href="/company?symbol=HYUNDAI"' in html and 'x.pdf' in html


def test_recent_keeps_filings_with_shown_values_since_the_day():
    reads = pd.DataFrame([row(), row(event_id='nse:2', shown=0), row(event_id='nse:3', status='failed'),
                          row(event_id='nse:4', category='routine'), row(event_id='nse:5', broadcast_date='2026-10-01'),
                          row(event_id='bse:6', status='same_filing_other_exchange')])
    assert list(fr.recent(reads, pd.Timestamp('2026-10-12'))['event_id']) == ['nse:1']
    assert fr.recent(pd.DataFrame(), pd.Timestamp('2026-10-12')).empty



def test_the_same_file_filed_again_is_one_card_with_where_else_it_was_filed():
    reads = pd.DataFrame([row(), row(event_id='bse:1', exchange='BSE', status='same_file', same_as='nse:1',
                                     broadcast_at='2026-10-13T10:09:00+05:30'),
                          row(event_id='nse:2', status='same_file', same_as='nse:1', subject='General Updates',
                              broadcast_at='2026-10-13T10:20:00+05:30'),
                          row(event_id='nse:7', status='same_file', same_as='nse:9')])   # its original not shown
    got = fr.recent(reads, pd.Timestamp('2026-10-12'))
    assert list(got['event_id']) == ['nse:1', 'nse:7']
    html = fr.card_html(got.iloc[0].to_dict())
    assert 'Also filed: BSE 13 Oct, 10:09 · NSE 13 Oct, 10:20' in html
    assert 'Also filed' not in fr.card_html(got.iloc[1].to_dict())


def test_held_back_reasons_are_counted_and_an_empty_period_is_not_written():
    fields = [dict(FIELDS[4]), dict(FIELDS[4], name='amount')]
    metrics = [{'label': 'Stake acquired', 'period': 'N/A', 'value': '89.8', 'number': 89.8, 'unit': 'percent',
                'quote': 'acquire c.89.8%', 'evidence': 'exact', 'shown': True}]
    html = fr.card_html(row(fields=json.dumps(fields), metrics=json.dumps(metrics)))
    assert '2 values held back: number not in its quote ×2' in html
    assert '<td>Stake acquired</td>' in html and 'N/A' not in html

def test_card_waits_for_data_and_renders_when_there_is_some():
    code = APP_PATHS + f'''
import json, pandas as pd
from screens import filings_read
reads = pd.DataFrame({[row()]!r})
filings_read.render(pd.DataFrame(), pd.Timestamp('2026-10-12'))
filings_read.render(reads, pd.Timestamp('2026-10-12'))
'''
    at = AppTest.from_string(code).run(timeout=60)
    assert not at.exception
    html = ' '.join(h.proto.body for h in at.get('html'))
    assert html.count('<article class="rc">') == 1 and 'Filings read' in ' '.join(m.value for m in at.markdown) + html


def test_no_currency_in_the_filing_means_none_on_the_site():
    # 13 Oct dry run: Tristar's US$ metrics would have shown as rupees; a value is written in rupees only
    # when its filing says so, and as the filing writes it when the filing names no currency
    assert fr.metric_text({'number': 1.4e9, 'unit': 'billion', 'value': '1.4', 'currency': 'USD'}) == 'USD 1.40 bn'
    assert fr.metric_text({'number': 2e9, 'unit': 'crore', 'value': '200.00', 'currency': None}) == '200.00 crore'
    assert fr.value_text({'name': 'amount', 'number': 2e9, 'value': '200.00', 'unit': 'crore'}) == '200.00 crore'
    assert fr.value_text({'name': 'price_per_share', 'number': 165.65, 'value': '165.65', 'currency': 'INR'}) == '₹165.65'


def test_card_leads_with_its_checked_headline_and_points_and_shows_our_own_change():
    headline = {'text': 'Shivam Autotech sets Rs 120 Cr rights issue at Rs 12 a share', 'quote': 'up to Rs 12,000 Lakhs',
                'evidence': 'exact', 'shown': True}
    points = [{'text': 'Up to 10 Cr shares at Rs 12, record date October 15, 2026.', 'quote': 'q', 'evidence': 'exact', 'shown': True},
              {'text': 'A point the checks held back', 'quote': 'x', 'shown': False, 'reason': 'a number not in its quote'}]
    metrics = [{'label': 'Sales (Commercial Vehicles)', 'period': 'Sep 2026', 'value': '1071', 'unit': 'units',
                'number': 1071, 'quote': '1071', 'evidence': 'table', 'shown': True, 'change_pct': 31.9}]
    prices = {'market_cap': 2.23e9, 'mcap_bucket': 'Small'}
    days = pd.date_range('2025-10-01', '2026-10-13', freq='D')
    hist = {'INE1': (days.to_numpy(), [100.0] * (len(days) - 7) + [110.0] * 7)}
    html = fr.card_html(row(isin='INE1', headline=json.dumps(headline), points=json.dumps(points),
                            metrics=json.dumps(metrics)), prices, hist)
    assert '<h4 class="rc-h">Shivam Autotech sets Rs 120 Cr rights issue at Rs 12 a share</h4>' in html
    assert '<b>10 Cr</b> shares at <b>Rs 12</b>' in html and 'A point the checks held back' not in html.split('<details')[0]
    assert 'Sales (Commercial Vehicles) (Sep 2026)' in html and '+31.9% YoY' in html
    assert 'Smallcap' in html and '₹223' in html and '1Y <b class="up">+10.0%</b>' in html
    assert 'Key terms' in html and 'Price a share' in html and '2 readers agree' in html
    assert "The filing's own words" in html.replace('&#x27;', "'") and 'a number not in its quote' in html


def test_an_older_read_without_a_headline_still_gets_a_plain_one():
    html = fr.card_html(row())
    assert '<h4 class="rc-h">Hyundai Motor India Ltd: capacity / investment, USD 15.50 bn</h4>' in html
