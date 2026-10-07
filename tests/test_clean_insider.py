"""Insider-trade cleaning, mostly on real NSE filings (see conftest.py)."""
from __future__ import annotations

from datetime import date

import pandas as pd
from conftest import RUN_DATE, canonical

from insiders_clean.insider import classify_mode, classify_role, clean_insider, side_of


def run(rows, master, calendar, report, exchange='nse'):
    return clean_insider(canonical(exchange, 'insider_trading', rows), master, calendar, report, RUN_DATE)


def only(df, **eq):
    m = pd.Series(True, index=df.index)
    for k, v in eq.items():
        m &= df[k] == v
    return df[m]


# --- 1. Kesoram: the +157,313% "stake change" on the live site ---------------

def test_kesoram_is_off_market_and_never_a_market_buy(real_nse_rows, master, calendar, report):
    rows = [r for r in real_nse_rows if r['symbol'] == 'KESORAMIND']
    out = run(rows, master, calendar, report)
    k = out.iloc[0]
    assert k['mode_raw'] == 'Off Market'
    assert k['kind'] == 'off_market' and not k['is_market']
    assert k['person_role'] == 'promoter'
    assert k['company'] == 'Kesoram Industries'
    assert k['holding_before'] == 84525 and k['holding_after'] == 133053804


def test_same_jump_filed_as_market_purchase_is_held_back(real_nse_rows, master, calendar, report):
    row = dict(next(r for r in real_nse_rows if r['symbol'] == 'KESORAMIND'), modeOfAcquisition='Market Purchase')
    k = run([row], master, calendar, report).iloc[0]
    assert k['is_market']
    assert 'holding_jump_on_market_trade' in k['flags'] and k['needs_review']


# --- 2. Prakash Steelage: the same gift filed twice ---------------------------

def test_prakash_steelage_repeat_filings_removed(real_nse_rows, master, calendar, report):
    rows = [r for r in real_nse_rows if r['symbol'] == 'PRAKASHSTL']
    assert len(rows) == 4  # appIds 3135, 3136, 3138, 3139
    out = run(rows, master, calendar, report)
    assert len(out) == 2
    assert report.data['tables']['insider_trades']['removed']['repeat_filing']['count'] == 2
    seth = only(out, person_name='Dheliben Mafatlal Seth').iloc[0]
    assert seth['app_id'] == '3138'  # the later broadcast is kept
    assert seth['kind'] == 'gift' and not seth['is_market']
    # A gift is legitimately filed at zero value: not flagged.
    assert 'missing_or_zero_value' not in seth['flags']


# --- Zee: the live site's top "open-market promoter buy" ----------------------

def test_zee_promoter_allotment_is_preferential_not_market(real_nse_rows, master, calendar, report):
    out = run([r for r in real_nse_rows if r['symbol'] == 'ZEEL'], master, calendar, report)
    sunbright = out[out['person_name'].str.startswith('Sunbright')]
    assert len(sunbright) == 2
    assert set(sunbright['kind']) == {'preferential'} and not sunbright['is_market'].any()
    # Together exactly the Rs.735.55 Cr the live site ranked as open-market buying.
    assert round(sunbright['value'].sum() / 1e7, 2) == 735.55
    goenka = only(out, person_name='Shreyasi Goenka').iloc[0]
    assert goenka['is_market'] and goenka['side'] == 'BUY' and goenka['person_role'] == 'immediate_relative'


# --- Corrected re-filing without prevAppId (HCL Tech 3082 -> 3119) ------------

def test_corrected_refiling_replaces_original(real_nse_rows, master, calendar, report):
    rows = [r for r in real_nse_rows if r['appId'] in ('3082', '3119')]
    out = run(rows, master, calendar, report)
    assert set(out['app_id']) == {'3119'}
    removed = report.data['tables']['insider_trades']['removed']
    assert removed['corrected_refiling']['count'] == 2   # the two 'Market Purchase' sales
    assert removed['repeat_filing']['count'] == 1        # the identical ESOS line
    sales = only(out, kind='market')
    assert set(sales['mode_raw']) == {'Market Sale'} and set(sales['side']) == {'SELL'}


