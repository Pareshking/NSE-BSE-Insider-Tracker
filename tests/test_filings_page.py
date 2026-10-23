"""The Filings page (streamlit_app/screens/filings_all.py): every filing and deal in one list.

Runs on the real-data fixture folder of tests/test_ui_pages.py, with an exchange copy of an insider
filing, of a deal and of a SAST disclosure added (each must show once), a pledge filing and a
BSE-only SAST disclosure."""
from __future__ import annotations

import json
import shutil

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from test_ui_pages import APP_PATHS, data_dir  # noqa: F401  (data_dir is the module fixture)

PLEDGER = 'Pledge Test Holder'
BSE_ONLY = 'BSE Only Acquirer'


@pytest.fixture(scope='module')
def site(data_dir, tmp_path_factory):  # noqa: F811
    root = tmp_path_factory.mktemp('filings') / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    t = pd.read_parquet(cur / 'insider_trades.parquet')
    base = t[t['kind'].eq('off_market')].iloc[0]
    t.loc[t['trade_id'] == base['trade_id'], 'listed_on'] = 'bse,nse'
    copy = base.copy()
    copy[['trade_id', 'exchange', 'is_primary', 'primary_id']] = ['bsecopy0000001', 'bse', False, base['trade_id']]
    pledge = t[t['kind'].eq('gift')].iloc[0].copy()
    pledge[['trade_id', 'kind', 'mode_raw', 'person_name', 'person_id', 'is_market']] = \
        ['pledge00000001', 'pledge_create', 'Pledge', PLEDGER, 'pledge-test-holder', False]
    pd.concat([t, pd.DataFrame([copy, pledge])], ignore_index=True).to_parquet(cur / 'insider_trades.parquet')
    d = pd.read_parquet(cur / 'deals.parquet')
    dc = d.iloc[0].copy()
    dc[['deal_id', 'exchange', 'is_primary', 'primary_id']] = ['nsecopy0000001', 'nse', False, d.iloc[0]['deal_id']]
    pd.concat([d, pd.DataFrame([dc])], ignore_index=True).to_parquet(cur / 'deals.parquet')
    s = pd.read_parquet(cur / 'sast.parquet')
    on_nse = s.iloc[[0]].assign(event_id='bse-on-nse', on_nse=True, listed_on='bse')
    only = s.iloc[[1]].assign(event_id='bse-only', on_nse=False, listed_on='bse', acquirer_name=BSE_ONLY,
                              acquirer_id='bse-only-acquirer')
    pd.concat([on_nse, only], ignore_index=True).to_parquet(cur / 'bse_sast.parquet')
    return root


def _run(site, monkeypatch, kind: str | None = None, days: int = 365) -> tuple[AppTest, str]:
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(site))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()   # other tests cached tables from another folder
from ui import theme
theme.inject()
from screens import filings_all
filings_all.render()
""", default_timeout=90)
    at.session_state['fa_days'] = days
    if kind:
        at.session_state['fa_kind'] = kind
    at.run()
    assert not at.exception, at.exception[0].value
    return at, ' '.join(e.proto.body for e in at.get('html'))


def test_every_kind_is_listed_and_rows_open(site, monkeypatch):
    at, html = _run(site, monkeypatch)
    for words in ('Open market', 'ESOP', 'Gift', 'Off-market transfer', 'Bulk deal', 'Stake moved 2% or more',
                  'Stake crossed 5%', 'Preferential issue', 'Rights issue', 'QIP', 'Buyback', 'Split'):
        assert f'>{words}<' in html, words
    assert BSE_ONLY in html                               # BSE's SAST rows NSE has not got
    assert '<template>' in html and 'dt-grid' in html     # every row opens to its facts (drawn on the first open)
    assert 'Shares' in html and 'Holding before' in html and 'Made public' in html
    labels = {o.split(' · ')[0]: int(o.split(' · ')[1].replace(',', '')) for o in at.pills(key='fa_kind').options}
    assert all(labels[k] > 0 for k in labels), labels
    _, pledges = _run(site, monkeypatch, 'Pledges')
    assert PLEDGER in pledges and '>Pledge created<' in pledges


def test_held_back_rows_only_under_their_pill_with_the_reason(site, monkeypatch):
    reason = 'Mode says buy, type says sell (or the reverse)'
    _, everything = _run(site, monkeypatch)
    assert reason not in everything
    for kind in ('Insider trades', 'Other filings', 'Deals'):
        assert reason not in _run(site, monkeypatch, kind)[1]
    _, held = _run(site, monkeypatch, 'Held back')
    assert reason in held and 'mode says buy, type says sell' in held  # under What and in the facts


def test_a_filing_on_nse_and_bse_shows_once(site, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(site))
    at = AppTest.from_string(APP_PATHS + """
