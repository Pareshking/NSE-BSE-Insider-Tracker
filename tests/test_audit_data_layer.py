"""Data-layer audit, batch 2 (docs/audit/data_layer.md W1, W3, W4, W5, W7, W8, W10).

Filings are test values in the shape of NSE's PIT list rows and BSE's nightly
capture rows, turned into canonical rows by scripts/r2_writer.py (conftest.canonical).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from conftest import RUN_DATE, canonical

from insiders_clean import adjust, market_cap, signals
from insiders_clean.deals import clean_deals
from insiders_clean.insider import clean_insider


@pytest.fixture(scope='module')
def hcl(master):
    isin = master.resolve('nse', 'HCLTECH')[0]
    rec = master.record(isin)
    assert rec['bse_code']
    return rec


def nse(name, qty, val, frm, to, mode='Market Purchase', tt='Acquisition', b=1_000_000, a=None, app='9001',
        cat='Promoter', symbol='HCLTECH', bcast='08-Sep-2026 16:00:00', sub='', remark='', prev=''):
    a = b + qty if a is None and tt == 'Acquisition' else (b - qty if a is None else a)
    buy = tt == 'Acquisition'
    return {'symbol': symbol, 'companyName': 'Test Co', 'acqName': name, 'personCategory': cat, 'secType': 'Equity',
            'transactionType': tt, 'buyQuantity': str(qty) if buy else '', 'sellquantity': '' if buy else str(qty),
            'buyValue': str(val) if buy else '', 'sellValue': '' if buy else str(val),
            'beforeSharesNo': str(b), 'afterSharesNo': str(a), 'modeOfAcquisition': mode,
            'acqfromDt': frm, 'acqtoDt': to, 'date': to, 'intimDt': to, 'broadcastDt': bcast, 'appId': app,
            'prevAppId': prev, 'typeOfSubmission': sub, 'revisionRemark': remark}


def bse(code, name, qty, val, day, mode='Market Purchase', tt='ACQUISITION', b=1_000_000, a=None, cat='Promoter'):
    a = (b + qty if tt == 'ACQUISITION' else b - qty) if a is None else a
    return {'security_code': code, 'company': 'Test Co Ltd', 'person': name.upper(), 'person_category': cat,
            'holding_before': str(b), 'security_type': 'Equity', 'quantity': str(qty), 'transaction_value': str(val),
            'transaction_type': tt, 'holding_after': str(a), 'transaction_date': day, 'mode': mode,
            'broadcast_date': '2026-09-08T00:00:00'}


def run(master, calendar, report, nse_rows=(), bse_rows=(), mcap=None):
    parts = []
    if nse_rows:
        parts.append(canonical('nse', 'insider_trading', list(nse_rows)))
    if bse_rows:
        parts.append(canonical('bse', 'insider_trading', list(bse_rows)))
    raw = pd.concat(parts, ignore_index=True)
    return clean_insider(raw, master, calendar, report, RUN_DATE, market_cap_daily=mcap)


def mcap_frame(rows):
    return market_cap.daily_frame(pd.DataFrame(rows, columns=['date', 'symbol', 'series', 'market_cap']))


# --- W1: % of market cap at the trade date ----------------------------------------------------------------------

def test_pct_of_mcap_uses_the_trade_dates_market_cap(master, calendar, report):
    mc = mcap_frame([('2026-09-01', 'ZEEL', 'EQ', 1.0e11), ('2026-09-04', 'ZEEL', 'EQ', 2.0e11),
                     ('2026-09-04', 'ZEEL', 'BL', 9.9e11)])   # a block-window series never wins over EQ
    rows = [nse('Buyer One', 10_000, 1e7, '2026-09-01', '2026-09-01', symbol='ZEEL', app='1'),
            nse('Buyer Two', 10_000, 1e7, '2026-09-07', '2026-09-07', symbol='ZEEL', app='2'),   # Monday: Friday's cap
            nse('Buyer Three', 10_000, 1e7, '2026-10-01', '2026-10-01', symbol='ZEEL', app='3')]  # after the layer
    out = run(master, calendar, report, rows, mcap=mc).set_index('person_name')
    one, two, three = out.loc['Buyer One'], out.loc['Buyer Two'], out.loc['Buyer Three']
    assert one['market_cap_at_trade'] == 1.0e11 and one['market_cap_basis'] == 'trade_date'
    assert two['market_cap_at_trade'] == 2.0e11 and two['market_cap_basis'] == 'previous_session'
    assert two['market_cap_date'] == pd.Timestamp('2026-09-04')
    assert one['pct_of_mcap'] == pytest.approx(1e7 / 1.0e11 * 100) and one['pct_of_mcap'] == 2 * two['pct_of_mcap']
    # No dated figure within 10 days: the latest market cap, said so
    assert three['market_cap_basis'] == 'latest' and three['pct_of_mcap'] == pytest.approx(1e7 / 6.9e10 * 100)
    assert set(out['market_cap']) == {6.9e10}   # `market_cap` stays the latest
    assert report.data['tables']['insider_trades']['market_cap_basis'] == {
        'trade_date': 1, 'previous_session': 1, 'latest': 1}


def test_without_the_layer_every_row_takes_the_latest(master, calendar, report):
    out = run(master, calendar, report, [nse('A', 10, 1e5, '2026-09-01', '2026-09-01', symbol='ZEEL')])
    assert out['market_cap_basis'].tolist() == ['latest'] and out['market_cap_at_trade'].tolist() == [6.9e10]


def test_deal_pct_of_mcap_on_the_deal_day(master, report):
    row = {'BD_DT_DATE': '01-Sep-2026', 'BD_SYMBOL': 'ZEEL', 'BD_SCRIP_NAME': 'Zee', 'BD_CLIENT_NAME': 'A FUND',
           'BD_BUY_SELL': 'BUY', 'BD_QTY_TRD': '100000', 'BD_TP_WATP': '100'}
    mc = mcap_frame([('2026-09-01', 'ZEEL', 'EQ', 1.0e11)])
    d = clean_deals(canonical('nse', 'bulk_deals', [row]), master, report, RUN_DATE, market_cap_daily=mc).iloc[0]
    assert d['market_cap_at_trade'] == 1.0e11 and d['market_cap'] == 6.9e10
    assert d['pct_of_mcap'] == pytest.approx(1e7 / 1e11 * 100)


def test_load_daily_lists_missing_months_and_reads_the_rest():
    buf = io.BytesIO()
    pd.DataFrame({'date': pd.to_datetime(['2026-09-01']), 'symbol': ['ZEEL'], 'series': ['EQ'], 'name': ['Z'],
                  'category': ['Listed'], 'face_value': [1.0], 'issue_size': [1e9], 'close': [100.0],
                  'market_cap': [1e11]}).to_parquet(buf, index=False)
    store = {'marketcap/daily/nse/2026-09.parquet': buf.getvalue()}
    daily, info = market_cap.load_daily(store.get, ['2026-08', '2026-09'])
    assert info['months_read'] == 1 and info['months_missing'] == ['marketcap/daily/nse/2026-08.parquet']
    assert daily[['symbol', 'market_cap']].values.tolist() == [['ZEEL', 1e11]]


# --- W3: the NSE/BSE copy link never demotes a distinct trade -----------------------------------------------------

def test_buy_and_sale_of_one_size_on_one_day_are_two_trades(master, calendar, report, hcl):
    code = hcl['bse_code']
    nr = [nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-02', '2026-09-02', app='9004'),
          nse('Shiv Nadar', 50_000, 75_500_000, '2026-09-02', '2026-09-02', mode='Market Sale', tt='Disposal',
              b=1_050_000, app='9005')]
    br = [bse(code, 'Shiv Nadar', 50_000, 75_000_000, '02/09/2026'),
          bse(code, 'Shiv Nadar', 50_000, 75_500_000, '02/09/2026', mode='Market Sale', tt='DISPOSAL', b=1_050_000)]
    out = run(master, calendar, report, nr, br)
    n, b = out[out['exchange'] == 'nse'], out[out['exchange'] == 'bse']
    assert n['is_primary'].all() and not b['is_primary'].any()
    # each BSE row points at the NSE row of its own side
    for _, r in b.iterrows():
        assert n.set_index('trade_id').loc[r['primary_id'], 'side'] == r['side']
    el = signals.eligible(out)
    assert sorted(el['side']) == ['BUY', 'SELL']
    assert set(out['listed_on']) == {'bse,nse'}


def test_a_pledge_and_a_buy_of_one_size_both_stay(master, calendar, report, hcl):
    code = hcl['bse_code']
    nr = [nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-02', '2026-09-02', app='9002'),
          nse('Shiv Nadar', 50_000, 0, '2026-09-02', '2026-09-02', mode='Pledge Creation', tt='Pledge',
              b=1_050_000, a=1_050_000, app='9003')]
    br = [bse(code, 'Shiv Nadar', 50_000, 75_000_000, '02/09/2026')]
    out = run(master, calendar, report, nr, br)
    assert out.loc[out['exchange'] == 'nse', 'is_primary'].all()
    bse_row = out[out['exchange'] == 'bse'].iloc[0]
    linked_to = out.set_index('trade_id').loc[bse_row['primary_id']]
    assert linked_to['kind'] == 'market' and not bse_row['is_primary']


# --- W4: a multi-day NSE filing and its BSE nightly copy ----------------------------------------------------------

def test_multi_day_nse_filing_links_to_the_bse_nightly_copy(master, calendar, report, hcl):
    out = run(master, calendar, report, [nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-01', '2026-09-03')],
              [bse(hcl['bse_code'], 'Shiv Nadar', 50_000, 75_000_000, '01/09/2026')])
    assert out['is_primary'].sum() == 1 and set(out['listed_on']) == {'bse,nse'}
    assert signals.eligible(out)['value'].sum() == 75_000_000
    assert report.data['tables']['insider_trades']['nse_bse_copies'] == {'linked': 1, 'linked_bse_nightly_on_span': 1,
                                                                          'bse_refiled': 0}


def test_a_trade_bse_files_again_is_a_copy_too(master, calendar, report, hcl):
    """Gateway Distriparks, 04 Dec 2025: BSE files the buy with no value, then again on 23 Jan 2026 with it; the
    NSE row pairs with one, and the other was read by the signals as a second buy (audit 23 Oct)."""
    again = {**bse(hcl['bse_code'], 'Shiv Nadar', 50_000, 75_000_000, '02/09/2026'), 'broadcast_date': '2026-10-01T00:00:00'}
    out = run(master, calendar, report, [nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-02', '2026-09-02')],
              [bse(hcl['bse_code'], 'Shiv Nadar', 50_000, 0, '02/09/2026'), again])
    assert out['is_primary'].sum() == 1 and out.loc[out['is_primary'], 'exchange'].tolist() == ['nse']
    assert set(out.loc[~out['is_primary'], 'primary_id']) == set(out.loc[out['is_primary'], 'trade_id'])
    assert signals.eligible(out)['value'].sum() == 75_000_000
    assert report.data['tables']['insider_trades']['nse_bse_copies']['bse_refiled'] == 1


def test_two_trades_of_one_size_on_both_exchanges_stay_two(master, calendar, report, hcl):
    code = hcl['bse_code']
    out = run(master, calendar, report, [nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-02', '2026-09-02', app='9010'),
                                         nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-02', '2026-09-02', b=1_050_000, app='9011')],
              [bse(code, 'Shiv Nadar', 50_000, 75_000_000, '02/09/2026'), bse(code, 'Shiv Nadar', 50_000, 75_000_000, '02/09/2026', b=1_050_000)])
    assert out.loc[out['is_primary'], 'exchange'].tolist() == ['nse', 'nse']


def test_bse_nightly_row_outside_the_span_is_its_own_trade(master, calendar, report, hcl):
    out = run(master, calendar, report, [nse('Shiv Nadar', 50_000, 75_000_000, '2026-09-01', '2026-09-03')],
              [bse(hcl['bse_code'], 'Shiv Nadar', 50_000, 75_000_000, '07/09/2026')])
    assert out['is_primary'].all()


# --- W5: an individual is never folded into his HUF ---------------------------------------------------------------

def test_person_and_his_huf_stay_two_people(master, calendar, report):
    rows = [nse('Ramesh Kumar Agarwal', 1_000, 1e6, '2026-09-01', '2026-09-01', app='1'),
            nse('Ramesh Kumar Agarwal HUF', 2_000, 2e6, '2026-09-01', '2026-09-01', app='2')]
    out = run(master, calendar, report, rows)
    assert sorted(out['person_id']) == ['ramesh-kumar-agarwal', 'ramesh-kumar-agarwal-huf']


def test_cut_names_still_merge(master, calendar, report):
    rows = [nse('Vama Sundari Investments (Delh', 1_000, 1e6, '2026-09-01', '2026-09-01', app='1'),
            nse('Vama Sundari Investments (Delhi) Private Limited', 2_000, 2e6, '2026-09-02', '2026-09-02', app='2'),
            # cut at a word boundary, 30 characters: the same person
            nse('Anand Shivram Krishnamurthy Iy', 10, 1e4, '2026-09-01', '2026-09-01', app='3'),
            nse('Anand Shivram Krishnamurthy Iyer', 10, 1e4, '2026-09-02', '2026-09-02', app='4')]
    out = run(master, calendar, report, rows)
    assert out['person_id'].nunique() == 2


def test_whole_name_and_his_company_stay_apart(master, calendar, report):
    rows = [nse('Ramesh Kumar Agarwal Raghunath', 10, 1e4, '2026-09-01', '2026-09-01', app='1'),   # 30 characters
            nse('Ramesh Kumar Agarwal Raghunath Private Limited', 10, 1e4, '2026-09-02', '2026-09-02', app='2'),
            nse('Sunil Kumar Mehta Holdings Pvt', 10, 1e4, '2026-09-01', '2026-09-01', app='3'),
            nse('Sunil Kumar Mehta Holdings Private Limited', 10, 1e4, '2026-09-02', '2026-09-02', app='4')]
    out = run(master, calendar, report, rows)
    ids = set(out['person_id'])
    assert {'ramesh-kumar-agarwal-raghunath', 'ramesh-kumar-agarwal-raghunath-private-limited'} <= ids
    assert 'sunil-kumar-mehta-holdings-private' not in ids   # a company's name cut before its form merges


# --- W10: a revision without prevAppId that corrects the size -----------------------------------------------------

def test_revision_marker_replaces_the_original_and_its_bse_copy(master, calendar, report, hcl):
    orig = nse('Shiv Nadar', 10_000, 1e7, '2026-09-02', '2026-09-02', app='5001', sub='Original',
               bcast='03-Sep-2026 10:00:00')
    rev = nse('Shiv Nadar', 12_000, 1.2e7, '2026-09-02', '2026-09-02', app='5002', sub='Revision',
              remark='quantity corrected', bcast='05-Sep-2026 11:00:00')
    copy = bse(hcl['bse_code'], 'Shiv Nadar', 10_000, 1e7, '02/09/2026')
    out = run(master, calendar, report, [orig, rev], [copy])
    assert out['app_id'].tolist() == ['5002'] and out['quantity'].tolist() == [12_000]
    t = report.data['tables']['insider_trades']
    assert t['removed']['superseded_by_revision_marker']['count'] == 1
    assert t['removed']['bse_copy_of_replaced_filing']['count'] == 1
    assert t['revision_marker'] == {'revision_rows': 1, 'replaced_rows': 1, 'ambiguous': 0, 'no_original': 0}


def test_revision_marker_with_two_candidates_removes_nothing(master, calendar, report):
    a = nse('Shiv Nadar', 10_000, 1e7, '2026-09-02', '2026-09-02', app='6001', bcast='03-Sep-2026 10:00:00')
    b = nse('Shiv Nadar', 20_000, 2e7, '2026-09-02', '2026-09-02', app='6002', b=1_010_000,
            bcast='03-Sep-2026 12:00:00')
    rev = nse('Shiv Nadar', 12_000, 1.2e7, '2026-09-02', '2026-09-02', app='6003', sub='Revision',
              bcast='05-Sep-2026 11:00:00')
    out = run(master, calendar, report, [a, b, rev])
    assert len(out) == 3
    t = report.data['tables']['insider_trades']
    assert 'superseded_by_revision_marker' not in t['removed'] and t['revision_marker']['ambiguous'] == 1


def test_original_typed_as_original_is_never_replaced_by_content(master, calendar, report):
    a = nse('Shiv Nadar', 10_000, 1e7, '2026-09-02', '2026-09-02', app='7001', sub='Original')
    b = nse('Shiv Nadar', 12_000, 1.2e7, '2026-09-02', '2026-09-02', app='7002', sub='Original', b=1_010_000,
            bcast='09-Sep-2026 16:00:00')
    assert len(run(master, calendar, report, [a, b])) == 2


# --- W7: bonus ratios, and a special dividend that is not a bonus -------------------------------------------------

def _p(rows):
    return pd.DataFrame(rows, columns=['date', 'exchange', 'isin', 'symbol', 'series', 'close', 'prev_close', 'value'])\
        .assign(date=lambda d: pd.to_datetime(d['date']))


@pytest.mark.parametrize('n,h', [(1, 6), (1, 10), (3, 10), (7, 10), (11, 10), (2, 5)])
def test_bonus_ratios_with_six_and_ten_held_are_adjusted(n, h):
    f = h / (h + n)
    rows = [('2026-01-05', 'NSE', 'INE1', 'A', 'EQ', 100.0, 99.0, 10),
            ('2026-01-06', 'NSE', 'INE1', 'A', 'EQ', round(101 * f, 2), round(100 * f, 2), 10)]
    fac = adjust.implied_factors(_p(rows))
    assert fac['kind'].iloc[-1] == 'split_bonus' and fac['kind_basis'].iloc[-1] == 'ratio'
    adj = adjust.adjust_as_of(fac, _p(rows)[['date', 'exchange', 'isin', 'close']], '2026-01-06')
    assert adj['adj_close'].iloc[0] == pytest.approx(100.0 * round(100 * f, 2) / 100, rel=1e-9)


def test_odd_resets_are_still_not_taken_for_bonuses():
    assert adjust.is_clean_ratio(np.array([0.73, 0.93, 0.88])).tolist() == [False, False, False]


def test_special_dividend_with_a_filed_dividend_is_not_a_bonus():
    rows = [('2026-01-05', 'NSE', 'INE1', 'A', 'EQ', 100.0, 99.0, 10), ('2026-01-06', 'NSE', 'INE1', 'A', 'EQ', 81.0, 80.0, 10)]
    assert adjust.implied_factors(_p(rows))['kind'].iloc[-1] == 'split_bonus'   # 0.8 = a 1:4 bonus, by ratio alone
    acts = pd.DataFrame([{'isin': 'INE1', 'purpose': 'dividend', 'ex_date': '2026-01-06', 'ratio': None,
                          'face_value_from': None, 'face_value_to': None}])
    fac = adjust.implied_factors(_p(rows), actions=acts)
    assert (fac['kind'].iloc[-1], fac['kind_basis'].iloc[-1]) == ('other_large', 'action_not_split_bonus')
    adj = adjust.adjust_as_of(fac, _p(rows)[['date', 'exchange', 'isin', 'close']], '2026-01-06')
    assert adj['adj_close'].tolist() == [100.0, 81.0]


def test_filed_bonus_classifies_even_under_five_percent_and_checks_the_ratio():
    # 1:20 bonus: 20/21 = 0.952, a 4.8% reset, under the 5% line
    rows = [('2026-01-05', 'NSE', 'INE1', 'A', 'EQ', 105.0, 104.0, 10),
            ('2026-01-07', 'NSE', 'INE1', 'A', 'EQ', 101.0, 100.0, 10),   # not traded on the 6th, the ex-date
            ('2026-01-05', 'NSE', 'INE2', 'B', 'EQ', 100.0, 99.0, 10), ('2026-01-06', 'NSE', 'INE2', 'B', 'EQ', 70.0, 70.0, 10)]
    acts = pd.DataFrame([{'isin': 'INE1', 'purpose': 'bonus', 'ex_date': '2026-01-06', 'ratio': '1:20'},
                         {'isin': 'INE2', 'purpose': 'bonus', 'ex_date': '2026-01-06', 'ratio': '1:1'}])
    fac = adjust.implied_factors(_p(rows), actions=acts).set_index(['isin', 'date'])
    one = fac.loc[('INE1', pd.Timestamp('2026-01-07'))]
    assert (one['kind'], one['kind_basis']) == ('split_bonus', 'action')
    two = fac.loc[('INE2', pd.Timestamp('2026-01-06'))]   # filed 1:1 (0.5), price says 0.7: not applied
    assert (two['kind'], two['kind_basis']) == ('other_large', 'action_mismatch')


def test_expected_factors_from_bonus_and_split():
    acts = pd.DataFrame([{'isin': 'X', 'purpose': 'bonus', 'ex_date': '2026-01-06', 'ratio': '1:3'},
                         {'isin': 'Y', 'purpose': 'split', 'ex_date': '2026-01-06', 'face_value_from': 10.0,
                          'face_value_to': 2.0},
                         {'isin': 'Y', 'purpose': 'split', 'ex_date': '2026-01-06', 'face_value_from': 10.0,
                          'face_value_to': 2.0}])   # the same split on both exchanges counts once
    e = adjust.expected_factors(acts).set_index('isin')['expected']
    assert e['X'] == pytest.approx(0.75) and e['Y'] == pytest.approx(0.2)


# --- W8: deals on NSE and on BSE are separate executions ----------------------------------------------------------

def test_same_client_same_size_on_both_exchanges_counts_twice(master, report):
    nse_row = {'BD_DT_DATE': '06-Oct-2026', 'BD_SYMBOL': 'CLEANMAX', 'BD_SCRIP_NAME': 'Clean Max',
               'BD_CLIENT_NAME': 'BIG BUYER FUND', 'BD_BUY_SELL': 'BUY', 'BD_QTY_TRD': '100000', 'BD_TP_WATP': '100.0'}
    bse_row = {'event_date': '06/10/2026', 'security_code': '544717', 'security_name': 'CLEANMAX', 'company': 'CLEANMAX',
               'person': 'BIG BUYER FUND', 'side': 'BUY', 'quantity': '100000', 'price': '100.4', 'raw': []}
    raw = pd.concat([canonical('nse', 'bulk_deals', [nse_row]), canonical('bse', 'bulk_deals', [bse_row])],
                    ignore_index=True)
    out = clean_deals(raw, master, report, RUN_DATE)
    assert len(out) == 2 and out['is_primary'].all() and out['same_size_on_other_exchange'].all()
    assert out['signed_value'].sum() == pytest.approx(100000 * 100.0 + 100000 * 100.4)
    assert report.data['tables']['deals']['same_size_on_both_exchanges'] == {'legs': 2, 'legs_at_the_same_price': 0}


def _nse_cleanmax(client, side, qty, price='100.0', day='06-Oct-2026'):
    return {'BD_DT_DATE': day, 'BD_SYMBOL': 'CLEANMAX', 'BD_SCRIP_NAME': 'Clean Max', 'BD_CLIENT_NAME': client,
            'BD_BUY_SELL': side, 'BD_QTY_TRD': str(qty), 'BD_TP_WATP': price}


def _bse_cleanmax(client, side, qty, price='100.4', day='06/10/2026'):
    return {'event_date': day, 'security_code': '544717', 'security_name': 'CLEANMAX', 'company': 'CLEANMAX',
            'person': client, 'side': side, 'quantity': str(qty), 'price': price, 'raw': []}


def test_a_buy_on_one_exchange_and_an_equal_sell_on_the_other_is_an_intraday_round_trip(master, report):
    """Silverleaf Capital, 23 Jun 2026: Rs 3.96 Cr bought and sold, both shown. The writer flags a round trip only within
    one exchange and feed of one run; the clean layer judges the client's whole day."""
    raw = pd.concat([
        canonical('nse', 'bulk_deals', [_nse_cleanmax('FLIPPER CAPITAL LLP', 'BUY', 100000),
                                        _nse_cleanmax('REAL FUND', 'BUY', 500000)]),
        canonical('bse', 'bulk_deals', [_bse_cleanmax('FLIPPER CAPITAL LLP', 'SELL', 100000)]),
        canonical('bse', 'block_deals', [_bse_cleanmax('SOME SELLER', 'SELL', 500000)])], ignore_index=True)
    out = clean_deals(raw, master, report, RUN_DATE)
    assert sorted(out['client_name'].str.upper()) == ['REAL FUND', 'SOME SELLER']
    assert report.data['tables']['deals']['removed']['intraday_round_trip_across_exchanges']['count'] == 2
    assert not out['counterparties'].fillna('').str.contains('FLIPPER', case=False).any()   # not named as the other side


