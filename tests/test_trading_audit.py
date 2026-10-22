"""The trading-data audit of 22 Oct 2026 (docs/DATA_CHAIN_AUDIT.md, section 3, T-findings): fixtures shaped like
the real NSE and BSE rows behind each finding."""
from __future__ import annotations

import pandas as pd
import pytest
from test_audit_data_layer import bse, nse, run

from insiders_clean import ideas, signals
from insiders_clean.entities import entity_key
from insiders_clean.promoter_group import mark_deal_promoters
from insiders_clean.insider import classify_mode, classify_role, kind_from_type


@pytest.fixture(scope='module')
def code(master):
    return master.record(master.resolve('nse', 'HCLTECH')[0])['bse_code']


# --- T1: a director's relative is no director -------------------------------------------------------------------

def test_relatives_are_read_before_the_insider_they_are_related_to():
    assert classify_role('Directors Immediate Relative') == 'immediate_relative'
    assert classify_role('Employees Immediate Relative') == 'immediate_relative'
    assert classify_role('Immediate relative') == 'immediate_relative'
    assert classify_role('Promoters Immediate Relative') == 'promoter_group'   # ICDR 2(1)(pp)(ii)
    assert classify_role('Promoter Immediate Relative') == 'promoter_group'
    assert classify_role('Promoter & Director') == 'promoter'
    assert classify_role('Director') == 'director'


def test_three_relatives_and_an_huf_of_a_director_are_no_cluster(master, calendar, report, code):
    # Mkventures Capital (BSE 514238), 23 Sep 2026: four market buys at Rs 1,000, every filer "Directors Immediate
    # Relative"; Today showed "Cluster: Director Padma Bahety and 3 more bought 4.26%".
    # (dated 01 Sep here: the fixture's BSE rows are all made public on 08 Sep)
    rows = [bse(code, n, q, q * 1000, '01/09/2026', b=0, cat='Directors Immediate Relative')
            for n, q in (('Ankit Bahety', 15_000), ('Ankit Bahety and Sons HUF', 50_000), ('Padma Bahety', 50_000),
                         ('Sushil Bahety', 48_544))]
    out = run(master, calendar, report, bse_rows=rows)
    assert set(out['person_role']) == {'immediate_relative'}
    el = signals.eligible(out)
    assert len(el) == 4 and signals.clusters(el, pd.Timestamp('2026-09-10')).empty


# --- T2: pledge kinds from the transaction type; a blank BSE copy of an NSE pledge -------------------------------

def test_the_transaction_type_gives_the_kind_when_no_mode_is_filed():
    assert kind_from_type('PLEDGE REVOKE') == 'pledge_revoke' and kind_from_type('REVOKE') == 'pledge_revoke'
    assert kind_from_type('PLEDGE INVOKE') == 'pledge_invoke' and kind_from_type('INVOKE') == 'pledge_invoke'
    assert kind_from_type('PLEDGE') == 'pledge_create'
    assert kind_from_type('ACQUISITION') is None and kind_from_type(None) is None


def test_a_release_filed_without_a_mode_is_a_release(master, calendar, report, code):
    # BSE nightly, Paradeep Phosphates 19 Aug 2026: mode blank, transaction type REVOKE, 4,00,00,000 shares.
    row = bse(code, 'Zuari Maroc Phosphates Private Limited', 40_000_000, 6_036_000_000, '19/08/2026', mode='', tt='REVOKE',
              b=522_971_970, a=522_971_970)
    k = run(master, calendar, report, bse_rows=[row]).iloc[0]
    assert k['kind'] == 'pledge_revoke' and pd.isna(k['side']) and 'unrecognised_mode' not in k['flags']
    assert report.data['tables']['insider_trades']['kind_from_transaction_type'] == 1


def test_thyrocare_release_blank_on_bse_is_the_copy_of_nse_2325(master, calendar, report, code):
    # NSE appId 2325 (17 Aug 2026): Docon Technologies, Pledge Release, shares not kept by NSE's mapper then. BSE's
    # nightly copy: no mode, no type, 7,94,69,696 shares valued Rs 4,916 Cr, holding 8,12,00,000 unchanged.
    n = nse('Docon Technologies Private Limited', '', '', '2026-08-17', '2026-08-17', mode='Pledge Release', tt='Pledge',
            b=81_200_000, a=81_200_000, app='2325')
    b_ = bse(code, 'Docon Technologies Private Limited', 79_469_696, 49_159_953_946, '17/08/2026', mode='', tt='',
             b=81_200_000, a=81_200_000)
    out = run(master, calendar, report, [n], [b_]).set_index('exchange')
    assert out.loc['nse', 'kind'] == 'pledge_revoke' and out.loc['nse', 'quantity'] == 79_469_696
    assert out.loc['nse', 'is_primary'] and not out.loc['bse', 'is_primary']
    assert out.loc['bse', 'kind'] == 'pledge_revoke' and out.loc['bse', 'flags'] == ''


