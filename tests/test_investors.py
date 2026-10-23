"""Investors (insiders_clean/investors.py, fund_managers.py): net buying and selling per investor from bulk and block deals."""
import pandas as pd

from insiders_clean import fund_managers, investors

REF = pd.Timestamp('2026-10-19')


def deal(client, side, value, isin='INE001A01011', day='2026-10-10', typ='mutual_fund', conf='high', group=None, mm=False,
         primary=True, pct=0.1, company='Alpha Ltd', symbol='ALPHA', cid=None):
    return {'deal_id': f'{client}{day}{side}{value}{isin}', 'is_primary': primary, 'client_is_market_maker': mm, 'date': pd.Timestamp(day),
            'isin': isin, 'company': company, 'nse_symbol': symbol, 'client_id': cid or client.lower().replace(' ', '-'),
            'client_name': client, 'client_type': typ, 'client_type_confidence': conf, 'investor_group': group or client,
            'investor_group_id': (group or client).lower().replace(' ', '-'), 'side': side, 'value': value,
            'signed_value': value if side == 'BUY' else -value, 'pct_of_mcap': pct}


def deals():
    return pd.DataFrame([
        deal('SBI MUTUAL FUND', 'BUY', 300e7, pct=0.9, isin='INE001A01011'),
        deal('SBI MUTUAL FUND', 'BUY', 100e7, pct=0.3, isin='INE002A01011', company='Beta Ltd', symbol='BETA'),
        deal('SBI MUTUAL FUND', 'SELL', 20e7, pct=0.1, isin='INE002A01011', company='Beta Ltd', symbol='BETA'),
        deal('GQG PARTNERS EMERGING MARKETS EQUITY FUND', 'BUY', 200e7, typ='fpi', conf='medium', group='GQG Fund A'),
        deal('GQG PARTNERS INTERNATIONAL QUALITY EQUITY FUND', 'BUY', 150e7, typ='fpi', conf='medium', group='GQG Fund B'),
        deal('Pastel Limited', 'SELL', 500e7, typ='corporate', conf='medium'),                       # not a fund type
        deal('Citadel Securities', 'BUY', 900e7, typ='prop_hft', mm=True),                          # market maker
        deal('Copy Fund', 'BUY', 700e7, primary=False),                                             # not a primary leg
        deal('Old Fund', 'BUY', 700e7, day='2026-06-01'),                                           # outside the period
        deal('Elm Park Fund Limited', 'SELL', 200e7, typ='fund_other', conf='low', pct=0.4),
        deal('Churn Fund', 'BUY', 500e7), deal('Churn Fund', 'SELL', 495e7)])


def test_real_deals_are_primary_legs_of_the_period_by_institutions_without_market_makers():
    d = investors.real_deals(deals(), REF, 30)
    names = set(d['client_name'])
    assert 'Citadel Securities' not in names and 'Copy Fund' not in names and 'Old Fund' not in names and 'Pastel Limited' not in names
    assert {'SBI MUTUAL FUND', 'Elm Park Fund Limited'} <= names
    assert 'Pastel Limited' in set(investors.real_deals(deals(), REF, 30, types='all')['client_name'])
    assert investors.real_deals(deals().iloc[:0], REF, 30).empty and investors.real_deals(None, REF, 30).empty


def test_net_is_buying_minus_selling_with_gross_beside_it_and_the_largest_position():
    out = investors.net_by_investor(deals(), REF, 30).set_index('investor')
    sbi = out.loc['SBI MUTUAL FUND']
    assert sbi['buy'] == 400e7 and sbi['sell'] == 20e7 and sbi['net'] == 380e7 and sbi['companies'] == 2
    assert sbi['largest_symbol'] == 'ALPHA' and sbi['largest_net'] == 300e7 and abs(sbi['largest_pct'] - 0.9) < 1e-9
    assert sbi['type'] == 'mutual_fund' and sbi['confidence'] == 'high'
    churn = out.loc['Churn Fund']
    assert churn['net'] == 5e7 and churn['buy'] == 500e7 and churn['sell'] == 495e7          # not "Rs 5 Cr" alone
    assert list(investors.net_by_investor(deals(), REF, 30).columns) == investors.COLUMNS


