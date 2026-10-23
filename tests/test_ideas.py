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
                            '(filed as voting rights other than by shares), now holds 5.79%')
    assert out['THYROCARE'].startswith('HSBC Mutual Fund bought 1.88%')


def test_a_stake_filed_as_others_says_it_once_and_an_ipo_in_capitals():
    """Today, 23 Oct: 'ITC Infotech India Ltd took 11.11% of the company (filed as others, not shares) (others)'."""
    sast = pd.DataFrame({'isin': ['INE0HAPP0011', 'INE0FXMT0011'], 'symbol': ['HAPPSTMNDS', 'FXMT'], 'company': ['H', 'F'],
                         'is_promoter': [False, False], 'acquirer_name': ['ITC Infotech India Ltd', 'Rajasthan Global Securities'],
                         'pct_acquired': [11.11, 5.01], 'pct_sold': [None, None], 'post_stake_pct': [11.11, 5.01],
                         'instrument': ['Others', 'Equity shares'], 'mode': ['Others', 'ipo'],
                         'broadcast_date': pd.to_datetime(['2026-10-10'] * 2)})
    out = dict(zip(ideas.stake_events(sast, REF)['nse_symbol'], ideas.stake_events(sast, REF)['sentence']))
    assert out['HAPPSTMNDS'] == 'ITC Infotech India Ltd took 11.11% of the company (filed as other than shares), now holds 11.11%'
    assert out['FXMT'] == 'Rajasthan Global Securities took 5.01% of the company (IPO), now holds 5.01%'


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


def test_an_issue_to_promoters_and_others_counts_only_the_promoter_groups_part():
    """Spectrum Electrical, 23 Oct: 8.04% to "promoters and others" said nothing of the promoters' part. The
    allottees matched to the promoter-group list size it; none matched, no warning."""
    from insiders_clean import promoter_group
    sh = pd.DataFrame({'isin': ['INE0MIXD0011', 'INE0NONE0011'], 'symbol': ['MIXCO', 'NONECO'], 'company': ['M', 'N'],
                       'quarter_end': pd.to_datetime(['2026-09-30'] * 2), 'total_shares': [1e8, 1e8]})
    issues = pd.DataFrame({'isin': ['INE0MIXD0011', 'INE0NONE0011'], 'symbol': ['MIXCO', 'NONECO'], 'company': ['M', 'N'],
                           'app_id': ['L1', 'L2'], 'linked_app_id': ['A1', 'A2'],
                           'allottee_category': ['MIXED', 'MIXED'], 'vs_market': [-30.0, -30.0],
                           'shares_allotted': [8e6, 8e6], 'securities_proposed': [None, None], 'instruments': ['Warrants'] * 2,
                           'posted_on': pd.to_datetime(['2026-10-05'] * 2), 'status': ['Allotted or listed'] * 2, 'amount': [1e8] * 2})
    allottees = pd.DataFrame({'app_id': ['A1', 'A1', 'A2'], 'isin': ['INE0MIXD0011', 'INE0MIXD0011', 'INE0NONE0011'],
                              'allottee': ['Ravi Kumar Gupta', 'Some Fund LLP', 'Other Fund LLP'],
                              'allottee_id': ['RAVI KUMAR GUPTA', 'SOME FUND LLP', 'OTHER FUND LLP'], 'securities': [2e6, 6e6, 8e6]})
    group = pd.DataFrame({'isin': ['INE0MIXD0011'], 'quarter_end': ['2026-09-30'], 'member_id': ['RAVI KUMAR GUPTA'],
                          'member_alt_id': [None]})
    marked, rep = promoter_group.mark_allottee_promoters(allottees, group, None)
    assert marked['in_promoter_group'].tolist() == [True, False, False] and rep['in_promoter_group'] == 1
    out = ideas.issue_events(issues, REF, sh, allottees=marked)
    assert out['nse_symbol'].tolist() == ['MIXCO']                                    # NONECO: no promoter among the named
    r = out.iloc[0]
    assert abs(r['pct_of_company'] - 2.0) < 1e-9                                       # a quarter of the 8% issue
    assert '(1 of 2 named allottees in the promoter group)' in r['sentence']
    assert len(ideas.issue_events(issues, REF, sh)) == 2                               # no allottee table: as before


# ---- the money board of 23 Oct: the Rs 25 Cr path, the lift, raises (docs/DESIGN_V3.md; agreed with the consultant) ----

BIG = 'INE777A01011'


