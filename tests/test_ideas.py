"""Today's lists (insiders_clean/ideas.py), on cases shaped like real filings."""
import pandas as pd

from insiders_clean import ideas

REF = pd.Timestamp('2026-10-19')


def row(isin, sym, person, role, side, qty, price, day, frm=None, token=False):
    v = qty * price
    return {'isin': isin, 'company': sym.title(), 'nse_symbol': sym, 'person_id': person.lower().replace(' ', '-'),
            'person_name': person, 'person_role': role, 'side': side, 'quantity': qty, 'price': price, 'value': v,
            'signed_value': v if side == 'BUY' else -v, 'pct_of_mcap': v / 4612e7 * 100, 'market_cap': 4612e7,
            'seen': pd.Timestamp(day), 'trade_date_to': pd.Timestamp(day) - pd.Timedelta(days=2),
            'trade_date_from': pd.Timestamp(frm or day) - pd.Timedelta(days=2), 'is_token': token, 'is_market': True}


def electrosteel():
    """The 01 Oct 2026 filing: seven promoter-group buyers, 2,71,42,650 shares, Rs 194.95 Cr."""
    buys = [('Tulsi Highrise Private Limited', 'promoter_group', 3163250, 72.61), ('Wilcox Merchants Private Limited', 'promoter_group', 4825000, 71.59),
            ('Mayank Kejriwal', 'promoter', 8397600, 71.43), ('Asha Kejriwal', 'promoter_group', 5594400, 71.49),
            ('Nityangi Kejriwal Jaiswal', 'promoter_group', 1720800, 72.60), ('Priya Sakhi Kejriwal Mehta', 'promoter_group', 1720000, 72.62),
            ('Madhav Kejriwal', 'promoter', 1721600, 72.51)]
    return [row('INE086A01029', 'ELECTCAST', p, r, 'BUY', q, pr, '2026-10-01') for p, r, q, pr in buys]


SH = pd.DataFrame({'isin': ['INE086A01029'] * 2 + ['INE000PLEDGE'] * 2, 'symbol': ['ELECTCAST'] * 2 + ['PLEDGECO'] * 2,
                   'company': ['Electrosteel Castings'] * 2 + ['Pledge Co'] * 2,
                   'quarter_end': pd.to_datetime(['2026-06-30', '2026-09-30'] * 2),
                   'total_shares': [618.1e6, 618.1e6, 1e8, 1e8], 'promoter_pledge_pct': [9.7, 9.7, 8.0, 18.0],
                   'promoter_holding_pct': [50.1, 54.5, 60.0, 60.0], 'public_holding_pct': [49.9, 45.5, 40.0, 40.0]})


def test_a_promoter_group_is_one_idea_sized_in_shares():
    t = pd.DataFrame(electrosteel())
    out = ideas.worth_a_look(t, REF, SH)
    assert len(out) == 1
    r = out.iloc[0]
    assert r['decision_makers'] == 1 and 'Promoter buying' in r['kinds'] and 'Cluster' not in r['kinds']
    assert abs(r['pct_of_company'] - 27142650 / 618.1e6 * 100) < 1e-9 and r['pct_basis'] == 'shares'
    assert r['sentence'].startswith('Promoter group (7 entities) bought 4.39% of the company on the market')


def test_one_lakh_a_day_is_steady_accumulation_and_small_one_offs_are_not():
    steady = [row('INE111A01011', 'STEADY', 'Ravi Promoter', 'promoter', 'BUY', 1000, 100, d)
              for d in pd.bdate_range('2026-08-03', periods=12)]
    small = [row('INE222A01011', 'SMALLBUY', 'Dee Director', 'director', 'BUY', 2000, 100, '2026-10-10')]   # Rs 2 lakh, once
    out = ideas.worth_a_look(pd.DataFrame(steady + small), REF)
    assert list(out['nse_symbol']) == ['STEADY']
    assert 'Steady accumulation' in out.iloc[0]['kinds'] and 'on 12 days' in out.iloc[0]['sentence']


def test_a_kind_that_did_worse_than_the_index_stays_off_today():
    t = pd.DataFrame([row('INE333A01011', 'OFFICERCO', 'Kim Kmp', 'kmp', 'BUY', 400000, 100, '2026-10-10')])   # Rs 4 Cr
    behind = pd.DataFrame({'signal': ['officer_buy'] * 2, 'horizon': ['3M', '6M'], 'cases': [40, 35],
                           'median_excess': [-3.0, -4.0], 'beat_index': [40.0, 38.0]})
    assert ideas.worth_a_look(t, REF, summary=behind).empty
    assert len(ideas.worth_a_look(t, REF)) == 1   # not measured yet: shown, studies support it


def test_watch_out_lists_promoter_sales_before_pledge_rises():
    sell = [row('INE444A01011', 'SELLCO', 'Promo Seller', 'promoter', 'SELL', 3_000_000, 50, '2026-10-15')]
    out = ideas.watch_out(pd.DataFrame(sell), REF, SH)
    assert list(out['kind']) == ['Promoter selling', 'Pledge rising']
    assert 'up from 8.0%' in out.iloc[1]['sentence']