def test_one_investor_is_one_investor_group_whatever_the_spellings_and_never_a_fund_family():
    d = deals()
    d = pd.concat([d, pd.DataFrame([deal('HDFC STANDARD LIFE INSURANCE CO LTD', 'BUY', 40e7, typ='insurer', group='HDFC Life', cid='hdfc-a'),
                                    deal('HDFC STANDARD LIFE INSURANCE', 'BUY', 60e7, typ='insurer', group='HDFC Life', cid='hdfc-b')])])
    out = investors.net_by_investor(d, REF, 30).set_index('investor')
    assert out.loc['HDFC Life', 'net'] == 100e7 and out.loc['HDFC Life', 'n_names'] == 2
    assert 'GQG Fund A' in out.index and 'GQG Fund B' in out.index                             # two funds stay two investors


def test_the_floor_is_25_crore_net_or_a_quarter_percent_of_one_company():
    out = investors.floored(investors.net_by_investor(deals(), REF, 30)).set_index('investor')
    assert 'SBI MUTUAL FUND' in out.index and 'GQG Fund A' in out.index
    assert 'Churn Fund' not in out.index                                                       # Rs 5 Cr net, 0.1% of a company
    assert 'Elm Park Fund Limited' in out.index                                                # Rs 200 Cr net anyway
    small = pd.DataFrame([deal('Small Fund', 'BUY', 10e7, pct=0.25, typ='fpi')])
    assert len(investors.floored(investors.net_by_investor(small, REF, 30))) == 1               # 0.25% of one company qualifies
    just_under = pd.DataFrame([deal('Under Fund', 'BUY', 24e7, pct=0.24, typ='fpi')])
    assert investors.floored(investors.net_by_investor(just_under, REF, 30)).empty


def test_a_low_confidence_type_stays_out_of_the_default_view_and_is_counted():
    inv = investors.floored(investors.net_by_investor(deals(), REF, 30))
    kept, left_out = investors.split_confidence(inv)
    assert 'Elm Park Fund Limited' not in set(kept['investor']) and left_out == 1
    again, none = investors.split_confidence(inv, include_low=True)
    assert 'Elm Park Fund Limited' in set(again['investor']) and none == 0


def test_buyers_and_sellers_rank_by_rupees_or_by_the_share_of_the_largest_company():
    inv = investors.floored(investors.net_by_investor(deals(), REF, 30))
    buy, sell = investors.buyers_sellers(inv, by='value')
    assert buy['investor'].iloc[0] == 'SBI MUTUAL FUND' and (buy['net'] > 0).all() and (sell['net'] < 0).all()
    assert sell['investor'].tolist() == ['Elm Park Fund Limited']
    by_share, _ = investors.buyers_sellers(inv, by='share')
    assert by_share['largest_pct'].abs().is_monotonic_decreasing


def test_net_by_type_covers_every_institution_type():
    t = investors.by_type(deals(), REF, 30).set_index('type')
    assert t.loc['mutual_fund', 'net'] == 380e7 + 5e7 and t.loc['fpi', 'net'] == 350e7
    assert t.loc['fund_other', 'net'] == -200e7 and 'corporate' not in t.index and 'prop_hft' not in t.index


# ---- fund managers named in the fund's name ------------------------------------------------------------------------

GQG_NAMES = ['GQG PARTNERS EMERGING MARKETS EQUITY FUND', 'GQG PARTNERS EMERGING MARKETS EQUITY FUND A SUB FUND OF GQG GLOBAL UCITS ICAV',
             'BBH GQG PARTNERS EMERGING MARKETS EQUITY MASTER FUND LP',
             'GOLDMAN SACHS TRUST II - GOLDMAN SACHS GQG PARTNERS INTERNATIONAL OPPORTUNITIES FUND', 'JNL/GQG EMERGING MARKETS EQUITY FUND',
             'WITAN INVESTMENT TRUST PLC RE GQG PARTNERS LLC']


def test_a_manager_is_the_one_the_fund_name_names_and_a_sponsors_fund_is_marked_sub_advised():
    got = {n: fund_managers.manager_of(n) for n in GQG_NAMES}
    assert all(m[0] == 'GQG Partners' for m in got.values())
    assert [got[n][1] for n in GQG_NAMES] == [False, False, False, True, True, True]
    assert fund_managers.manager_of('GSF II GOLDMAN SACHS GLOBAL MULTI MANAGER ALTERNATIVES PORTFOLIO')[0] == 'Goldman Sachs'
    assert fund_managers.manager_of('FIDELITY FUNDS ASIAN SMALLER COMPANIES POOL')[0] == 'Fidelity'
    assert fund_managers.manager_of('SBI MUTUAL FUND') == (None, False, None)                    # no line: blank, never guessed
    assert fund_managers.manager_of(None) == (None, False, None) and fund_managers.manager_of(float('nan'))[0] is None