# --- T3: one trade kept more than once ---------------------------------------------------------------------------

def test_a_buy_filed_twice_with_other_holdings_counts_once(master, calendar, report, code):
    # VIP Industries (BSE 507880), 24 Dec 2025: Multiples Private Equity Gift Fund IV bought 1,39,14,505 shares for
    # Rs 539.88 Cr; BSE carries it twice, holdings 31,61,337 -> 1,70,75,842 and 31,52,461 -> 1,70,66,966.
    a = bse(code, 'Multiples Private Equity Gift Fund IV', 13_914_505, 5_398_819_591, '24/12/2025', b=3_161_337)
    b_ = bse(code, 'Multiples Private Equity Gift Fund IV', 13_914_505, 5_398_819_591, '24/12/2025', b=3_152_461)
    out = run(master, calendar, report, bse_rows=[a, b_])
    assert len(out) == 1 and signals.eligible(out)['value'].sum() == 5_398_819_591
    assert report.data['tables']['insider_trades']['removed']['refiled_with_other_holdings']['count'] == 1


def test_two_tranches_of_one_size_stay_two(master, calendar, report, code):
    # Billionbrains: 50,000 sold twice on one day, the second starting where the first ended.
    a = bse(code, 'Vikas Bansal', 50_000, 8_100_000, '24/11/2025', mode='Market Sale', tt='DISPOSAL', b=1_000_000)
    b_ = bse(code, 'Vikas Bansal', 50_000, 8_100_000, '24/11/2025', mode='Market Sale', tt='DISPOSAL', b=950_000)
    assert len(run(master, calendar, report, bse_rows=[a, b_])) == 2


def test_a_revision_whose_prev_app_id_we_do_not_hold_replaces_its_original(master, calendar, report, code):
    # Info Edge, Kapil Kapoor: 5,00,000 sold 18-20 Aug 2026 for Rs 68.05 Cr; appId 2427 (Original, 20 Aug) and 3962
    # (Revision, 08 Oct, prevAppId 47977, holdings corrected), each with its BSE copy. Counted twice before.
    orig = nse('Kapil Kapoor', 500_000, 680_478_416, '2026-08-18', '2026-08-20', mode='Market Sale', tt='Disposal',
               b=11_255_795, app='2427', sub='Original', cat='Director', bcast='20-Aug-2026 18:00:00')
    rev = nse('Kapil Kapoor', 500_000, 680_478_416, '2026-08-18', '2026-08-20', mode='Market Sale', tt='Disposal',
              b=11_555_795, app='3962', sub='Revision', prev='47977', cat='Director', bcast='06-Oct-2026 12:00:00')   # 08 Oct; the fixture runs on 07 Oct
    copies = [bse(code, 'Kapil Kapoor', 500_000, 680_478_416, '18/08/2026', mode='Market Sale', tt='DISPOSAL', b=h,
                  cat='Director') for h in (11_255_795, 11_555_795)]
    out = run(master, calendar, report, [orig, rev], copies)
    el = signals.eligible(out)
    assert el['app_id'].tolist() == ['3962'] and el['value'].sum() == 680_478_416
    assert out['is_primary'].sum() == 1


def test_the_same_release_from_two_nse_files_a_rupee_apart_counts_once(master, calendar, report, code):
    # Vikram Solar, 19 Feb 2026: Gyanesh Chaudhary Family Trust released 7,30,86,090 pledged shares; NSE's two files
    # value it Rs 15,775,632,527 (mode filed) and Rs 15,775,632,526 (no mode).
    kw = dict(tt='Pledge Revoke', b=73_086_090, a=73_086_090)
    one = nse('Gyanesh Chaudhary Family Trust', 73_086_090, 15_775_632_527, '2026-02-19', '2026-02-19',
              mode='Revokation of Pledge', app='', **kw)
    two = nse('Gyanesh Chaudhary Family Trust', 73_086_090, 15_775_632_526, '2026-02-19', '2026-02-19', mode='', app='', **kw)
    out = run(master, calendar, report, [one, two])
    assert len(out) == 1 and out.iloc[0]['mode_raw'] == 'Revokation of Pledge' and out.iloc[0]['kind'] == 'pledge_revoke'


