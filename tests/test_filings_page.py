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
    for kind in ('Insider market', 'Insider other', 'Deals'):
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
    _, html = _run(site, monkeypatch, 'Insider other')
    assert 'ex-bse' in html              # the one row says it was filed on both exchanges