def _big_buy(person='Vama Sundari', role='promoter_group', n=7, qty=60_000, price=1_700.0, isin=BIG):
    """Seven filings over seven days: Rs 71 Cr in a company worth Rs 4 lakh Cr (0.02%: under both share floors)."""
    return [{**row(isin, 'BIGCAP', person, role, 'BUY', qty, price, d), 'market_cap': 4e12, 'pct_of_mcap': qty * price / 4e12 * 100}
            for d in pd.bdate_range('2026-10-05', periods=n)]


def test_rs_25_crore_by_one_decision_maker_qualifies_whatever_the_share_of_the_company():
    t = pd.DataFrame(_big_buy(n=7))                           # 7 buying days: under STEADY_DAYS, value 71 Cr
    out = ideas.worth_a_look(t, REF)
    assert list(out['nse_symbol']) == ['BIGCAP'] and out.iloc[0]['pct_of_company'] < ideas.MIN_PCT
    assert out.iloc[0]['value'] >= ideas.BIG_VALUE
    small = pd.DataFrame(_big_buy(n=7, qty=10_000))           # Rs 11.9 Cr: still under, and a tiny share
    assert ideas.worth_a_look(small, REF).empty


def test_the_rupee_path_is_per_decision_maker_not_per_company():
    two = pd.DataFrame(_big_buy('Ravi', 'director', n=2, qty=50_000) + _big_buy('Dee', 'director', n=2, qty=50_000))   # 17 Cr each
    assert ideas.worth_a_look(two, REF).empty                 # 34 Cr in all, but no one decision-maker reaches 25 Cr


def test_a_director_selling_counts_only_at_rs_25_crore_and_the_promoter_group_by_the_old_floors_too():
    director_big = pd.DataFrame([{**row(BIG, 'BIGCAP', 'Dee Director', 'director', 'SELL', 160_000, 1_700.0, '2026-10-12'),
                                  'market_cap': 4e12, 'pct_of_mcap': 0.007}])
    director_small = pd.DataFrame([row('INE778A01011', 'DIRSMALL', 'Dee Director', 'director', 'SELL', 3_000_000, 50, '2026-10-12')])
    promoter_small = pd.DataFrame([row('INE779A01011', 'PROMSMALL', 'Promo Seller', 'promoter', 'SELL', 3_000_000, 50, '2026-10-12')])
    out = ideas.watch_out(pd.concat([director_big, director_small, promoter_small]), REF)
    assert dict(zip(out['nse_symbol'], out['kind'])) == {'BIGCAP': 'Director or KMP selling', 'PROMSMALL': 'Promoter selling'}


def test_designated_persons_and_employees_never_count():
    t = pd.DataFrame(_big_buy('Raghavan Kidambi', 'designated_person', n=2, qty=160_000))     # Rs 54 Cr each, but not a decision-maker
    assert ideas.worth_a_look(t, REF).empty and ideas.watch_out(t.assign(side='SELL'), REF).empty


def test_the_token_rule_cannot_fire_on_a_rupee_big_buy():
    t = pd.DataFrame(_big_buy(n=3, qty=60_000))
    assert not ideas.decisions(t.assign(is_token=False), REF, 'BUY')['value'].lt(ideas.BIG_VALUE).any()
    from insiders_clean import signals
    assert signals.TOKEN_MAX_VALUE < ideas.BIG_VALUE


def _two_groups_of_events(n_big=7, n_small=6):
    rows = []
    for i in range(n_big):    # rupee-big, tiny share
        rows.append({'isin': f'INE9{i:02d}A01011', 'company': f'Big {i}', 'nse_symbol': f'BIG{i}', 'list': 'look', 'kind': 'Promoter buying',
                     'pct_of_company': 0.01 + i / 1000, 'sentence': f'big {i}', 'value': (30 + i) * 1e7, 'last': REF - pd.Timedelta(days=i)})
    for i in range(n_small):  # small in rupees, big share
        rows.append({'isin': f'INE8{i:02d}A01011', 'company': f'Small {i}', 'nse_symbol': f'SM{i}', 'list': 'look', 'kind': 'Promoter buying',
                     'pct_of_company': 5.0 - i / 10, 'sentence': f'small {i}', 'value': 4e7, 'last': REF - pd.Timedelta(days=i)})
    return ideas._ev(rows)