def test_bse_block_deal_is_a_market_trade_and_pairs_with_nse(master, calendar, report, code):
    # Stylam Industries, 17 Feb 2026: Aica Kogyo bought 29,01,962 shares at Rs 2,250; NSE 'Market Purchase', BSE
    # 'Block Deal' (kind unrecognised, so the two copies never paired).
    assert classify_mode('Block Deal') == 'market' and classify_mode('Bulk Deal') == 'market'
    n = nse('Aica Kogyo Company Limited', 2_901_962, 6_529_414_500, '2026-02-17', '2026-02-17', b=1_694_906)
    b_ = bse(code, 'Aica Kogyo Company Limited', 2_901_962, 6_529_414_500, '17/02/2026', mode='Block Deal', b=1_694_906)
    out = run(master, calendar, report, [n], [b_])
    assert out['is_primary'].sum() == 1 and set(out['kind']) == {'market'}


def test_an_html_entity_in_a_name_is_the_same_filer():
    # P&G Hygiene, 19 Jun 2026: "Procter &amp; Gamble Home Products Private Limited" on one copy.
    assert entity_key('Procter &amp; Gamble Home Products Private Limited') == \
        entity_key('Procter & Gamble Home Products Private Limited')


# --- T4: shares moved inside the promoter group on the market -----------------------------------------------------

def test_a_promoter_group_buy_from_another_member_is_no_market_decision(master, calendar, report):
    # Bajaj Finserv, 27 Apr 2026: Bajaj Holdings & Investment (Promoters) bought 20,90,050 at Rs 1,770.40 and Bajaj
    # Auto Holdings (Promoter Group) sold 20,90,050 at Rs 1,770.67, in the block window.
    buy = nse('Bajaj Holdings & Investment Limited', 2_090_050, 3_700_224_520, '2026-04-27', '2026-04-27',
              cat='Promoters', b=612_742_140, app='1')
    sell = nse('Bajaj Auto Holdings Limited', 2_090_050, 3_700_779_428, '2026-04-27', '2026-04-27', mode='Market Sale',
               tt='Disposal', cat='Promoter Group', b=2_090_050, app='2')
    other = nse('A Fund', 2_090_050, 3_700_000_000, '2026-04-27', '2026-04-27', mode='Market Sale', tt='Disposal',
                cat='Other', b=5_000_000, app='3')
    out = run(master, calendar, report, [buy, sell, other]).set_index('person_name')
    for who in ('Bajaj Holdings & Investment Limited', 'Bajaj Auto Holdings Limited'):
        assert out.loc[who, 'kind'] == 'inter_se' and not out.loc[who, 'is_market']
        assert 'promoter_group_transfer' in out.loc[who, 'marks']
    assert out.loc['A Fund', 'is_market']
    assert report.data['tables']['insider_trades']['promoter_group_transfers_on_market'] == 2


def test_a_promoter_buy_against_an_outsiders_sale_stays_a_buy(master, calendar, report):
    buy = nse('Bajaj Holdings & Investment Limited', 1_000, 1_770_400, '2026-04-27', '2026-04-27', cat='Promoters', app='1')
    sell = nse('Some Director', 1_000, 1_770_400, '2026-04-27', '2026-04-27', mode='Market Sale', tt='Disposal',
               cat='Director', app='2')
    out = run(master, calendar, report, [buy, sell])
    assert out['is_market'].all()


# --- T5: Today: invocations, SAST encumbrances, promoters' own bulk/block deals -----------------------------------

REF = pd.Timestamp('2026-10-21')
SH = pd.DataFrame({'isin': ['INE0D0K01022', 'INE068V01023'], 'quarter_end': ['2026-09-30'] * 2,
                   'total_shares': [3.84e8, 1.6475e8]})


def test_an_invoked_pledge_is_a_warning_on_today():
    # Sigachi Industries: RPS Industries' 1,15,03,000 pledged shares invoked (NSE, PLEDGE INVOKE).
    t = pd.DataFrame([{'isin': 'INE0D0K01022', 'company': 'Sigachi Industries', 'nse_symbol': 'SIGACHI', 'is_primary': True,
                       'needs_review': False, 'person_role': 'promoter', 'person_id': 'rps-industries-private-limited',
                       'kind': 'pledge_invoke', 'quantity': 11_503_000.0, 'holding_before': 67_857_250.0,
                       'holding_after': 56_354_250.0, 'broadcast_date': '2026-10-01'}])
    ev = ideas.pledge_events(t, REF, SH)
    assert ev['kind'].tolist() == ['Pledge invoked'] and ev['list'].tolist() == ['warn']
    assert round(ev['pct_of_company'].iloc[0], 2) == round(11_503_000 / 3.84e8 * 100, 2)
    assert 'Pledge invoked' in dict(ideas.GROUPS['warn'])['Pledges']


