"""Every page renders without an exception on real cleaned data.

The data folder is built here from the real fixtures through the production
pipeline (insiders_clean.pipeline.run and the NSE events parsers), in the
same layout the site reads from R2."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from conftest import BSE_ROWS, FIXTURES, ROOT, RUN_DATE, canonical
from streamlit.testing.v1 import AppTest

from collectors.nse_events import parsers
from insiders_clean.calendar import seed_state
from insiders_clean.pipeline import run

APP_PATHS = f"""
import sys
sys.path.insert(0, r'{ROOT / "streamlit_app"}')
sys.path.insert(0, r'{ROOT}')
"""


@pytest.fixture(scope='module')
def data_dir(tmp_path_factory, real_nse_rows):
    root = tmp_path_factory.mktemp('site')
    cur = root / 'clean' / 'current'
    cur.mkdir(parents=True)
    deals = [{'event_date': '01/10/2026', 'security_code': '544717', 'security_name': 'CLEANMAX', 'company': 'CLEANMAX',
              'person': p, 'side': s, 'quantity': '100000', 'price': '1000', 'raw': []}
             for p, s in (('BIG BUYER FUND', 'BUY'), ('PROMOTER HOLDCO', 'SELL'))]
    vr = pd.read_csv(ROOT / 'reference_data' / 'security_master_20260901.csv', dtype=str, keep_default_na=False)
    tables, report = run({('nse', 'insider_trading'): canonical('nse', 'insider_trading', real_nse_rows),
                          ('bse', 'bulk_deals'): canonical('bse', 'bulk_deals', deals)},
                         RUN_DATE, seed_state(), vr_master=vr,
                         nse_lists=[pd.read_csv(FIXTURES / 'nse_equity_sample.csv', dtype=str)],
                         market_cap_rows=BSE_ROWS + [{'symbol': 'HCLTECH', 'market_cap': 4.0e12, 'source': 'pr_zip'},
                                                     {'symbol': 'ZEEL', 'market_cap': 6.9e10, 'source': 'pr_zip'}])
    ev = FIXTURES / 'nse_events'
    load = lambda n: json.loads((ev / n).read_text(encoding='utf-8'))
    # Trading window: a results meeting three days before the first open-market buy, through the real join.
    from insiders_clean import buybacks, trading_window
    from insiders_clean.calendar import Calendar
    t = tables['insider_trades']
    b = t[t['is_market'].astype(bool) & t['side'].eq('BUY') & t['nse_symbol'].notna()].iloc[0]
    meet = pd.DataFrame({'symbol': [b['nse_symbol']], 'results': [True], 'raw_json': ['[]'],
                         'meeting_date': [pd.Timestamp(b['trade_date_from'] or b['trade_date_to']) - pd.Timedelta(days=3)]})
    tables['insider_trades'] = trading_window.attach(
        t, meet, Calendar([d.date() for d in pd.bdate_range('2024-01-01', '2026-12-31')]))[0]
    for name, df in tables.items():
        if name != 'universe':   # fixture market caps cover few companies; the cutoff is tested in test_universe_filter_on_pages
            df.to_parquet(cur / f'{name}.parquet')
    acts = parsers.parse_corporate_actions(load('corporate_actions.json'))[0]
    tenders = parsers.parse_tender_offers(load('tender_offers_past.json')['data'], load('tender_offers_active.json'))
    bb = buybacks.build(tenders, parsers.parse_daily_buybacks(load('daily_buybacks.json')['data']), acts)[0]
    bb.loc[bb['symbol'] == 'INFY', 'isin'] = 'INE009A01021'
    bb.to_parquet(cur / 'buybacks.parquet')
    parsers.parse_sast(load('sast_reg29.json')).to_parquet(cur / 'sast.parquet')
    parsers.parse_corporate_actions(load('corporate_actions.json'))[0].to_parquet(cur / 'actions.parquet')
    parsers.parse_board_meetings(load('board_meetings.json'))[0].to_parquet(cur / 'meetings.parquet')
    sh = parsers.parse_shareholding_listing(load('shareholding_ZEEL.json'))
    sh['promoter_pledge_pct'] = 5.38
    sh.to_parquet(cur / 'shareholding.parquet')
    from test_issues import IN_P, LIST, frame as issue_frame, pref as issue_row

    from insiders_clean import issues as issue_clean
    pref_raw = issue_frame(issue_row('In-Principle', 1, isin='INE0V9N01017', posted='02-MAR-2026', **IN_P),
                           issue_row('Listing Stage', 2, isin='INE0V9N01017', posted='12-MAR-2026', **LIST),
                           issue_row('In-Principle', 5, isin='INE000000009', posted='09-OCT-2026', **IN_P))
    issue_clean.clean_issues(pref_raw, 'preferential')[0].to_parquet(cur / 'preferential.parquet')
    rights_raw = pd.DataFrame([{'canonical_event_id': 'r1', 'appId': '9', 'canonical_stage': 'Listing Stage',
                                'canonical_isin': 'INE0LXG01040', 'canonical_symbol': 'OLAELEC',
                                'canonical_company': 'OLA ELECTRIC MOBILITY LIMITED', 'sysDateTime': '09-OCT-2026',
                                'dtOfSubmission': '08-OCT-2026', 'offerPrice': '40', 'rightRatio': '1:5',
                                'ingested_at': '2026-10-10T02:01:03+00:00'},
                               {'canonical_event_id': 'r2', 'appId': '10', 'canonical_stage': 'Listing Stage',
                                'canonical_isin': 'INE860A01027', 'canonical_symbol': 'HCLTECH',
                                'canonical_company': 'HCL TECHNOLOGIES LIMITED', 'sysDateTime': '09-OCT-2026',
                                'dtOfSubmission': '08-OCT-2026', 'offerPrice': '1500', 'rightRatio': '1:10',
                                'ingested_at': '2026-10-10T02:01:03+00:00'}])
    issue_clean.clean_issues(rights_raw, 'rights')[0].to_parquet(cur / 'rights.parquet')
    # QIPs, allottees and filed lock-ins from the real further-issue fixtures, as scripts/clean_writer.py builds them
    import clean_writer
    from test_archive_and_writer import FakeR2, parquet
    from test_issue_filings import filings
    r2 = FakeR2()
    r2.objects['archive/nse_events/issues/year=2026.parquet'] = parquet(filings())
    extra, _ = clean_writer.issue_tables(r2)
    for name in ('preferential_lockins', 'preferential_allottees', 'qip', 'qip_allottees'):
        extra[name].to_parquet(cur / f'{name}.parquet')
    (root / 'clean' / 'report_local.json').write_text(json.dumps(report, default=str))
    (root / 'clean' / 'latest.json').write_text(json.dumps({'date': RUN_DATE, 'report': 'local'}))
    return root


PAGES = [('pages:today', {}), ('pages:insiders', {}), ('pages:deals', {}), ('pages:raises', {}), ('pages:risks', {}),
         ('pages:ownership', {}), ('pages:calendar', {}), ('filings_all', {}), ('investors', {}), ('capital_raises', {}),
         ('track_record', {}), ('data_status', {}), ('company', {'symbol': 'HCLTECH'}), ('company', {}),
         ('entity', {'id': 'vama-sundari-investments-delh'}), ('entity', {}), ('coming', {}), ('filings', {})]


@pytest.mark.parametrize(('screen', 'params'), PAGES, ids=[f'{s.replace(":", "-")}-{bool(p)}' for s, p in PAGES])
def test_page_renders(data_dir, monkeypatch, screen, params):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    code = APP_PATHS + f"""
import streamlit as st
for k, v in {params!r}.items():
    st.query_params[k] = v