import json
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import filings_all
from screens.ctx import load
rows, sources = filings_all.build(load(), 365)
ins = sources['insider'].loc[rows.loc[rows['_src'] == 'insider', '_i']]
st.write(json.dumps({
    'dup_keys': int(rows.duplicated(['_src', '_i']).sum()),
    'insider_non_primary': int((~ins['is_primary'].astype(bool)).sum()),
    'deal_non_primary': int((~sources['deal'].loc[rows.loc[rows['_src'] == 'deal', '_i'], 'is_primary'].astype(bool)).sum()),
    'off_market': int(((rows['_src'] == 'insider') & (rows['what'] == 'Off-market transfer')).sum()),
    'sast_first': int((rows['_src'].eq('sast') & rows['who'].eq(sources['sast'].iloc[0]['acquirer_name'])
                       & rows['made_public'].eq(rows.loc[rows['_src'].eq('sast')].iloc[0]['made_public'])).sum()),
    'deals': int((rows['_src'] == 'deal').sum()),
}))
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    got = json.loads(at.markdown[0].value)
    assert got['dup_keys'] == 0 and got['insider_non_primary'] == 0 and got['deal_non_primary'] == 0
    assert got['off_market'] == 1        # the NSE filing; its BSE copy is not a second row
    assert got['deals'] == 2             # the two fixture deals; the NSE copy of one is not a third
    _, html = _run(site, monkeypatch, 'Other filings')
    assert 'ex-bse' in html              # the one row says it was filed on both exchanges


def test_converted_warrants_say_the_amount_is_the_balance():
    """Warrants are paid 25% at allotment and 75% on conversion: the listing record raises the balance."""
    from screens import filings_all
    x = {'instruments': 'Warrants', 'shares_allotted': 1_000_000, 'offer_price': 100.0, 'amount_raised': 75_000_000}
    assert 'Raised on conversion (the 75% balance on warrants)' in filings_all._issue_facts('pref', x, {})
    assert 'Raised on conversion' not in filings_all._issue_facts('pref', {**x, 'amount_raised': 100_000_000}, {})
    assert 'Raised on conversion' not in filings_all._issue_facts('pref', {**x, 'instruments': 'Equity shares'}, {})


# ---- the kinds of docs/DESIGN_V3.md: each its own columns ------------------------------------------

KIND_HEADERS = {
    'Insider trades': ('Price now vs trade', 'Own holding Δ', 'Mode as filed'),
    'Deals': ('Client', 'Other side', 'Price now vs deal'),
    'Stake changes': ('% of company moved', 'Stake after'),
    'Preferential': ('Shares go to', 'ICDR minimum', 'Offer vs minimum', 'Lock-in ends'),
    'Rights': ('Rights price', 'Record date', 'Closes'),
    'QIPs': ('Allottees', 'Floor price', 'Issue vs now'),
    'Buybacks': ('Route', 'Offer vs now', 'Tendered ×'),
    'Pledges': ('Promoter or insider', 'Holding after'),
    'Upcoming': ('Date', 'Detail'),
}


def test_each_kind_draws_its_own_columns(site, monkeypatch):
    for kind, headers in KIND_HEADERS.items():
        at, html = _run(site, monkeypatch, kind)
        assert '<th' in html, kind
        for h in headers:
            assert f'>{h}<' in html, (kind, h)