def test_a_client_who_bought_and_sold_unequal_amounts_or_on_different_days_is_kept(master, report):
    raw = pd.concat([
        canonical('nse', 'bulk_deals', [_nse_cleanmax('SWING FUND', 'BUY', 100000),
                                        _nse_cleanmax('DAY FUND', 'BUY', 100000)]),
        canonical('bse', 'bulk_deals', [_bse_cleanmax('SWING FUND', 'SELL', 60000),                  # not equal
                                        _bse_cleanmax('DAY FUND', 'SELL', 100000, day='07/10/2026')])],   # another day
        ignore_index=True)
    out = clean_deals(raw, master, report, RUN_DATE)
    assert len(out) == 4
    assert 'intraday_round_trip_across_exchanges' not in report.data['tables']['deals']['removed']


# ---- a market cap on the trade's day for a company NSE does not list (BSE-only) ----------------------------------------

def _bse_only_master():
    from insiders_clean.securities import SecurityMaster, bse_list_frame, nse_list_frame
    rows = [{'symbol': '511111', 'isin': 'INE111A01011', 'company_name': 'Bse Only Ltd', 'market_cap': 9e9,
             'source': 'bse_list_securities', 'group': 'B'}]
    return SecurityMaster(vr_master=None, nse_list=nse_list_frame(), bse_list=bse_list_frame(rows), market_cap_rows=rows)


