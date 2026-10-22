"""The Company page's helpers: ownership by quarter (insiders_clean/ownership.py) and for / against
(insiders_clean/ideas.company_view)."""
import pandas as pd

from insiders_clean import ideas, ownership


def quarter(q, check='match', **pct):
    row = {'quarter_end': q, 'categories_check': check}
    for t in ('promoter', 'mf', 'insurance', 'fpi', 'banks_fi', 'aif', 'other_dii', 'retail', 'hni', 'corporate',
              'other_foreign', 'govt', 'other_public', 'non_public_other'):
        row[f'{t}_pct'] = pct.get(t, 0.0)
    return row


def test_ownership_uses_only_quarters_that_add_up_and_never_fills_the_rest():
    """SBIN Sep 2026 as filed: promoter 55.4538, MF 13.6769, insurance 9.8701, FPI 11.0659, retail 5.6435, HNI 0.1826."""
    rows = pd.DataFrame([
        quarter('2026-03-31', promoter=57.0, mf=12.0, fpi=11.5),
        quarter('2026-06-30', check=None, promoter=56.0),                                   # not parsed
        quarter('2026-09-30', promoter=55.4538, mf=13.6769, insurance=9.8701, fpi=11.0659, retail=5.6435, hni=0.1826,
                banks_fi=0.0024, govt=0.0016)])
    table, missing = ownership.by_quarter(rows)
    sep, mar = pd.Timestamp('2026-09-30'), pd.Timestamp('2026-03-31')
    assert missing == [pd.Timestamp('2026-06-30')] and table[pd.Timestamp('2026-06-30')].isna().all()
    assert table.loc['Mutual funds', sep] == 13.6769 and table.loc['Other DII and AIF', sep] == 0.0024
    assert table.loc['Other', sep] == 0.0016
    # the change is between the last two parsed quarters (Mar to Sep), not across the unparsed one
    assert abs(table.loc['Promoter', 'change'] - (55.4538 - 57.0)) < 1e-9
    assert table.loc['Promoter', mar] == 57.0


def test_ownership_with_one_parsed_quarter_has_no_change():
    table, missing = ownership.by_quarter(pd.DataFrame([quarter('2026-09-30', promoter=60.0)]))
    assert missing == [] and table['change'].isna().all()


def test_timeline_dates_with_and_without_a_zone_sort_together():
    """Real data, 21 Oct: results carry an IST time with its zone, other filings a plain date; the
    timeline's sort broke on the mix (company-hcltech screenshot)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens.company import _day
    days = pd.Series([_day('2026-10-14 18:05:00+05:30'), _day('2026-10-15'), _day(pd.Timestamp('2026-10-13'))])
    assert days.sort_values().tolist() == [pd.Timestamp('2026-10-13'), pd.Timestamp('2026-10-14 18:05'), pd.Timestamp('2026-10-15')]


def test_a_sale_is_a_negative_share_of_market_cap_in_the_timeline():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'streamlit_app'))
    from screens.company import _signed
    assert _signed({'side': 'SELL', 'pct_of_mcap': 0.0004}) == -0.0004
    assert _signed({'side': 'BUY', 'pct_of_mcap': 0.02}) == 0.02 and _signed({'side': 'BUY', 'pct_of_mcap': None}) is None


def test_company_view_keeps_every_event_with_its_kinds_and_reads():
    ev = pd.DataFrame([
        {'isin': 'X', 'list': 'look', 'kind': 'Promoter buying', 'pct_of_company': 0.4, 'sentence': 'Promoter group bought 0.40%', 'last': pd.Timestamp('2026-10-01')},
        {'isin': 'X', 'list': 'look', 'kind': 'Spotlight', 'pct_of_company': 0.4, 'sentence': 'Promoter group bought 0.40%', 'last': pd.Timestamp('2026-10-01')},
        {'isin': 'X', 'list': 'look', 'kind': 'Big investor in', 'pct_of_company': 2.1, 'sentence': 'A Fund bought 2.10%', 'last': pd.Timestamp('2026-10-05')},
        {'isin': 'X', 'list': 'warn', 'kind': 'Pledge created', 'pct_of_company': 1.0, 'sentence': 'Promoters pledged a net 1.00%', 'last': pd.Timestamp('2026-10-07')}])
    behind = pd.DataFrame({'signal': ['promoter_buy'] * 2, 'horizon': ['3M', '6M'], 'cases': [80, 70],
                           'median_excess': [-1.0, -2.0], 'beat_index': [45.0, 44.0]})
    pros, cons = ideas.company_view([ev], behind)
    assert list(pros['sentence']) == ['A Fund bought 2.10%', 'Promoter group bought 0.40%']     # largest share first
    assert pros.iloc[1]['kinds'] == ['Promoter buying', 'Spotlight']
    assert pros.iloc[1]['reads']['Promoter buying'] == 'drag'                                  # a tag, the row stays
    assert pros.iloc[0]['reads'] == {'Big investor in': 'not_measured'}
    assert list(cons['kind']) == ['Pledge created']