from ui import theme
theme.inject()
import importlib
mod, _, fn = '{screen}'.partition(':')
getattr(importlib.import_module('screens.' + mod), fn or 'render')()
"""
    at = AppTest.from_string(code, default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value


def test_investor_page_renders_for_a_deal_client(data_dir, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    deals = pd.read_parquet(data_dir / 'clean' / 'current' / 'deals.parquet')
    deals = deals[deals['is_primary'].astype(bool) & deals['client_id'].notna()]
    if deals.empty:
        pytest.skip('no deals in the fixtures')
    cid = deals['client_id'].iloc[0]
    at = AppTest.from_string(APP_PATHS + f"""
import streamlit as st
st.query_params['id'] = {cid!r}
from ui import theme
theme.inject()
from screens import entity
entity.render()
""", default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value


def test_whole_app_renders_with_bar(data_dir, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_file(str(ROOT / 'streamlit_app' / 'app.py'), default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value


def test_pages_never_change_the_shared_tables(data_dir, monkeypatch):
    """store.table, store.prices and the page context hand every visitor the same frames, not copies
    (st.cache_resource, 22 Oct): after every page has run, each one still equals what it was."""
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    frames = "('trades', 'eligible', 'deals', 'securities', 'sast', 'actions', 'meetings', 'shareholding', 'preferential', 'rights', 'prices', 'results')"
    snap = AppTest.from_string(APP_PATHS + f"""