def _caps(closes=((' 2026-10-06', 100.0),), shares=((' 2026-09-30', 1e7),)):
    s = pd.DataFrame({'isin': 'INE111A01011', 'quarter_end': pd.to_datetime([d.strip() for d, _ in shares]),
                      'total_shares': [v for _, v in shares]})
    c = pd.DataFrame({'isin': 'INE111A01011', 'date': pd.to_datetime([d.strip() for d, _ in closes]), 'close': [v for _, v in closes]})
    return s, c


def _bse_deal_row(day='06/10/2026'):
    return {'event_date': day, 'security_code': '511111', 'security_name': 'BSEONLY', 'company': 'BSEONLY', 'person': 'SOME FUND LLP',
            'side': 'BUY', 'quantity': '100000', 'price': '100.0', 'raw': []}


def test_a_bse_only_deal_takes_shares_times_the_bse_close_of_its_day(report):
    raw = canonical('bse', 'bulk_deals', [_bse_deal_row()])
    before = clean_deals(raw, _bse_only_master(), report, RUN_DATE).iloc[0]
    assert before['market_cap_basis'] == 'latest' and before['pct_of_mcap'] == pytest.approx(1e7 / 9e9 * 100)
    after = clean_deals(raw, _bse_only_master(), type(report)(RUN_DATE), RUN_DATE, bse_caps=_caps()).iloc[0]
    assert after['market_cap_basis'] == 'shares_x_close' and after['market_cap_at_trade'] == pytest.approx(1e9)   # 1 Cr shares x Rs 100
    assert after['pct_of_mcap'] == pytest.approx(1.0) and after['market_cap_date'] == pd.Timestamp('2026-10-06')
    assert after['market_cap'] == pytest.approx(9e9)                                                            # the latest stays as it was