def test_every_manager_line_has_a_reason_and_a_valid_pattern():
    rules = fund_managers.load()
    assert len(rules) >= 3 and all(r[3].strip() for r in rules)


def test_by_manager_groups_fund_names_beside_the_investors_and_counts_sub_advised():
    rows = [deal(n, 'BUY', 100e7, typ='fpi', conf='medium', group=n.title()) for n in GQG_NAMES] \
        + [deal('SBI MUTUAL FUND', 'BUY', 50e7), deal('GQG PARTNERS EMERGING MARKETS EQUITY FUND', 'SELL', 10e7, typ='fpi', group='Gqg A')]
    d = pd.DataFrame(rows)
    out = investors.by_manager(d, REF, 30)
    assert out['manager'].tolist() == ['GQG Partners']                                           # SBI Mutual Fund has no line
    r = out.iloc[0]
    assert r['funds'] == 6 and r['sub_advised'] == 3 and r['buy'] == 600e7 and r['sell'] == 10e7 and r['net'] == 590e7
    inv = investors.net_by_investor(d, REF, 30)
    assert len(inv[inv['investor'].str.contains('Gqg|Qg', case=False)]) >= 6                      # still separate investors
    assert investors.by_manager(pd.DataFrame([deal('SBI MUTUAL FUND', 'BUY', 1e9)]), REF, 30).empty


def test_unmatched_lists_the_fund_names_worth_a_new_line():
    d = pd.DataFrame([deal('NEW MANAGER GLOBAL FUND', 'BUY', 900e7, typ='fpi'), deal('GQG PARTNERS X FUND', 'BUY', 500e7, typ='fpi'),
                      deal('SMALL FUND', 'BUY', 1e7, typ='fpi'), deal('Pastel Limited', 'SELL', 999e7, typ='corporate')])
    out = fund_managers.unmatched(d)
    assert out['client_name'].tolist() == ['NEW MANAGER GLOBAL FUND', 'SMALL FUND']


# ---- the investor's own page -----------------------------------------------------------------------------------

def test_profile_gathers_every_name_of_the_investor_group_from_either_id():
    d = pd.DataFrame([deal('HDFC STANDARD LIFE INSURANCE CO LTD', 'BUY', 40e7, typ='insurer', group='HDFC Life', cid='hdfc-a'),
                      deal('HDFC STANDARD LIFE INSURANCE', 'SELL', 10e7, typ='insurer', group='HDFC Life', cid='hdfc-b'),
                      deal('SBI MUTUAL FUND', 'BUY', 50e7, cid='sbi'),
                      deal('Copy Leg', 'BUY', 5e7, group='HDFC Life', cid='hdfc-c', primary=False)])
    for eid in ('hdfc-a', 'hdfc-b', 'hdfc-life'):                       # a client id or the group's own id
        got, gid = investors.profile_deals(d, eid)
        assert gid == 'hdfc-life' and sorted(got['client_id']) == ['hdfc-a', 'hdfc-b']     # primary legs only
    got, gid = investors.profile_deals(d, 'sbi')
    assert got['client_id'].tolist() == ['sbi'] and gid == 'sbi-mutual-fund'
    assert investors.profile_deals(d, 'nobody')[0].empty and investors.profile_deals(None, 'x')[0].empty


def test_by_company_nets_one_investors_deals_per_company():
    d = pd.DataFrame([deal('SBI MUTUAL FUND', 'BUY', 300e7, pct=0.9), deal('SBI MUTUAL FUND', 'SELL', 100e7, pct=0.3),
                      deal('SBI MUTUAL FUND', 'BUY', 100e7, isin='INE002A01011', company='Beta Ltd', symbol='BETA', pct=0.2)])
    out = investors.by_company(d, REF, 30).set_index('isin')
    assert out.loc['INE001A01011', ['buy', 'sell', 'net']].tolist() == [300e7, 100e7, 200e7]
    assert abs(out.loc['INE001A01011', 'pct'] - 0.6) < 1e-9 and out['net'].abs().is_monotonic_decreasing
    assert investors.by_company(None, REF, 30).empty
