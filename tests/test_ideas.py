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


def test_a_kind_measured_behind_the_index_still_shows_with_its_tag():
    """Owner, 21 Oct: evidence is a tag, never a filter (promoters buy for the quarters and years ahead)."""
    t = pd.DataFrame([row('INE333A01011', 'OFFICERCO', 'Kim Kmp', 'kmp', 'BUY', 400000, 100, '2026-10-10')])   # Rs 4 Cr
    behind = pd.DataFrame({'signal': ['officer_buy'] * 2, 'horizon': ['3M', '6M'], 'cases': [40, 35],
                           'median_excess': [-3.0, -4.0], 'beat_index': [40.0, 38.0]})
    look, _ = ideas.today([ideas.insider_events(t, REF, summary=behind)], behind)
    assert list(look['nse_symbol']) == ['OFFICERCO'] and look.iloc[0]['group'] == 'Insiders buying'
    assert look.iloc[0]['reads']['Director or KMP buying'] == 'drag'


def test_watch_out_lists_promoter_sales_largest_first():
    sell = [row('INE444A01011', 'SELLCO', 'Promo Seller', 'promoter', 'SELL', 3_000_000, 50, '2026-10-15'),
            row('INE445A01011', 'SMALLSELL', 'Other Promoter', 'promoter', 'SELL', 1_000_000, 50, '2026-10-15')]
    out = ideas.watch_out(pd.DataFrame(sell), REF)
    assert list(out['nse_symbol']) == ['SELLCO', 'SMALLSELL'] and set(out['kind']) == {'Promoter selling'}


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
    # by group (ideas.GROUPS), then % of the company inside a group: the big investor's 1.2% before the funds' 0.35%
    assert list(look['nse_symbol']) == ['PREMCO', 'STAKECO', 'FUNDCO', 'BUYBACKCO']
    assert list(look['group']) == ['Promoters pay up', 'Big investors and funds in', 'Big investors and funds in', 'Buybacks at a premium']
    assert 'warrants' in look.loc[look['nse_symbol'] == 'PREMCO', 'sentence'].iloc[0]
    assert set(zip(warn['nse_symbol'], warn['kind'])) == {('DISCCO', 'Cheap shares to promoters'), ('ELECTCAST', 'Pledge created')}


def test_fund_buying_measured_behind_shows_tagged_behind():
    deals = pd.DataFrame({'isin': ['INE777A01011'], 'company': ['F'], 'nse_symbol': ['FUNDCO'], 'client_id': ['x'], 'client_name': ['X Fund'],
                          'client_type': ['mutual_fund'], 'client_is_market_maker': [False], 'is_primary': [True], 'side': ['BUY'],
                          'pct_of_mcap': [0.6], 'value': [5e7], 'date': pd.to_datetime(['2026-10-14'])})
    behind = pd.DataFrame({'signal': ['fund_deal_buy'] * 2, 'horizon': ['3M', '6M'], 'cases': [174, 120],
                           'median_excess': [-2.7, -3.1], 'beat_index': [41.0, 39.0]})
    look, _ = ideas.today([ideas.fund_events(deals, None, REF)], behind)
    assert list(look['kind']) == ['Fund buying'] and look.iloc[0]['reads'] == {'Fund buying': 'drag'}


def test_a_lenders_trustee_or_security_agent_is_no_big_investor():
    """Real SAST filings of Oct 2026: shares held as security for bonds or loans."""
    names = ['GLAS Agency (Hong Kong) Limited (as trustee and security agent for the holders of the Tap Bonds)',
             'Catalyst Trusteeship Limited acting in its capacity as the debenture trustee on behalf of',
             'Deutsche Bank AG, Singapore Branch', 'Vistra ITCL (India) Limited', 'HSBC Mutual Fund']
    sast = pd.DataFrame({'isin': [f'INE{i}00A01011' for i in range(5)], 'symbol': list('ABCDE'), 'company': list('ABCDE'),
                         'is_promoter': [False] * 5, 'acquirer_name': names, 'pct_acquired': [56.38, 22.67, 75.4, 28.06, 1.88],
                         'pct_sold': [None] * 5, 'post_stake_pct': [56.38, 22.67, 75.4, 28.06, 6.63],
                         'broadcast_date': pd.to_datetime(['2026-10-10'] * 5)})
    out = ideas.stake_events(pd.concat([sast, sast.tail(1)], ignore_index=True), REF)   # HSBC seen twice (both exchanges)
    assert list(out['nse_symbol']) == ['E'] and out.iloc[0]['sentence'].startswith('HSBC Mutual Fund bought 1.88%')