def test_a_bse_only_trade_with_no_close_or_no_shares_keeps_the_latest(report):
    raw = canonical('bse', 'bulk_deals', [_bse_deal_row()])
    for caps in (_caps(closes=((' 2026-08-01', 100.0),)),                  # the last close is over ten days before
                 _caps(shares=((' 2026-12-31', 1e7),))):                   # the only quarter is after the trade
        out = clean_deals(raw, _bse_only_master(), type(report)(RUN_DATE), RUN_DATE, bse_caps=caps).iloc[0]
        assert out['market_cap_basis'] == 'latest' and out['market_cap_at_trade'] == pytest.approx(9e9)
    near = clean_deals(raw, _bse_only_master(), type(report)(RUN_DATE), RUN_DATE,
                       bse_caps=_caps(closes=((' 2026-10-02', 90.0),))).iloc[0]                                 # the session before
    assert near['market_cap_basis'] == 'shares_x_close' and near['market_cap_at_trade'] == pytest.approx(9e8)
    assert near['market_cap_date'] == pd.Timestamp('2026-10-02')


def test_an_nse_listed_company_never_takes_the_shares_route(master, report):
    """CLEANMAX is on both exchanges: its dated figure is NSE's or the latest, whatever the BSE layer holds."""
    from insiders_clean import market_cap
    at = pd.DataFrame({'market_cap_at_trade': [9e10], 'market_cap_date': [pd.NaT], 'market_cap_basis': ['latest']})
    s = pd.DataFrame({'isin': ['INE647U01026'], 'quarter_end': [pd.Timestamp('2026-09-30')], 'total_shares': [1e7]})
    c = pd.DataFrame({'isin': ['INE647U01026'], 'date': [pd.Timestamp('2026-10-06')], 'close': [100.0]})
    out = market_cap.from_shares(at, pd.Series(['INE647U01026']), pd.Series([pd.Timestamp('2026-10-06')]), s, c, pd.Series([False]))
    assert out['market_cap_basis'].tolist() == ['latest'] and out['market_cap_at_trade'].tolist() == [9e10]


