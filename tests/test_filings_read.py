"""The Brief's "Filings read" card (streamlit_app/screens/filings_read.py): only checked values, each with
its quote and evidence; held-back values counted with their reasons; nothing before the reader has data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
from screens import filings_read as fr  # noqa: E402

FIELDS = [
    {'name': 'price_per_share', 'value': '165.65', 'number': 165.65, 'quote': 'at the issue price of Rs. 165.65',
     'evidence': 'exact', 'shown': True, 'currency': 'INR'},
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
                          row(event_id='nse:7', status='same_file', same_as='nse:9', symbol='OTHER')])   # original not shown
    got = fr.recent(reads, pd.Timestamp('2026-10-12'))
    assert list(got['event_id']) == ['nse:1', 'nse:7']
    html = fr.card_html(got.iloc[0].to_dict())
    assert 'Also filed: <a href' in html and 'BSE 13 Oct, 10:09</a>' in html and 'NSE 13 Oct, 10:20 (General Updates)</a>' in html
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


def test_an_older_read_without_a_headline_uses_checked_category_and_terms():
    html = fr.card_html(row())
    assert '<h4 class="rc-h">Hyundai Motor India Ltd: capacity / investment' in html
    assert 'USD 15.50 bn size' in html and '₹165.65 a share' in html
    assert '<h4 class="rc-h">Press Release</h4>' not in html  # category badge may still say Press Release


def test_different_files_on_one_deal_are_one_card_and_other_deals_stay_apart():
    deal = [dict(FIELDS[1], number=809e6), dict(FIELDS[0], number=165.65)]
    other = [dict(FIELDS[1], number=95e6)]
    reads = pd.DataFrame([
        row(event_id='nse:1', subject='Press Release', fields=json.dumps(deal), shown=5),
        row(event_id='nse:2', subject='General Updates', fields=json.dumps(deal[:1]), shown=4,
            broadcast_at='2026-10-13T10:40:00+05:30', file_url='https://f/2.pdf'),
        row(event_id='nse:3', subject='Acquisition', fields=json.dumps(other), shown=1),          # another deal
        row(event_id='nse:4', subject='Press Release', fields=json.dumps(deal), category='qip'),  # another category
        row(event_id='nse:5', subject='Press Release', fields=json.dumps(deal), broadcast_date='2026-10-15',
            broadcast_at='2026-10-15T10:15:00+05:30')])                                          # two days later
    got = fr.recent(reads, pd.Timestamp('2026-10-12')).set_index('event_id')
    assert sorted(got.index) == ['nse:1', 'nse:3', 'nse:4', 'nse:5']
    assert [a['event_id'] for a in got.loc['nse:1', 'also_filed']] == ['nse:2']   # the one with more values leads
    html = fr.card_html(got.loc['nse:1'].to_dict() | {'event_id': 'nse:1'})
    assert 'href="https://f/2.pdf"' in html and '(General Updates)' in html

def test_before_this_is_built_from_our_own_tables_with_our_own_sums():
    deal = [dict(FIELDS[0], number=12.0, currency='INR'), dict(FIELDS[1], number=1.2e9, currency='INR')]
    r = row(isin='INE1', fields=json.dumps(deal), broadcast_at='2026-10-13T10:15:00+05:30', category='preferential')
    reads = pd.DataFrame([r, row(event_id='nse:0', isin='INE1', category='preferential', broadcast_at='2026-09-20T12:00:00+05:30',
                                 headline=json.dumps({'text': 'Board approves a preferential issue', 'shown': True})),
                          row(event_id='nse:9', isin='INE1', category='rights', broadcast_at='2026-05-01T12:00:00+05:30')])
    price = {'latest_close': 15.0, 'last_date': '2026-10-13', 'market_cap': 2.4e9}
    holding = {'promoter_holding_pct': 63.8, 'promoter_pledge_pct': 0.0, 'quarter_end': '2026-06-30'}
    insiders = pd.DataFrame([{'isin': 'INE1', 'side': 'BUY', 'value': 2.5e6, 'seen': pd.Timestamp('2026-10-01')},
                             {'isin': 'INE1', 'side': 'BUY', 'value': 1e6, 'seen': pd.Timestamp('2026-08-01')}])   # too old
    lines = fr.before_this(r, reads, price, holding, insiders)
    assert lines[0] == 'The price of <b>₹12.00</b> is <b>20.0%</b> below the last close of ₹15.00 (13 Oct).'
    assert lines[1] == "The size is <b>50.0%</b> of the company's market cap (₹240.00 Cr)."
    assert lines[2] == 'Promoters hold <b>63.8%</b> (30 Jun 2026), none of it pledged.'
    assert lines[3].startswith('Insiders bought <b>₹25.00 L</b>') and '1 filing' in lines[3]
    assert lines[4] == '20 Sep: Board approves a preferential issue.' and len(lines) == 5   # May is past 90 days
    assert 'Before this' in fr.card_html(r, price, None, lines)
    assert fr.before_this(row(), None, None, None, None) == []


def test_filings_page_filters_by_heading_size_search_and_agreement(tmp_path, monkeypatch):
    from screens import filings
    assert filings.heading_of('rights') == 'Fund raising' and filings.heading_of('acquisition') == 'Acquisitions & restructuring'
    assert filings.heading_of('something_new') == 'Other'   # a new category is never hidden
    assert filings.heading_of('legal_regulatory') == 'Legal & regulatory' and filings.heading_of('deal_or_dispute') == 'Other'
    now = pd.Timestamp.now(tz='Asia/Kolkata')
    at, day = now.isoformat(), now.strftime('%Y-%m-%d')
    reads = pd.DataFrame([row(event_id='nse:1', isin='A', category='rights', broadcast_at=at, broadcast_date=day),
                          row(event_id='bse:2', isin='B', exchange='BSE', symbol='AEGISLOG', company='Aegis Logistics',
                              category='acquisition', broadcast_at=at, broadcast_date=day, agreed='{}'),
                          row(event_id='nse:3', isin='C', category='capex', symbol='JUBLPHARMA', company='Jubilant',
                              broadcast_at=at, broadcast_date=day, fields=json.dumps([FIELDS[2]]), agreed='{}')])
    r = fr.recent(reads, now.tz_localize(None).normalize() - pd.Timedelta(days=7))
    size = {'A': 'Small', 'B': 'Mid', 'C': 'Large'}
    ids = lambda **kw: sorted(filings.pick(r, **{'headings': list(filings.HEADINGS), 'exchanges': ['NSE', 'BSE'],
                                                 'sizes': list(filings.SIZES), 'query': '', 'agreed_only': False,
                                                 'size_of': size, **kw})['event_id'])
    assert ids() == ['bse:2', 'nse:1', 'nse:3']
    assert ids(headings=['Fund raising']) == ['nse:1'] and ids(exchanges=['BSE']) == ['bse:2']
    assert ids(sizes=['Large']) == ['nse:3'] and ids(query='aegis') == ['bse:2'] and ids(agreed_only=True) == ['nse:1']
    cur = tmp_path / 'clean' / 'current'
    cur.mkdir(parents=True)
    reads.to_parquet(cur / 'announcement_reads.parquet')
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(tmp_path))
    st.cache_data.clear()   # the site caches tables by name: other tests' data must not leak in, nor this one's out
    st.cache_resource.clear()   # and the page context built from them (screens/ctx.py)
    at_ = AppTest.from_string(APP_PATHS + '''
import streamlit as st
st.query_params['h'] = 'Fund raising'
from ui import theme
theme.inject()
from screens import filings
filings.render()
''', default_timeout=60).run()
    assert not at_.exception, at_.exception[0].value
    st.cache_data.clear()
    st.cache_resource.clear()
    html = ' '.join(h.proto.body for h in at_.get('html'))
    assert html.count('<article class="rc">') == 1 and 'HYUNDAI' in html



def test_a_price_is_set_against_the_close_only_for_the_companys_own_shares():
    deal = [dict(FIELDS[0], number=937.5, currency='INR')]
    price = {'latest_close': 56.77, 'last_date': '2026-10-12', 'market_cap': 6.38e9}
    gtpl = row(isin='INE1', category='acquisition', fields=json.dumps(deal))   # the target's price (GTPL, 13 Oct)
    assert not any('last close' in x for x in fr.before_this(gtpl, None, price, None, None))
    own = row(isin='INE1', category='rights', fields=json.dumps(deal))
    assert any('last close' in x for x in fr.before_this(own, None, price, None, None))


def test_a_card_without_a_headline_uses_category_not_exchange_detail_and_keeps_bse_company_name():
    html = fr.card_html(row(symbol='541347', company='Parvati Sweetners and Power Ltd', subject='Acquisition',
                            category='acquisition', fields='[]',
                            detail='Acquisition of 51% stake in Shree Parvati Agro Pvt Ltd for Rs 2 crore',
                            metrics=json.dumps([{'label': 'amount awarded', 'number': 2.566e8, 'value': '25.66', 'unit': 'crore',
                                                 'currency': 'INR', 'quote': 'q', 'shown': True}])))
    assert '<h4 class="rc-h">Parvati Sweetners and Power Ltd: acquisition</h4>' in html
    assert 'Acquisition of 51% stake in Shree Parvati Agro Pvt Ltd' not in html
    assert '>Parvati Sweetners and Power Ltd</a>' in html and '>541347<' not in html
    assert '<td>Amount awarded</td>' in html


def test_exchange_boilerplate_headline_is_replaced_by_checked_category():
    headline = {'text': 'Madhav Infra Projects Ltd: Submission of Board Meeting Outcome for Board Meeting held today',
                'shown': True, 'quote': 'Submission of Board Meeting Outcome'}
    html = fr.card_html(row(symbol='MADHAVIPL', company='Madhav Infra Projects Ltd', category='preferential',
                            fields='[]', headline=json.dumps(headline),
                            detail='Submission of Board Meeting Outcome for Board Meeting held today'))
    assert '<h4 class="rc-h">Madhav Infra Projects Ltd: preferential issue</h4>' in html
    assert 'Submission of Board Meeting Outcome' not in html



def test_every_category_of_the_live_reader_has_a_label_and_a_heading():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import announcement_reader as ar
    from screens import filings
    shown = set(ar.CATEGORIES) - {'routine'}
    assert shown <= set(fr.CATEGORY), shown - set(fr.CATEGORY)
    assert all(filings.heading_of(c) != filings.OTHER for c in shown), [c for c in shown if filings.heading_of(c) == 'Other']


def test_a_bse_file_older_than_two_days_links_to_the_history_path_and_the_rest_keep_their_link():
    live = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/a.pdf'
    now = pd.Timestamp('2026-10-15 18:00', tz='UTC')   # 15 Oct 23:30 IST
    link = fr.filing_link
    assert link(live, '2026-10-12T10:00:00+05:30', now) == live.replace('AttachLive', 'AttachHis')   # 3 days
    assert link(live, '2026-10-13T10:00:00+05:30', now) == live                                      # 2 days
    assert link(live, '2026-10-15T10:00:00+05:30', now) == live
    nse = 'https://nsearchives.nseindia.com/corporate/X.pdf'
    assert link(nse, '2026-01-01T10:00:00+05:30', now) == nse
    assert link(None, '2026-01-01T10:00:00+05:30', now) == '' and link(live, None, now) == live
    already = live.replace('AttachLive', 'AttachHis')
    assert link(already, '2026-01-01T10:00:00+05:30', now) == already
    # the boundary is in IST: a filing at 00:30 IST on 13 Oct is still 2 days old at 23:30 IST on 15 Oct
    assert link(live, '2026-10-13T00:30:00+05:30', now) == live


def test_coverage_counts_what_was_read_in_full_and_names_why_the_rest_was_not():
    reads = pd.DataFrame({
        'broadcast_date': ['2026-10-14'] * 9 + ['2026-09-01'],
        'status': ['read', 'same_file', 'same_filing_other_exchange', 'no_text', 'not_read', 'failed', 'failed',
                   'below_100_cr', 'quota_deferred', 'read']})
    c = fr.coverage(reads, pd.Timestamp('2026-10-10'))
    assert c == {'looked_at': 9, 'in_full': 3, 'below_500_cr': 1, 'sme_excluded': 0,
                 'not_read': {'no text layer': 1, 'longer than the reader limit': 1, 'could not be downloaded': 2,
                              'waiting for model capacity': 1}}
    html = fr.coverage_html(c)
    assert 'Of 9 filings' in html and '<b>3</b> read in full' in html and '<b>5</b> not read' in html
    assert '2 could not be downloaded' in html and 'never summarised from a part' in html
    assert fr.coverage(pd.DataFrame(), pd.Timestamp('2026-10-10')) == {} and fr.coverage_html({}) == ''


def test_a_checked_subtitle_sits_under_the_headline_and_a_held_one_is_not_shown():
    sub = {'text': 'Up to 6.32 crore equity shares', 'quote': 'up to 6,32,00,000 equity shares', 'evidence': 'exact', 'shown': True}
    headline = {'text': 'Ujjivan SFB approves ₹409 Cr preferential issue', 'quote': 'q', 'evidence': 'exact', 'shown': True, 'subtitle': sub}
    html = fr.card_html(row(headline=json.dumps(headline), points='[]'))
    assert '<h4 class="rc-h">Ujjivan SFB approves ₹409 Cr preferential issue</h4><p class="rc-sub">Up to 6.32 crore equity shares</p>' in html
    held = dict(headline, subtitle=dict(sub, shown=False, reason='a number not in its quote'))
    assert 'rc-sub' not in fr.card_html(row(headline=json.dumps(held), points='[]')).split('<details')[0]


def test_before_this_sets_the_size_against_the_last_full_year_from_the_results_table():
    import pandas as pd
    results = pd.DataFrame([{'isin': 'INE1', 'period_end': '2026-03-31', 'consolidated': 'Consolidated', 'ytd_revenue': 5.0e9,
                             'ytd_total_income': 5.1e9, 'ytd_profit': 1e8, 'broadcast_at': '2026-05-10'}])
    r = {'isin': 'INE1', 'symbol': 'X', 'category': 'order_win', 'broadcast_at': '2026-10-16T10:00:00+05:30',
         'fields': '[{"name": "amount", "shown": true, "number": 1.495e9, "currency": "INR"}]'}
    lines = fr.before_this(r, None, None, None, None, results)
    assert any('FY26 revenue' in x and '29.9%' in x and 'consolidated' in x for x in lines)
    assert not any('FY26' in x for x in fr.before_this({**r, 'category': 'management_change'}, None, None, None, None, results))
    assert not any('FY26' in x for x in fr.before_this(r, None, None, None, None, None))


def test_a_results_card_without_a_headline_leads_with_its_own_figures():
    html = fr.card_html(row(symbol='INDIACEM', company='The India Cements Limited', category='business_update', fields='[]',
                            metrics=json.dumps([{'label': 'Revenue from Operations', 'period': 'Q2FY27', 'number': 1.142e10, 'value': '1,142', 'unit': 'crore',
                                                 'currency': 'INR', 'quote': 'q', 'shown': True},
                                                {'label': 'PAT (12-13)', 'period': 'Q2FY27', 'number': 3.9e8, 'value': '39', 'unit': 'crore',
                                                 'currency': 'INR', 'quote': 'q', 'shown': True}])))
    assert 'The India Cements Limited Q2FY27: Revenue from Operations' in html and 'business update</h4>' not in html
    assert '(12-13)' not in html


def test_a_results_card_before_this_gives_the_previous_quarters_growth_not_the_promoter_holding():
    import pandas as pd
    results = pd.DataFrame([
        {'isin': 'INE1', 'period_end': '2025-06-30', 'consolidated': 'Consolidated', 'quarter_revenue': 1.0e10, 'quarter_profit': 1.0e9, 'broadcast_at': '2025-08-01T10:00:00Z'},
        {'isin': 'INE1', 'period_end': '2026-06-30', 'consolidated': 'Consolidated', 'quarter_revenue': 1.27e10, 'quarter_profit': 1.31e9, 'broadcast_at': '2026-08-01T10:00:00Z'}])
    r = {'isin': 'INE1', 'symbol': 'KROSS', 'category': 'financial_results', 'broadcast_at': '2026-10-17T12:00:00Z', 'fields': '[]', 'event_id': 'x'}
    holding = {'promoter_holding_pct': 68.6, 'promoter_pledge_pct': 0.0, 'quarter_end': pd.Timestamp('2026-09-30')}
    lines = fr.before_this(r, None, None, holding, None, results)
    assert any('Q1 FY27 also posted sales growth of <b>27%</b> and profit growth of <b>31%</b>' in x for x in lines)
    assert not any('Promoters hold' in x for x in lines)
    other = fr.before_this({**r, 'category': 'order_win'}, None, None, holding, None, results)
    assert any('Promoters hold' in x for x in other) and not any('also posted' in x for x in other)


def test_pages_hold_50_or_100_cards_and_return_to_the_first_when_filters_change(monkeypatch):
    import streamlit as st
    from screens import filings
    state = {}
    monkeypatch.setattr(st, 'session_state', state)
    assert filings.page_of(230, ('a',)) == (50, 0, 5)
    state['fl_page'] = 3
    assert filings.page_of(230, ('a',)) == (50, 3, 5)         # same filters: the page stays
    assert filings.page_of(230, ('b',)) == (50, 0, 5)         # other filters: back to the first
    state['fl_page'], state['fl_size'] = 4, 100
    assert filings.page_of(230, ('b',)) == (100, 0, 3)        # another page size starts again
    state['fl_page'] = 9
    assert filings.page_of(60, ('b',)) == (100, 0, 1)         # a short list has one page


def test_cards_html_preindexes_company_history_instead_of_passing_the_full_archive(monkeypatch):
    # A large archive with many issuers should give each card only its own pre-sorted history slice.
    from types import SimpleNamespace
    reads = pd.DataFrame([
        row(event_id=f'nse:{i}', symbol=f'SYM{i % 2}', isin=None,
            broadcast_at=f'2026-10-{13 - (i % 3):02d}T10:15:00+05:30')
        for i in range(120)
    ])
    cards = reads[reads['event_id'].isin(['nse:0', 'nse:1'])].copy()
    observed = []
    original = fr.before_this

    def spy(item, company_reads, price, holding, insiders, results=None, reads_sorted=False, reads_prepared=False):
        observed.append((len(company_reads), reads_sorted, reads_prepared, '_broadcast_at_utc' in company_reads))
        return original(item, company_reads, price, holding, insiders, results, reads_sorted=reads_sorted, reads_prepared=reads_prepared)

    monkeypatch.setattr(fr, 'before_this', spy)
    html = fr.cards_html(cards, reads, ctx=SimpleNamespace())
    assert html.count('<article class="rc">') == 2
    assert len(observed) == 2
    assert all(n == 60 and sorted_ and prepared and parsed for n, sorted_, prepared, parsed in observed)
    assert all(n < len(reads) for n, _, _, _ in observed)