def _sast(**kw):
    base = {'isin': 'INE0D0K01022', 'company': 'Horizon Industrial Parks Ltd', 'symbol': 'HORIZON', 'is_promoter': False,
            'acquirer_name': 'An Investor', 'mode': 'Market', 'action_type': 'Acquisition', 'pct_acquired': 6.0,
            'pct_sold': None, 'post_stake_pct': 6.0, 'instrument': None, 'transaction_date': '2026-10-01'}
    return {**base, **kw}


def test_a_sast_encumbrance_is_never_a_big_investor():
    # BSE Reg 29, 28 Sep 2026: "Deutsche Bank AG," for Horizon Industrial Parks, mode "Encumbrance Shares" (the trustee
    # pattern misses the name); Comfort Fincap, "Pledge Creation".
    s = pd.DataFrame([_sast(acquirer_name='Deutsche Bank AG,', mode='Encumbrance Shares'),
                      _sast(acquirer_name='Comfort Fincap Ltd', mode='Pledge Creation'),
                      _sast(acquirer_name='Real Buyer Fund', mode='Market')])
    ev = ideas.stake_events(s, REF)
    assert len(ev) == 1 and ev.iloc[0]['sentence'].startswith('Real Buyer Fund bought 6.00%')


def test_an_allotment_is_said_and_not_called_bought():
    s = pd.DataFrame([_sast(acquirer_name='Amit Kumar Saraogi', mode='Pref. Allotment', pct_acquired=21.42,
                            post_stake_pct=21.42)])
    assert ideas.stake_events(s, REF).iloc[0]['sentence'] == \
        'Amit Kumar Saraogi took 21.42% of the company (pref. allotment), now holds 21.42%'


def _deal(name, cid, side, qty, kind='fpi'):
    return {'isin': 'INE068V01023', 'company': 'Gland Pharma', 'nse_symbol': 'GLAND', 'exchange': 'bse',
            'date': '2026-09-04', 'client_name': name, 'client_id': cid, 'client_type': kind,
            'client_is_market_maker': False, 'is_primary': True, 'side': side, 'quantity': float(qty),
            'value': qty * 2826.6, 'signed_value': qty * 2826.6 * (1 if side == 'BUY' else -1), 'pct_of_mcap': None}


def test_a_promoters_block_sale_is_the_promoter_not_funds_selling():
    # Gland Pharma, BSE 04 Sep 2026: Fosun Pharma Industrial Pte (promoter, in the promoter-group list) sold
    # 1,74,02,500 shares; mutual funds and others bought. Today read the net as "Funds selling".
    deals = pd.DataFrame([_deal('Fosun Pharma Industrial Pte. LTD.', 'fosun-pharma-industrial-pte-limited', 'SELL', 17_402_500),
                          _deal('Kotak Mahindra Mutual Fund', 'kotak-mahindra-mutual-fund', 'BUY', 2_793_000, 'mutual_fund'),
                          _deal('Societe Generale', 'societe-generale', 'BUY', 400_000)])
    group = pd.DataFrame({'isin': ['INE068V01023'], 'quarter_end': ['2026-09-30'],
                          'member_id': ['fosun-pharma-industrial-pte-limited'], 'member_alt_id': [None]})
    marked, rep = mark_deal_promoters(deals, group, None)
    assert marked['client_is_promoter'].tolist() == [True, False, False] and rep['by_list'] == 1
    assert ideas.fund_events(marked, None, REF, sh=SH)['kind'].tolist() == ['Fund buying']
    prom = ideas.promoter_deal_events(marked, None, REF, sh=SH)
    assert prom['kind'].tolist() == ['Promoter selling'] and round(prom['pct_of_company'].iloc[0], 2) == 10.56
    # A PIT promoter market trade in the period already says it: no second line from the deal.
    pit = pd.DataFrame([{'isin': 'INE068V01023', 'person_role': 'promoter', 'is_market': True, 'broadcast_date': '2026-09-06'}])
    assert ideas.promoter_deal_events(marked, pit, REF, sh=SH).empty