def test_other_kinds_reach_today_across_the_market():
    """Preferential to promoters (premium and discount), a big investor crossing 5%, fund net buying, pledge
    created and released, a buyback at a premium: each becomes one row in the right list, sized in % of the company."""
    sh = pd.concat([SH, pd.DataFrame({'isin': ['INE555A01011', 'INE666A01011', 'INE777A01011', 'INE888A01011'],
                                      'symbol': ['PREMCO', 'DISCCO', 'FUNDCO', 'BUYBACKCO'], 'company': ['P', 'D', 'F', 'B'],
                                      'quarter_end': pd.to_datetime(['2026-09-30'] * 4), 'total_shares': [1e8] * 4,
                                      'promoter_pledge_pct': [0.0] * 4})], ignore_index=True)
    issues = pd.DataFrame({'isin': ['INE555A01011', 'INE666A01011'], 'symbol': ['PREMCO', 'DISCCO'], 'company': ['P', 'D'],
                           'allottee_category': ['PROMOTER', 'PROMOTER'], 'vs_market': [12.0, -18.0],
                           'shares_allotted': [2e6, 1e6], 'securities_proposed': [None, None], 'instruments': ['Warrants', 'Equity'],
                           'posted_on': pd.to_datetime(['2026-10-05', '2026-10-06']), 'status': ['Allotted or listed'] * 2, 'amount': [5e8, 1e8]})
    sast = pd.DataFrame({'isin': ['INE111B01011'], 'symbol': ['STAKECO'], 'company': ['S'], 'is_promoter': [False],
                         'acquirer_name': ['A Big Fund'], 'pct_acquired': [1.2], 'pct_sold': [None], 'post_stake_pct': [5.4],
                         'broadcast_date': pd.to_datetime(['2026-10-10'])})
    deals = pd.DataFrame({'isin': ['INE777A01011'] * 2, 'company': ['F'] * 2, 'nse_symbol': ['FUNDCO'] * 2,
                          'client_id': ['sbi-mutual-fund', 'hdfc-mutual-fund'], 'client_name': ['SBI Mutual Fund', 'HDFC Mutual Fund'],
                          'client_type': ['mutual_fund'] * 2, 'client_is_market_maker': [False] * 2, 'is_primary': [True] * 2,
                          'side': ['BUY', 'BUY'], 'pct_of_mcap': [0.2, 0.15], 'value': [2e7, 1.5e7], 'date': pd.to_datetime(['2026-10-14'] * 2)})
    trades = pd.DataFrame([{**row('INE086A01029', 'ELECTCAST', 'Asha Kejriwal', 'promoter_group', 'BUY', 1_000_000, 70, '2026-10-12'),
                            'kind': 'pledge_create', 'is_primary': True, 'needs_review': False, 'broadcast_date': '2026-10-12'}])
    bb = pd.DataFrame({'isin': ['INE888A01011'], 'symbol': ['BUYBACKCO'], 'company': ['B'], 'route': ['tender'], 'vs_market': [22.0],
                       'offer_open': pd.to_datetime(['2026-10-25']), 'record_date': pd.to_datetime(['2026-10-15']),
                       'shares_sought': [3e6], 'offer_value': [6e9]})
    look, warn = ideas.today([ideas.issue_events(issues, REF, sh), ideas.stake_events(sast, REF), ideas.fund_events(deals, None, REF),
                              ideas.pledge_events(trades, REF, sh), ideas.buyback_events(bb, REF, sh)])
    kinds = dict(zip(look['nse_symbol'], look['kind']))
    assert kinds == {'BUYBACKCO': 'Buyback at a premium', 'PREMCO': 'Promoters pay up', 'STAKECO': 'Big investor in', 'FUNDCO': 'Fund buying'}
    assert list(look['nse_symbol'])[:2] == ['BUYBACKCO', 'PREMCO']          # by % of the company: 3.0% then 2.0%
    assert 'warrants' in look.loc[look['nse_symbol'] == 'PREMCO', 'sentence'].iloc[0]
    assert set(zip(warn['nse_symbol'], warn['kind'])) == {('DISCCO', 'Cheap shares to promoters'), ('ELECTCAST', 'Pledge created')}


def test_a_kind_measured_behind_the_index_is_left_off_worth_a_look():
    deals = pd.DataFrame({'isin': ['INE777A01011'], 'company': ['F'], 'nse_symbol': ['FUNDCO'], 'client_id': ['x'], 'client_name': ['X Fund'],
                          'client_type': ['mutual_fund'], 'client_is_market_maker': [False], 'is_primary': [True], 'side': ['BUY'],
                          'pct_of_mcap': [0.6], 'value': [5e7], 'date': pd.to_datetime(['2026-10-14'])})
    behind = pd.DataFrame({'signal': ['fund_deal_buy'] * 2, 'horizon': ['3M', '6M'], 'cases': [174, 120],
                           'median_excess': [-2.7, -3.1], 'beat_index': [41.0, 39.0]})
    look, _ = ideas.today([ideas.fund_events(deals, None, REF)], behind)
    assert look.empty