import sys
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from data import store
from screens import ctx as C
c = C.load()
names = [n for n in store.TABLES if n not in store.FRESH]
sys.__dict__['_shared_before'] = ({{n: store.table(n).copy() for n in names}}, {{f: getattr(c, f).copy() for f in {frames}}})
""", default_timeout=60)
    snap.run()
    assert not snap.exception, snap.exception[0].value
    for screen, params in PAGES:
        code = APP_PATHS + f"""
import streamlit as st
for k, v in {params!r}.items():
    st.query_params[k] = v
from ui import theme
theme.inject()
import importlib
mod, _, fn = '{screen}'.partition(':')
getattr(importlib.import_module('screens.' + mod), fn or 'render')()
"""
        at = AppTest.from_string(code, default_timeout=60)
        at.run()
        assert not at.exception, at.exception[0].value
    check = AppTest.from_string(APP_PATHS + f"""
import sys
import streamlit as st
from data import store
from screens import ctx as C
tables, ctx_frames = sys.__dict__.pop('_shared_before')
c = C.load()
changed = [n for n, df in tables.items() if not store.table(n).equals(df)]
changed += ['ctx.' + f for f, df in ctx_frames.items() if not getattr(c, f).equals(df)]
st.write('changed: ' + ','.join(changed) + '|' + str(len(tables)))
""", default_timeout=60)
    check.run()
    assert not check.exception, check.exception[0].value
    out = [m.value for m in check.markdown if m.value.startswith('changed')]
    assert out and out[0].split('|')[0] == 'changed: ' and int(out[0].split('|')[1]) > 10, out


def test_company_board_survives_two_symbols_on_one_isin(real_nse_rows, master, calendar, report):
    """Seen on real data: two shareholding rows with one ISIN broke the
    Screener (pandas InvalidIndexError on the pledge lookup)."""
    from insiders_clean import signals
    from insiders_clean.insider import clean_insider
    t = signals.eligible(clean_insider(canonical('nse', 'insider_trading', real_nse_rows), master, calendar, report, RUN_DATE))
    sh = pd.DataFrame({'symbol': ['ZEEL', 'ZEEL-BE'], 'isin': ['INE256A01028', 'INE256A01028'],
                       'quarter_end': ['2026-06-30', '2026-06-30'], 'promoter_holding_pct': [3.99, 3.99],
                       'public_holding_pct': [96.01, 96.01], 'promoter_pledge_pct': [5.38, 5.38]})
    board = signals.company_board(t, None, sh, signals.as_of(t))
    assert not board.empty


def test_company_timeline_shows_issues_only_when_the_company_has_them(data_dir, monkeypatch):
    """One dossier, no tabs (21 Oct): an issue is a row in the timeline, with its own filter."""
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    html, kinds = {}, {}
    for sym in ('HCLTECH', 'ZEEL'):
        code = APP_PATHS + f"""