def test_rupee_big_rows_go_first_in_their_group_by_value_but_leave_places_for_share_ranked_rows():
    look, _ = ideas.today([_two_groups_of_events()])
    names = look['company'].tolist()
    lifted = names[:ideas.MAX_LIFT]
    assert lifted == ['Big 6', 'Big 5', 'Big 4', 'Big 3', 'Big 2']                      # largest rupees first, at most MAX_LIFT
    assert names[ideas.MAX_LIFT:ideas.PER_GROUP] == ['Small 0', 'Small 1', 'Small 2']   # three places stay for the share ranking
    assert look['big'].tolist()[:ideas.MAX_LIFT] == [True] * ideas.MAX_LIFT
    assert ideas.PER_GROUP - ideas.MAX_LIFT >= 3
    rest = names[ideas.PER_GROUP:]
    assert set(rest) == {'Big 1', 'Big 0', 'Small 3', 'Small 4', 'Small 5'}             # the other big rows rank by share like any


def test_a_preferential_issue_at_exactly_the_market_price_is_promoters_paying_up_and_nothing_else():
    sh = pd.DataFrame({'isin': ['INE0EQ000011'], 'symbol': ['EQCO'], 'company': ['E'], 'quarter_end': pd.to_datetime(['2026-09-30']),
                       'total_shares': [1e8]})
    base = {'isin': 'INE0EQ000011', 'symbol': 'EQCO', 'company': 'E', 'app_id': 'L1', 'allottee_category': 'PROMOTER',
            'shares_allotted': 1e6, 'instruments': 'Equity shares', 'posted_on': pd.Timestamp('2026-10-05'),
            'status': 'Allotted or listed', 'amount': 1e8}
    for vs, kind in ((0.0, 'Promoters pay up'), (0.01, 'Promoters pay up'), (-0.01, 'Cheap shares to promoters')):
        out = ideas.issue_events(pd.DataFrame([{**base, 'vs_market': vs}]), REF, sh)
        assert out['kind'].tolist() == [kind], (vs, out)                              # exactly one place, the same price reference
        assert out['list'].tolist() == [('look' if kind == 'Promoters pay up' else 'warn')]
        assert ideas.raise_events(pd.DataFrame([{**base, 'vs_market': vs}]), None, None, REF, sh).empty   # promoter issues are not 'Raises'


def _qip(**kw):
    r = {'isin': 'INE0QIP00011', 'symbol': 'QIPCO', 'company': 'Qip Co', 'app_id': 'Q1', 'status': 'Allotted or listed',
         'allotment_date': pd.Timestamp('2026-10-05'), 'posted_on': pd.Timestamp('2026-10-06'), 'issue_price': 165.65,
         'shares_allotted': 18_110_473, 'allottees': 20, 'amount': 3e9, 'vs_market': -8.0}
    return {**r, **kw}


def _total(n):
    return pd.DataFrame({'isin': ['INE0QIP00011'], 'symbol': ['QIPCO'], 'company': ['Q'], 'quarter_end': pd.to_datetime(['2026-09-30']),
                         'total_shares': [n]})


def test_raises_are_shown_at_100_crore_or_2_percent_and_say_what_is_not_stated():
    big = ideas.raise_events(None, pd.DataFrame([_qip()]), None, REF, _total(4e8))
    r = big.iloc[0]
    assert r['kind'] == 'QIP' and r['list'] == 'look' and abs(r['pct_of_company'] - 18_110_473 / 4e8 * 100) < 1e-9
    assert '20 institutions took 18,110,473 shares at ₹165.65; ₹300 Cr raised, 4.53% of the company, 8% below the price now' in r['sentence']
    assert r['kv3_label'] == 'Issue vs now' and r['kv3'] == '-8.0%'
    no_price = ideas.raise_events(None, pd.DataFrame([_qip(vs_market=None)]), None, REF, _total(4e8)).iloc[0]
    assert no_price['kv3_label'] == 'Issue vs now' and no_price['kv3'] == '—'          # not the promoters' holding in its place
    # under Rs 100 Cr but over 2% of the shares: shown by dilution
    small_amount = ideas.raise_events(None, pd.DataFrame([_qip(amount=4e8, shares_allotted=3e6)]), None, REF, _total(1e8))
    assert len(small_amount) == 1 and '3.00% of the company' in small_amount.iloc[0]['sentence']
    # under both: left out
    assert ideas.raise_events(None, pd.DataFrame([_qip(amount=4e8, shares_allotted=1e6)]), None, REF, _total(1e8)).empty