def test_mode_contradicting_type_keeps_type_and_is_flagged(real_nse_rows, master, calendar, report):
    row = next(r for r in real_nse_rows if r['appId'] == '2894' and r['modeOfAcquisition'] == 'Market Purchase')
    k = run([row], master, calendar, report).iloc[0]
    assert k['side'] == 'SELL'  # holding 37,894 -> 37,104
    assert 'mode_contradicts_side' in k['flags']


# --- Truncated names: one promoter, two spellings -----------------------------

def test_truncated_promoter_names_merge(real_nse_rows, master, calendar, report):
    rows = [r for r in real_nse_rows if r['acqName'].replace('\n', ' ').startswith('Vama Sundari')]
    assert len({r['acqName'] for r in rows}) >= 2
    out = run(rows, master, calendar, report)
    assert out['person_id'].nunique() == 1
    assert out['person_name'].iloc[0].startswith('Vama Sundari Investments (Del')


# --- Disclosure deadlines in trading sessions ---------------------------------

def test_friday_trade_told_on_monday_is_on_time(real_nse_rows, master, calendar, report):
    row = next(r for r in real_nse_rows if r['appId'] == '2793')  # traded Fri 28 Aug, told Mon 31 Aug
    k = run([row], master, calendar, report).iloc[0]
    assert k['insider_to_company_sessions'] == 1 and not k['insider_filed_late']
    assert k['company_to_exchange_sessions'] == 1 and not k['company_filed_late']


def test_six_week_old_trade_is_late(real_nse_rows, master, calendar, report):
    row = next(r for r in real_nse_rows if r['appId'] == '2894' and r['acqtoDt'] == '2026-07-20')
    k = run([row], master, calendar, report).iloc[0]
    assert k['insider_filed_late'] and k['insider_to_company_sessions'] > 20


def test_lateness_unknown_past_calendar(real_nse_rows, master, calendar, report):
    row = dict(real_nse_rows[0], acqtoDt='2026-10-05', intimDt='2026-10-07')
    k = run([row], master, calendar, report).iloc[0]
    assert pd.isna(k['insider_filed_late'])


# --- small units ---------------------------------------------------------------

def test_mode_vocabulary():
    assert classify_mode('Market Purchase') == 'market'
    assert classify_mode('Market Sale') == 'market'
    assert classify_mode('Off Market') == 'off_market'
    assert classify_mode('ESOS') == 'esop'
    assert classify_mode('Preferential Offer') == 'preferential'
    assert classify_mode('Revokation of Pledge') == 'pledge_revoke'
    assert classify_mode('Invocation of pledge') == 'pledge_invoke'
    assert classify_mode('Inter-se-Transfer') == 'inter_se'
    assert classify_mode('Scheme of Amalgamation') == 'scheme'
    assert classify_mode('Something new') == 'unrecognised'
    assert classify_mode(None) == 'missing'


def test_roles_and_sides():
    assert classify_role('Promoter Group') == 'promoter_group'
    assert classify_role('Promoter and Director') == 'promoter'
    assert classify_role('Key Managerial Personnel') == 'kmp'
    assert side_of('Disposal', 'Market Purchase') == 'SELL'
    assert side_of('', 'Market Purchase') == 'BUY'
    assert side_of('Pledge Creation', 'Pledge Creation') is None


def test_dates_parse_both_exchanges():
    from insiders_clean.dates import parse_dates
    got = parse_dates(pd.Series(['2026-08-27', '31-Aug-2026 17:40:12', '03/04/2026',
                                 '2026-08-30T18:30:00.000Z', '', None]))
    assert list(got) == [date(2026, 8, 27), date(2026, 8, 31), date(2026, 4, 3), date(2026, 8, 31), None, None]