def pledge(day, kind, qty):
    return {**row('INE0AEQUS011', 'AEQUS', 'Melligeri Private Family Foundation', 'promoter', 'BUY', qty, 0, day),
            'kind': kind, 'is_primary': True, 'needs_review': False, 'broadcast_date': day}


def test_pledges_are_netted_so_a_renewal_is_counted_once():
    """Aequs, Sep-Oct 2026: the same 10.05 crore shares pledged, released, pledged again."""
    sh = pd.DataFrame({'isin': ['INE0AEQUS011'], 'symbol': ['AEQUS'], 'company': ['Aequs'],
                       'quarter_end': pd.to_datetime(['2026-09-30']), 'total_shares': [670e6]})
    t = pd.DataFrame([pledge('2026-09-21', 'pledge_create', 100513070), pledge('2026-10-09', 'pledge_revoke', 100513070),
                      pledge('2026-10-15', 'pledge_create', 100513070)])
    out = ideas.pledge_events(t, REF, sh)
    assert len(out) == 1 and out.iloc[0]['kind'] == 'Pledge created'
    assert abs(out.iloc[0]['pct_of_company'] - 100513070 / 670e6 * 100) < 1e-9
    assert '(2 pledged, 1 released)' in out.iloc[0]['sentence']
    assert ideas.pledge_events(t.iloc[:2], REF, sh).empty      # pledged and released in full: nothing


def test_a_quarterly_pledge_change_shows_only_in_the_period_it_was_made_public():
    """Race Eco Chain, Sep 2026 XBRL: promoters' 77,30,100 shares all pledged, none in June."""
    sh = pd.DataFrame({'isin': ['INE0RACE0011'] * 2, 'symbol': ['RACE'] * 2, 'company': ['Race Eco Chain'] * 2,
                       'quarter_end': pd.to_datetime(['2026-06-30', '2026-09-30']),
                       'submission_date': pd.to_datetime(['2026-07-04', '2026-10-07']), 'total_shares': [17.26e6] * 2,
                       'promoter_pledge_pct': [0.0, 100.0], 'promoter_pledged_shares': [0, 7730100], 'xbrl_status': ['ok', 'ok']})
    assert ideas.pledge_events(None, REF, sh, days=30).iloc[0]['kind'] == 'Pledge rising'
    assert ideas.pledge_events(None, REF, sh, days=7).empty                  # made public 07 Oct, 12 days before
    assert ideas.pledge_events(None, REF, sh.assign(xbrl_status=['pending', 'ok']), days=30).empty


def test_each_period_counts_only_its_own_days():
    t = pd.DataFrame([row('INE555B01011', 'OLDBUY', 'Old Promoter', 'promoter', 'BUY', 500000, 100, '2026-08-20'),
                      row('INE556B01011', 'NEWBUY', 'New Promoter', 'promoter', 'BUY', 500000, 100, '2026-10-19')])
    got = {d: set(ideas.insider_events(t, REF, days=d)['nse_symbol']) for d in ideas.PERIODS.values()}
    assert got == {1: {'NEWBUY'}, 7: {'NEWBUY'}, 30: {'NEWBUY'}, 90: {'NEWBUY', 'OLDBUY'}}


def test_a_pledge_cannot_exceed_what_the_person_holds():
    """Aequs as stored before 22 Oct: NSE's release of 08 Oct carries no shares, the pledges around it do."""
    sh = pd.DataFrame({'isin': ['INE0AEQUS011'], 'symbol': ['AEQUS'], 'company': ['Aequs'],
                       'quarter_end': pd.to_datetime(['2026-09-30']), 'total_shares': [670665635]})
    rows = [pledge('2026-09-21', 'pledge_create', 100513070), {**pledge('2026-10-09', 'pledge_revoke', 0), 'quantity': None},
            pledge('2026-10-15', 'pledge_create', 100513070)]
    t = pd.DataFrame([{**r, 'holding_before': 100513070, 'holding_after': 100513070} for r in rows])
    out = ideas.pledge_events(t, REF, sh)
    assert abs(out.iloc[0]['pct_of_company'] - 100513070 / 670665635 * 100) < 1e-9      # 14.99%, as the 30 Sep XBRL