import streamlit as st
st.query_params['symbol'] = {sym!r}
from ui import theme
theme.inject()
from screens import company
company.render()
"""
        at = AppTest.from_string(code, default_timeout=60)
        at.run()
        assert not at.exception, at.exception[0].value
        assert not at.tabs
        html[sym] = ' '.join(e.proto.body for e in at.get('html'))
        kinds[sym] = {o.split(' · ')[0] for w in at.get('button_group') for o in w.options}
    assert 'Rights issue' in kinds['HCLTECH'] and 'Rights issue' not in kinds['ZEEL']
    assert {'Insider buy', 'Staff trade'} <= kinds['HCLTECH']   # designated persons apart from decision-makers (12 Nov)
    assert 'Rights issue' in html['HCLTECH']           # its row is drawn (on by default)
    h = html['HCLTECH']
    # redesign 12 Nov: the masthead (the preview waits for '.head h1'), the stat strip, the checks, the stories, the noise counted
    assert '<div class="head ds-head">' in h and '<div class="ds-stats">' in h and 'Over 12 months promoters' in h
    for part in ('>Checks before acting<', '>What did insiders do?<', '>Who owns it?<', '>Every filing<', '>Price and every decision<'):
        assert part in h, part
    for check in ('Pledge', 'Promoter sales', 'Late filings', 'Tradability'):
        assert f'<dt>{check}</dt>' in h, check
    assert 'class="ds-story"' in h and 'class="ds-lede"' in h and 'class="ds-facts"' in h     # a news line and its numbers
    assert 'class="co"' not in h.split('>What did insiders do?<')[1].split('Left out as noise')[0]   # no name repeated on its own page
    assert 'Left out as noise' in h and 'designated persons' in h                            # 37 staff trades counted, not listed


def test_window_open_buy_is_marked_and_buybacks_show_price_and_route(data_dir, monkeypatch):
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    out = {}
    for screen in ('filings_all', 'capital_raises'):
        at = AppTest.from_string(APP_PATHS + f"""
import streamlit as st
st.session_state.setdefault('fa_days', max(__import__('screens.filings_all', fromlist=['x']).PERIODS))   # the fixture's trades are older than 30 days
from ui import theme
theme.inject()
from screens import {screen}
{screen}.render()
""", default_timeout=60)
        at.run()
        assert not at.exception, at.exception[0].value
        out[screen] = ' '.join(e.proto.body for e in at.get('html'))  # tables are drawn in the page (st.html)
    assert 'after the trading window reopened' in out['filings_all']
    assert 'Tender offer' in out['capital_raises'] and 'Open market' in out['capital_raises'] and '₹1,800' in out['capital_raises']


def test_universe_filter_on_pages(data_dir, monkeypatch, tmp_path):
    """With a universe table, every page drops companies under Rs 100 Cr (insiders_clean/universe.py)."""
    import shutil
    root = tmp_path / 'site'
    shutil.copytree(data_dir, root)
    cur = root / 'clean' / 'current'
    t = pd.read_parquet(cur / 'insider_trades.parquet')
    isins = list(t['isin'].dropna().unique())
    keep, drop = isins[0], isins[1:]
    pd.DataFrame({'isin': isins, 'market_cap': [500e7] + [10e7] * len(drop),
                  'in_universe': [True] + [False] * len(drop)}).to_parquet(cur / 'universe.parquet')
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(root))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()   # earlier tests cached tables from a folder without a universe
from data import store
import pandas as pd
st_t = store.table('insider_trades')
all_t = pd.read_parquet(store._local() / 'clean' / 'current' / 'insider_trades.parquet')
import streamlit as st
st.write(f'{st_t["isin"].nunique()}|{all_t["isin"].nunique()}')
""", default_timeout=60)
    at.run()
    assert not at.exception
    shown, everything = at.markdown[0].value.split('|')
    assert shown == '1' and int(everything) == len(isins) > 1