def test_dilution_uses_the_shareholding_total_only_and_only_when_it_passes_the_check():
    # the filing's own count is half the company or more: not a dilution; the amount (Rs 300 Cr) still qualifies, dilution not stated
    r = ideas.raise_events(None, pd.DataFrame([_qip(shares_allotted=6e7)]), None, REF, _total(1e8)).iloc[0]
    assert r['pct_of_company'] == 0 and 'dilution not stated' in r['sentence'] and '₹300 Cr raised' in r['sentence']
    # no shareholding total at all: same
    assert 'dilution not stated' in ideas.raise_events(None, pd.DataFrame([_qip()]), None, REF, None).iloc[0]['sentence']
    # a blanked (unreliable) amount with a usable dilution qualifies by dilution and says the amount is not usable
    blank = ideas.raise_events(None, pd.DataFrame([_qip(amount=None, shares_allotted=3e6)]), None, REF, _total(1e8)).iloc[0]
    assert 'amount not usable' in blank['sentence'] and '3.00% of the company' in blank['sentence']
    # neither usable: left out
    assert ideas.raise_events(None, pd.DataFrame([_qip(amount=None, shares_allotted=6e7)]), None, REF, _total(1e8)).empty


def test_an_approval_is_not_a_raise_and_the_event_date_is_the_allotment():
    approved = _qip(status='Approved in principle')
    assert ideas.raise_events(None, pd.DataFrame([approved]), None, REF, _total(4e8)).empty
    old = _qip(allotment_date=pd.Timestamp('2026-06-01'), posted_on=pd.Timestamp('2026-10-06'))
    assert ideas.raise_events(None, pd.DataFrame([old]), None, REF, _total(4e8), days=30).empty      # allotted outside the window
    assert len(ideas.raise_events(None, pd.DataFrame([old]), None, REF, _total(4e8), days=180)) == 1
    only_posted = _qip(allotment_date=pd.NaT)
    assert ideas.raise_events(None, pd.DataFrame([only_posted]), None, REF, _total(4e8)).iloc[0]['last'] == pd.Timestamp('2026-10-06')


def test_preferential_to_others_and_rights_are_raises_funds_named_only_when_the_filing_names_them():
    pref = pd.DataFrame([{'isin': 'INE0QIP00011', 'symbol': 'QIPCO', 'company': 'Qip Co', 'app_id': 'P1', 'status': 'Allotted or listed',
                          'allottee_category': 'NON_PROMOTER', 'posted_on': pd.Timestamp('2026-10-05'), 'offer_price': 2002.0,
                          'shares_allotted': 2.5e6, 'amount': 5e9, 'vs_market': 2.4},
                         {'isin': 'INE0QIP00011', 'symbol': 'QIPCO', 'company': 'Qip Co', 'app_id': 'P2', 'status': 'Allotted or listed',
                          'allottee_category': 'PROMOTER', 'posted_on': pd.Timestamp('2026-10-05'), 'offer_price': 10.0,
                          'shares_allotted': 2.5e6, 'amount': 5e9, 'vs_market': 2.4}])
    rights = pd.DataFrame([{'isin': 'INE0QIP00011', 'symbol': 'QIPCO', 'company': 'Qip Co', 'app_id': 'R1', 'status': 'Allotted or listed',
                            'posted_on': pd.Timestamp('2026-10-04'), 'offer_price': 40.0, 'shares_allotted': 1e7, 'amount': 4e8, 'vs_market': -12.0}])   # 2.5% of the shares
    out = ideas.raise_events(pref, None, rights, REF, _total(4e8), named={'P1': True})
    kinds = dict(zip(out['kind'], out['sentence']))
    assert set(kinds) == {'Preferential to others', 'Rights issue'}                    # the promoter issue is not here
    assert 'funds named among the allottees' in kinds['Preferential to others'] and 'funds named' not in kinds['Rights issue']
    assert out.set_index('kind').loc['Rights issue', 'kv3_label'] == 'Rights vs now'


def test_raises_are_a_neutral_group_under_money_in_and_a_company_sits_in_one_group():
    assert ('Raises', ['QIP', 'Preferential to others', 'Rights issue']) in ideas.GROUPS['look']
    ev = [ideas.raise_events(None, pd.DataFrame([_qip()]), None, REF, _total(4e8)),
          ideas._ev([{'isin': 'INE0QIP00011', 'company': 'Qip Co', 'nse_symbol': 'QIPCO', 'list': 'look', 'kind': 'Promoter buying',
                      'pct_of_company': 0.5, 'sentence': 'bought', 'value': 1e7, 'last': REF}])]
    look, _ = ideas.today(ev)
    assert len(look) == 1 and look.iloc[0]['group'] == 'Insiders buying'               # one row per company: the first group it belongs to
    assert set(look.iloc[0]['kinds']) == {'QIP', 'Promoter buying'}