def test_every_row_is_under_exactly_one_kind(site, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(site))
    at = AppTest.from_string(APP_PATHS + """
import json
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import filings_all
from screens.ctx import load
rows, _ = filings_all.build(load(), 365)
kinds = [k for k in filings_all.KINDS if k not in ('All', 'Held back')]
under = sum(filings_all.in_kind(rows, k).astype(int) for k in kinds)
held = rows['held']
st.write(json.dumps({'n': len(rows), 'bad': int(((under != 1) & ~held).sum()), 'held_in_a_kind': int(((under > 0) & held).sum()),
                     'all_has_upcoming': int((filings_all.in_kind(rows, 'All') & rows['group'].eq('Upcoming')).sum())}))
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    got = json.loads(at.markdown[0].value)
    assert got['n'] > 0
    assert got['bad'] == 0, got           # a row is under one kind; a deal that is an insider's own trade is under Deals only
    assert got['held_in_a_kind'] == 0     # held-back rows only under their pill
    assert got['all_has_upcoming'] == 0   # the money events ahead have their own pill


def test_upcoming_is_money_events_ahead_in_date_order(site, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(site))
    at = AppTest.from_string(APP_PATHS + """
import json
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from screens import filings_all
from screens.ctx import load
ctx = load()
rows, _ = filings_all.build(ctx, 7)          # the period chips are the past; Upcoming ignores them
up = rows[filings_all.in_kind(rows, 'Upcoming')]
ref = ctx.ref.normalize()
st.write(json.dumps({'n': len(up), 'what': sorted(set(up['what'])), 'earliest_ok': bool((up['made_public'] >= ref).all()),
                     'latest_ok': bool((up['made_public'] <= ref + __import__('pandas').Timedelta(days=filings_all.UPCOMING_DAYS)).all())}))
""", default_timeout=90)
    at.run()
    assert not at.exception, at.exception[0].value
    got = json.loads(at.markdown[0].value)
    assert got['n'] > 0 and got['earliest_ok'] and got['latest_ok']
    assert any(w.startswith('Board meets: ') for w in got['what']), got
    assert 'Lock-in ends' in got['what'] or 'Buyback tender closes' in got['what'], got


def test_company_cell_shows_size_price_and_52_week_position():
    from ui import kit, table
    row = {'nse_symbol': 'ABC', 'mk_bucket': 'Small', 'mk_cap': 2.4e10, 'mk_px': 2050.0, 'mk_lo': 1500.0, 'mk_hi': 2200.0,
           'listed_on': 'nse'}
    html = table._cell(kit.Col('company', 'Company', 'co2'), {**row, 'company': 'Abc Ltd'}, {})[0]
    assert 'Small' in html and '₹2,400 Cr' in html and '₹2,050' in html and 'rgm' in html and 'left:79%' in html
    assert 'ex-nse' not in html                                   # NSE-only is the default: no mark
    assert 'ex-bse' in table._cell(kit.Col('company', 'Company', 'co2'), {**row, 'company': 'Abc', 'listed_on': 'bse,nse'}, {})[0]
    big = table._cell(kit.Col('company', 'Company', 'co2'), {**row, 'company': 'Abc', 'mk_cap': 4.1e12}, {})[0]
    assert '₹4.1 L Cr' in big
    bare = table._cell(kit.Col('company', 'Company', 'co2'), {'nse_symbol': 'ABC', 'company': 'Abc'}, {})[0]
    assert 'class="mk"' not in bare                               # no price data: no empty line


def test_a_held_back_amount_shows_a_question_mark_with_the_reason():
    from ui import kit, table
    col = kit.Col('amount', 'Amount', 'amt', flag='why', sub='sub')
    shown = table._cell(col, {'amount': 5e8, 'why': '', 'sub': 'approved ₹9.00 Cr'}, {})[0]
    assert '₹50.00 Cr' in shown and 'qm' not in shown and 'approved ₹9.00 Cr' in shown
    held = table._cell(col, {'amount': float('nan'), 'why': 'fails the unit check', 'sub': 'shares × price ₹18.01 Cr'}, {})[0]
    assert 'class="qm"' in held and 'fails the unit check' in held and 'shares × price ₹18.01 Cr' in held


def test_price_now_vs_a_trade_is_coloured_for_a_buy_only():
    from ui import kit, table
    col = kit.Col('x', 'Now vs trade', 'vspct')
    assert table._cell(col, {'x': 8.0, 'side': 'BUY'}, {})[2].endswith('up')
    assert table._cell(col, {'x': 8.0, 'side': 'SELL'}, {})[2].strip() == 'r num'
    assert table._cell(col, {'x': -8.0, 'side': 'BUY'}, {})[2].endswith('down')
    assert table._cell(kit.Col('x', 'x', 'npct'), {'x': -8.0, 'side': 'BUY'}, {})[2].strip() == 'r num'


def test_amount_columns_hold_back_an_unreliable_filed_amount():
    import numpy as np
    import pandas as pd
    from screens import filings_all as f
    r = pd.DataFrame({'amount': [np.nan, 2.0e8, 3.0e8], 'amount_unreliable': [True, False, False],
                      'shares_allotted': [1_651_866, 1_000_000, 1_000_000], 'offer_price': [109.0, 200.0, 300.0],
                      'amount_total': [np.nan, 5.0e8, 3.0e8], 'amount_raised': [np.nan, 2.0e8, 3.0e8]})
    out = pd.DataFrame(index=r.index)
    f._amount_cols(r, out)
    assert out['amount_why'].iloc[0] == f.UNIT_WHY and out['amount_why'].iloc[1] == ''
    assert out['amount_sub'].iloc[0] == 'shares × price ₹18.01 Cr'     # the safe figure, not the filed one
    assert out['amount_sub'].iloc[1] == 'approved ₹50.00 Cr'            # raised 20 Cr of 50 Cr approved
    assert out['amount_sub'].iloc[2] == ''


def test_lock_in_end_is_the_filed_lines_else_the_rule():
    import pandas as pd
    from screens import filings_all as f
    lines = pd.DataFrame({'app_id': ['7', '7'], 'expires': pd.to_datetime(['2027-04-07', '2028-04-07'])})
    assert f._lock_end({'app_id': '7'}, lines) == ('07 Apr 2027 · 07 Apr 2028', 'as filed')
    got = f._lock_end({'app_id': '8', 'lock_in_other_until': pd.Timestamp('2027-04-07'),
                       'lock_in_promoter_until': pd.Timestamp('2028-04-07')}, lines)
    assert got[0] == '07 Apr 2027 · 07 Apr 2028' and got[1].startswith('rule')
    assert f._lock_end({'app_id': '9'}, lines) == ('', '')


def test_a_meeting_keeps_its_agenda_line_not_the_boilerplate():
    from screens import filings_all as f
    text = ('To consider Fund Raising and other business matters | RMC SWITCHGEARS LIMITED has informed the Exchange about '
            'Board Meeting to be held on 09-Oct-2026')
    assert f._meeting_detail(text) == 'To consider Fund Raising and other business matters'
    assert f._meeting_detail('X has informed the Exchange about a meeting') == 'X has informed the Exchange about a meeting'
    assert f._meeting_detail(None) == ''
