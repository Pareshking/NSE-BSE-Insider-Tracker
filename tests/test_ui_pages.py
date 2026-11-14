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
         ('pages:ownership', {}), ('pages:calendar', {}), ('more_pages:watchlist', {}), ('more_pages:watchlist', {'watch': 'HCLTECH,ZEEL,NOPE'}),
         ('more_pages:screener', {}), ('more_pages:sectors', {}), ('more_pages:results', {}), ('filings_all', {}), ('investors', {}), ('capital_raises', {}),
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
    # redesign 12 Nov: the masthead (the preview waits for '.head h1'), the stat strip, the checks; 13 Nov (R8): insiders,
    # deals and stakes as the dense tables of the topic pages, without a Company column on the company's own page
    assert '<div class="head ds-head">' in h and 'class="ds-kpis' in h
    for part in ('>Checks before acting<', '>Insider decisions <', '>Bulk and block deals <', '>Stake changes <',
                 '>Who owns it?<', '>Every filing<', '>Price and every decision<'):
        assert part in h, part
    for check in ('Pledge', 'Promoter sales', 'Late filings', 'Tradability'):
        assert f'<dt>{check}</dt>' in h, check
    ins = h.split('>Insider decisions <')[1].split('>Bulk and block deals <')[0]
    assert '<table class="dt' in ins and 'class="ev"' in ins and '>Company<' not in ins   # a dense row with its evidence, no name repeated


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
    for old in ('market', 'actions', 'brief', 'shareholding'):   # 'screener' is a page again (12 Nov)
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
    assert '<div class="head ds-head">' in h and 'Insider trades' in h and 'class="ds-kpis' in h
    assert '>Who is buying?<' in h and '>Who is selling?<' in h
    assert 'class="ds-club"' in h
    assert 'designated persons, employees and relatives' in h or 'ESOP' in h


def test_deals_page_shows_both_sides_as_one_deal(data_dir, monkeypatch):
    """The fixture's CLEANMAX deal: BIG BUYER FUND bought and PROMOTER HOLDCO sold the same shares the same day; one story."""
    h = _page_html(data_dir, monkeypatch, 'deals', '90 days')
    assert '>Who sold, who took it?<' in h
    if 'class="ds-story"' in h:
        story = h.split('class="ds-story"')[1]
        assert 'Sold:' in story and 'Bought:' in story


def test_today_shows_the_top_of_every_topic(data_dir, monkeypatch):
    """Minimal theme (12 Nov): four numbers, then cards: the shortlist, coming up, selling, deals, raises, risks, holders."""
    h = _page_html(data_dir, monkeypatch, 'today')
    assert h.count('class="kpi"') == 4
    order = ['Worth a look', 'Coming up', 'Selling', 'Big deals', 'Raises', 'Risks', 'Big holders']
    at = [h.index(f'>{x}</h2>') for x in order]
    assert at == sorted(at)
    for href in ('/insiders', '/deals', '/raises', '/risks', '/ownership', '/calendar'):
        assert f'href="{href}"' in h, href