def test_old_addresses_redirect():
    """The retired pages (Market, Actions, Morning brief, Screener, Shareholding, Insider trades, Deals, Other
    filings, Capital raises; 21-22 Oct) are gone; their addresses lead to Today or Filings."""
    import re
    app = (ROOT / 'streamlit_app' / 'app.py').read_text(encoding='utf-8')
    for old in ('market', 'actions', 'brief', 'screener', 'shareholding'):
        assert re.search(rf"'{old}': 'Today'", app), old
    # 12 Nov: insider trades, deals and capital raises have their own pages again; other filings stay in Filings
    assert re.search(r"'insider-trades': 'Insiders'", app) and re.search(r"'capital-raises': 'Raises'", app)
    assert re.search(r"'other-filings': 'Filings'", app) and "url_path='deals'" in app


def test_in_app_links_map_to_pages_with_their_query():
    """ui/nav.py: a link the pages draw goes to its page, query kept; any other path is left alone."""
    import sys
    sys.path.insert(0, str(ROOT / 'streamlit_app'))
    from ui import nav
    pages = {'': 'TODAY', 'company': 'COMPANY', 'filings-all': 'FILINGS'}
    assert nav.target('/company?symbol=HCLTECH#1792634659117', pages) == ('COMPANY', {'symbol': 'HCLTECH'})
    assert nav.target('/filings-all', pages) == ('FILINGS', {})
    assert nav.target('/', pages) == ('TODAY', {})
    assert nav.target('/elsewhere?x=1', pages) is None and nav.target(None, pages) is None


def test_a_promoter_deal_with_no_filing_does_not_take_the_measured_promoter_read():
    from insiders_clean import ideas
    assert ideas.PROMOTER_DEAL_BUY not in ideas.MEASURED_BY and ideas.PROMOTER_DEAL_SELL not in ideas.MEASURED_BY
    assert ideas.PROMOTER_DEAL_BUY in dict(ideas.GROUPS['look'])['Insiders buying']
    assert ideas.PROMOTER_DEAL_SELL in dict(ideas.GROUPS['warn'])['Insiders selling']


def _page_html(data_dir, monkeypatch, fn: str, period: str = '90 days') -> str:
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_string(APP_PATHS + f"""
from ui import theme
theme.inject()
from screens import pages
pages.{fn}()
""", default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else ''
    for w in at.get('button_group'):
        if period in getattr(w, 'options', []):
            w.set_value(period)
            at.run()
            break
    return ' '.join(e.proto.body for e in at.get('html'))


def test_insiders_page_is_5w2h_with_the_noise_clubbed(data_dir, monkeypatch):
    """Redesign 12 Nov: each decision a story with its 5W-2H; staff trades and ESOPs counted at the foot, not listed."""
    h = _page_html(data_dir, monkeypatch, 'insiders')
    assert '<div class="head ds-head">' in h and 'Insider trades' in h and '<div class="ds-stats">' in h
    assert '>Who is buying?<' in h and '>Who is selling?<' in h
    assert 'Left out as noise' in h
    assert 'designated persons, employees and relatives' in h or 'ESOP' in h


def test_deals_page_shows_both_sides_as_one_deal(data_dir, monkeypatch):
    """The fixture's CLEANMAX deal: BIG BUYER FUND bought and PROMOTER HOLDCO sold the same shares the same day; one story."""
    h = _page_html(data_dir, monkeypatch, 'deals', '90 days')
    assert '>Who sold, who took it?<' in h
    if 'class="ds-story"' in h:
        story = h.split('class="ds-story"')[1]
        assert 'Sold:' in story and 'Bought:' in story


def test_today_shows_the_top_of_every_topic(data_dir, monkeypatch):
    h = _page_html(data_dir, monkeypatch, 'today')
    order = ['Worth a look now', 'Who is selling?', 'Who sold, who took it?', 'Who is raising or returning money?',
             'What could go wrong?', 'Who are the big holders moving?', 'What is coming up?']
    at = [h.index(f'>{x}<') for x in order]
    assert at == sorted(at)
    for href in ('/insiders', '/deals', '/raises', '/risks', '/ownership', '/calendar'):
        assert f'href="{href}"' in h, href