def test_shares_frame_keeps_one_row_per_isin_and_quarter_and_drops_blanks():
    from insiders_clean import market_cap
    a = pd.DataFrame({'isin': ['X', 'X', 'Y'], 'quarter_end': ['2026-06-30', '2026-06-30', '2026-06-30'], 'total_shares': [1e6, 2e6, None]})
    got = market_cap.shares_frame(a, None)
    assert got['isin'].tolist() == ['X'] and got['total_shares'].tolist() == [2e6]
    assert market_cap.shares_frame(None).empty


def test_load_bse_closes_reads_the_months_it_finds_and_lists_the_rest():
    import io

    from insiders_clean import market_cap
    body = io.BytesIO()
    pd.DataFrame({'date': ['2026-10-06', '2026-10-06'], 'isin': ['A', 'A'], 'close': [100.0, 101.0]}).to_parquet(body)
    got, info = market_cap.load_bse_closes(lambda k: body.getvalue() if k.endswith('2026-10.parquet') else None, ['2026-09', '2026-10'])
    assert len(got) == 1 and got.iloc[0]['close'] == 101.0               # one row per ISIN and session, the last print
    assert info['months_read'] == 1 and info['months_missing'] == ['prices/daily/bse/2026-09.parquet']
    none, info = market_cap.load_bse_closes(lambda k: None, ['2026-10'])
    assert none is None and info['months_read'] == 0