def _more_html(data_dir, monkeypatch, fn: str, params: dict | None = None) -> str:
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_string(APP_PATHS + f"""
import streamlit as st
for k, v in {(params or {})!r}.items():
    st.query_params[k] = v
from ui import theme
theme.inject()
from screens import more_pages
more_pages.{fn}()
""", default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else ''
    return ' '.join(e.proto.body for e in at.get('html'))


def test_watchlist_reads_the_address_and_names_what_it_does_not_know(data_dir, monkeypatch):
    """12 Nov: the list lives in the page address (?watch=), never stored by the site; an unknown symbol is said."""
    h = _more_html(data_dir, monkeypatch, 'watchlist', {'watch': 'HCLTECH,NOPE'})
    assert '2 companies on your list' in h
    assert 'NOPE: not a symbol in our data' in h
    empty = _more_html(data_dir, monkeypatch, 'watchlist')
    assert 'Type the NSE symbols' in empty


def test_screener_presets_and_risks_red_flags_and_lenders(data_dir, monkeypatch):
    from screens import more_pages
    assert list(more_pages.PRESETS)[0] == 'Promoters buying, funds adding' and 'Trap: selling and pledging' in more_pages.PRESETS
    import pandas as pd
    snap = pd.DataFrame({'promoter_buy_90d': [1e7, 0, 1e7], 'mf_change_pts': [0.5, 2, -1], 'fpi_change_pts': [0, 0, 0],
                         'pledge': [0, 0, 20], 'insider_buy_90d': [1e7, 0, 1e7], 'range_pos': [10, 50, 90],
                         'promoter_change_pts': [0.6, 0.01, 0], 'promoter_sell_90d': [0, 0, 5e7], 'pledge_change_pts': [0, 0, 1]})
    pick = lambda k: more_pages.PRESETS[k][1](snap).fillna(False).tolist()  # noqa: E731
    assert pick('Promoters buying, funds adding') == [True, False, False]
    assert pick('Insiders buying near the low') == [True, False, False]
    assert pick('Funds piling in') == [False, True, False]
    assert pick('Trap: selling and pledging') == [False, False, True]
    assert pick('Promoters raising their stake') == [True, False, False]   # 0.01 point is noise
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_string(APP_PATHS + """
from ui import theme
theme.inject()
from screens import pages
pages.risks()
""", default_timeout=60)
    at.run()
    assert not at.exception
    h = ' '.join(e.proto.body for e in at.get('html'))
    assert '>Red flags<' in h and '>Who lends against promoter shares?<' in h


def test_results_and_sectors_pages_say_their_limits(data_dir, monkeypatch):
    h = _more_html(data_dir, monkeypatch, 'results')
    assert 'a dash where it does not' in h and '>Who bought right after their own results?<' in h and 'Exploratory' in h
    s = _more_html(data_dir, monkeypatch, 'sectors')
    assert 'Sectors' in s


def test_lenders_without_an_isin_column():
    """Site preview 12 Nov: the real encumbrances table carried no `isin`; the lenders table keys on the symbol then."""
    import sys
    from types import SimpleNamespace
    sys.path.insert(0, str(ROOT / 'streamlit_app'))
    import pandas as pd
    from screens import more_pages
    enc = pd.DataFrame({'lender': ['ABC Finance', 'ABC Finance', None], 'symbol': ['AAA', 'BBB', 'AAA'],
                        'event_type': ['Creation', 'Invocation', 'Release'], 'broadcast_date': pd.to_datetime(['2026-11-10'] * 3)})
    out = more_pages.lenders(SimpleNamespace(encumbrances=enc, ref=pd.Timestamp('2026-11-11')), 30)
    abc = out[out['lender'] == 'ABC Finance'].iloc[0]
    assert abc['companies'] == 2 and abc['created'] == 1 and abc['invoked'] == 1 and 'not named' in set(out['lender'])


def test_profile_and_screenshot_scripts_name_pages_that_exist():
    import importlib
    import re
    import sys
    sys.path.insert(0, str(ROOT / 'streamlit_app'))
    sys.path.insert(0, str(ROOT))
    prof = (ROOT / 'scripts' / 'site_profile.py').read_text(encoding='utf-8')
    for screen in re.findall(r"\('([a-z_:]+)', \{", prof.split('PAGES = ')[1].split(']')[0]):
        mod, _, fn = screen.partition(':')
        assert hasattr(importlib.import_module('screens.' + mod), fn or 'render'), screen
    app = (ROOT / 'streamlit_app' / 'app.py').read_text(encoding='utf-8')
    shots = (ROOT / 'scripts' / 'site_screenshots.py').read_text(encoding='utf-8')
    for path in re.findall(r"\('([a-z-]+)(?:\?[^']*)?', '", shots.split('PAGES = ')[1].split(']')[0]):
        assert f"url_path='{path}'" in app or f"'{path}':" in app, path



def test_results_year_on_year_and_quarter_before_only_where_held():
    import sys
    from types import SimpleNamespace
    sys.path.insert(0, str(ROOT / 'streamlit_app'))
    import pandas as pd
    from screens import more_pages
    res = pd.DataFrame({'isin': ['A', 'A', 'A', 'B'], 'symbol': ['A', 'A', 'A', 'B'], 'company': ['A', 'A', 'A', 'B'],
                        'period_end': ['2025-09-30', '2026-06-30', '2026-09-30', '2026-09-30'],
                        'broadcast_at': ['2025-11-05T10:00:00+05:30', '2026-08-05T10:00:00+05:30', '2026-11-05T10:00:00+05:30', '2026-11-06T10:00:00+05:30'],
                        'consolidated': ['Consolidated'] * 4, 'quarter_revenue': [100.0, 110.0, 120.0, 50.0], 'quarter_profit': [10.0, 11.0, 12.0, -1.0]})
    out = more_pages._latest_results(SimpleNamespace(results=res, ref=pd.Timestamp('2026-11-11')), 30).set_index('isin')
    assert round(out.loc['A', 'rev_yoy'], 1) == 20.0 and round(out.loc['A', 'rev_qoq'], 2) == 9.09
    assert pd.isna(out.loc['B', 'rev_yoy']) and pd.isna(out.loc['B', 'rev_qoq'])     # no history: a dash, never a guess


def test_site_loads_the_columns_the_dense_pages_read():
    """13 Nov 2026: the live Stakes page failed with KeyError 'pct_of_company': data/store.ONLY keeps a few columns of
    some tables for memory, and the pledge table on Stakes reads more. Every column the dense pages read is kept."""
    from data import store
    assert {'symbol', 'company', 'event_type', 'shares', 'pct_of_company', 'post_event_holding_pct', 'promoter_id', 'lender',
            'broadcast_date', 'attachment'} <= set(store.ONLY['encumbrances'])
    assert {'symbol', 'company', 'quarter_derived', 'quarter_revenue', 'quarter_profit'} <= set(store.ONLY['results'])


def test_events_report_is_published_and_shown(monkeypatch):
    """13 Nov 2026: the nightly NSE events report goes to R2 and Data health shows NSE's own results count."""
    from collectors.nse_events import run_daily
    put = []
    monkeypatch.setattr(run_daily, 'put', lambda r2, key, body, ct: put.append((key, body)))
    run_daily.publish_report(None, {'run_date': '2026-11-13', 'streams': {}}, 'all')
    assert put and put[0][0] == 'reports/nse_events/latest_all.json'
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(APP_PATHS + """
from screens import proto
proto._events_run({'run_date': '2026-11-13', 'window': ['2026-11-06', '2026-11-13'], 'results_listed': 90, 'results_total': 100,
                   'streams': {'results': {'fetched': 90, 'clean_rows': 88}}, 'notes': ['results: fetch failed (listing short: 90 of 100 for x..y)']})
""")
    at.run()
    assert not at.exception
    h = ' '.join(e.proto.body for e in at.get('html'))
    assert '90 of 100 NSE lists' in h and 'listing short' in h


def test_encumbered_after_is_the_post_event_holding():
    """NSE's encumbPerc is the encumbrance before the event; after = postEventHoldingPerc, summed over holders (13 Nov)."""
    import pandas as pd
    from screens import proto
    g = pd.DataFrame({'promoter_id': ['a', 'b', 'a'], 'encumbered_pct': [4.89, 0.1, 5.0],
                      'post_event_holding_pct': ['     7.60', '0.24', '     8.00']})
    assert abs(proto._encumbered_after(g) - 8.24) < 1e-9


def test_an_empty_stream_says_not_confirmed(monkeypatch):
    """C4 on the page (13 Nov 2026): when the last run marked a stream empty over a week, the empty table says so."""
    from data import store
    from screens import proto
    monkeypatch.setattr(store, 'events_report', lambda: {'streams': {'encumbrances': {'fetched': 0, 'empty_unconfirmed': True}}})
    assert 'not confirmed' in proto._unconfirmed('encumbrances') and proto._unconfirmed('sast') == ''


def test_a_half_year_only_filing_is_compared_half_year_with_half_year():
    """14 Nov 2026: a filing with no quarter (no June quarter to derive one) gets its half year compared with the half year
    a year earlier, of the same length, marked half_year; a filing with a quarter keeps the quarter comparison."""
    import sys
    import types
    from pathlib import Path
    import pandas as pd
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens import more_pages
    rows = [  # company A: half years only; company B: quarters
        dict(isin='A', period_end='2026-09-30', ytd_start='2026-04-01', ytd_revenue=1200.0, ytd_profit=120.0, quarter_revenue=None,
             broadcast_at='2026-11-05T10:00:00+05:30'),
        dict(isin='A', period_end='2025-09-30', ytd_start='2025-04-01', ytd_revenue=1000.0, ytd_profit=150.0, quarter_revenue=None,
             broadcast_at='2025-11-05T10:00:00+05:30'),
        dict(isin='B', period_end='2026-09-30', ytd_start='2026-04-01', ytd_revenue=900.0, ytd_profit=50.0, quarter_revenue=500.0,
             broadcast_at='2026-11-06T10:00:00+05:30'),
        dict(isin='B', period_end='2025-09-30', ytd_start='2025-04-01', ytd_revenue=800.0, ytd_profit=40.0, quarter_revenue=400.0,
             broadcast_at='2025-11-06T10:00:00+05:30')]
    res = pd.DataFrame(rows).assign(consolidated='Consolidated', quarter_profit=None, superseded=False)
    ctx = types.SimpleNamespace(results=res, ref=pd.Timestamp('2026-11-12'))
    out = more_pages._latest_results(ctx, 30).set_index('isin')
    assert bool(out.loc['A', 'half_year']) and round(float(out.loc['A', 'ytd_yoy']), 1) == 20.0
    assert not bool(out.loc['B', 'half_year']) and round(float(out.loc['B', 'rev_yoy']), 1) == 25.0


def test_top_search_finds_codes_isins_and_people():
    """14 Nov 2026: the top search found names and NSE symbols only; a BSE code, an ISIN, a promoter or a fund now match."""
    import sys
    import types
    from pathlib import Path
    import pandas as pd
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens import search
    ref = pd.Timestamp('2026-11-12')
    ctx = types.SimpleNamespace(
        ref=ref,
        securities=pd.DataFrame({'nse_symbol': ['HAVELLS', None], 'display_name': ['Havells India', 'Himalaya Nutravedics India'],
                                 'bse_code': ['517354', '544943'], 'isin': ['INE176B01034', 'INE0ABC01010']}),
        trades=pd.DataFrame({'person_id': ['p1', 'p2'], 'person_name': ['Anil Rai Gupta', 'A Staff Member'],
                             'person_role': ['promoter', 'designated_person'], 'is_market': [True, True],
                             'broadcast_date': [ref, ref]}),
        deals=pd.DataFrame({'client_id': ['c1', 'c2'], 'client_name': ['Kotak Mahindra Mutual Fund', 'Small Client'],
                            'value': [5e8, 1e6], 'date': [ref, ref], 'client_is_market_maker': [False, False]}))
    opts, targets = search._options.__wrapped__(ctx, str(ref))
    lab = 'Havells India · HAVELLS · BSE 517354 · INE176B01034'
    assert lab in opts and targets[lab] == ('company', 'HAVELLS')
    assert targets['Himalaya Nutravedics India · BSE 544943 · INE0ABC01010'] == ('company', '544943')   # BSE-only
    assert targets['Person or fund · Anil Rai Gupta'] == ('entity', 'p1')
    assert 'Person or fund · Kotak Mahindra Mutual Fund' in targets
    assert not any('Staff Member' in o or 'Small Client' in o for o in opts)   # staff and small clients are left out


def test_company_page_opens_by_bse_code(data_dir, monkeypatch):
    """14 Nov 2026: the top search opens a BSE-only company by its BSE code; the page finds it and its deals by ISIN."""
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()   # tables cached by earlier tests from another folder
st.query_params['symbol'] = '544717'
from ui import theme
theme.inject()
from screens import company
company.render()
""", default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value
    h = ' '.join(e.proto.body for e in at.get('html'))
    assert 'No company with the symbol' not in h and '>Bulk and block deals <' in h


def test_investors_directory_lists_funds_as_links(data_dir, monkeypatch):
    """14 Nov 2026 (owner: "one page with all mutual fund names as links, large investors etc"): the directory renders a
    section per investor type, each name a link to its page, market makers and promoters left out."""
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(data_dir))
    at = AppTest.from_string(APP_PATHS + """
import streamlit as st
st.cache_data.clear(); st.cache_resource.clear()
from ui import theme
theme.inject()
from screens import proto
proto.investors_directory()
""", default_timeout=60)
    at.run()
    assert not at.exception, at.exception[0].value
    h = ' '.join(e.proto.body for e in at.get('html'))
    assert '>Investors</h1>' in h and '>Mutual funds <' in h and '>Large individuals <' in h
    assert 'PROMOTER HOLDCO' not in h.upper() or '/entity?id=' in h