def test_a_stake_filed_as_voting_rights_or_warrants_is_not_called_bought():
    sast = pd.DataFrame({'isin': ['INE0JSIPL011', 'INE0HSBC0011'], 'symbol': ['JSIPL', 'THYROCARE'], 'company': ['J', 'T'],
                         'is_promoter': [False, False], 'acquirer_name': ['Craft Emerging Marketing Fund PCC', 'HSBC Mutual Fund'],
                         'pct_acquired': [5.79, 1.88], 'pct_sold': [None, None], 'post_stake_pct': [5.79, 6.63],
                         'instrument': ['Voting Rights other than by shares', 'Equity shares'],
                         'broadcast_date': pd.to_datetime(['2026-10-10'] * 2)})
    out = dict(zip(ideas.stake_events(sast, REF)['nse_symbol'], ideas.stake_events(sast, REF)['sentence']))
    assert out['JSIPL'] == ('Craft Emerging Marketing Fund PCC took 5.79% of the company '
                            '(filed as voting rights other than by shares, not shares), now holds 5.79%')
    assert out['THYROCARE'].startswith('HSBC Mutual Fund bought 1.88%')


def test_fund_nets_are_shares_over_total_shares_when_the_xbrl_gives_the_total():
    """RHI Magnesita, 22 Sep 2026 block deals at Rs 360: SBI, Nippon and Bandhan MFs bought 2,19,41,224 shares."""
    deals = pd.DataFrame({'isin': ['INE0RHIM0011'] * 3, 'company': ['RHI'] * 3, 'nse_symbol': ['RHIM'] * 3,
                          'client_id': list('abc'), 'client_name': ['SBI Mutual Fund', 'Nippon India Mutual Fund', 'Bandhan Mutual Fund'],
                          'client_type': ['mutual_fund'] * 3, 'client_is_market_maker': [False] * 3, 'is_primary': [True] * 3,
                          'side': ['BUY'] * 3, 'quantity': [16666667, 2496780, 2777777], 'pct_of_mcap': [7.7, 1.2, 1.3],
                          'value': [q * 360 for q in (16666667, 2496780, 2777777)], 'date': pd.to_datetime(['2026-09-22'] * 3)})
    sh = pd.DataFrame({'isin': ['INE0RHIM0011'], 'quarter_end': pd.to_datetime(['2026-09-30']), 'total_shares': [206500000]})
    out = ideas.fund_events(deals, None, REF, sh=sh).iloc[0]
    assert abs(out['pct_of_company'] - 21941224 / 206500000 * 100) < 1e-9
    assert abs(ideas.fund_events(deals, None, REF).iloc[0]['pct_of_company'] - 10.2) < 1e-9   # no total: value basis


def test_a_pledge_row_names_the_lender_from_reg_31():
    """Reg 31 names who holds the shares (free text, as filed); the row's figures stay the PIT filings'."""
    sh = pd.DataFrame({'isin': ['INE0AEQUS011'], 'symbol': ['AEQUS'], 'company': ['Aequs'],
                       'quarter_end': pd.to_datetime(['2026-09-30']), 'total_shares': [670e6]})
    t = pd.DataFrame([pledge('2026-10-15', 'pledge_create', 100513070)])
    enc = pd.DataFrame({'symbol': ['AEQUS', 'AEQUS', 'AEQUS', 'OTHER'],
                        'event_type': ['Creation', 'Creation', 'Release', 'Creation'],
                        'encumbrance_type': ['Pledge', 'Non disposal undertaking', 'Pledge', 'Pledge'],
                        'lender': ['Catalyst  Trusteeship Limited', 'N.A.', 'Axis Bank', 'Someone'],
                        'shares': [100513070, 10, 5, 1], 'broadcast_date': pd.to_datetime(['2026-10-16'] * 4)})
    s = ideas.pledge_events(t, REF, sh, enc=enc).iloc[0]['sentence']
    assert s.endswith('; lender as filed (Reg 31): Catalyst Trusteeship Limited; Reg 31 calls it a non-disposal undertaking')
    assert ideas.pledge_events(t, REF, sh).iloc[0]['sentence'] == ideas.pledge_events(t, REF, sh, enc=enc.iloc[3:]).iloc[0]['sentence']
    old = enc.assign(broadcast_date=pd.to_datetime(['2026-01-02'] * 4))         # outside the window: nothing added
    assert 'Reg 31' not in ideas.pledge_events(t, REF, sh, enc=old).iloc[0]['sentence']
