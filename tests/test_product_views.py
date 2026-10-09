import pandas as pd

from insiders_clean import product_views as pv


def _trades():
    rows = []
    def add(isin, date, value, role='promoter', person='p1', side='BUY'):
        rows.append(dict(isin=isin, broadcast_date=pd.Timestamp(date), value=value, person_role=role, person_id=person, side=side,
                         is_market=True, is_primary=True, trade_id=f'{isin}{date}{person}', company='Co ' + isin, pct_of_mcap=0.1))
    add('A', '2026-05-01', 30e5); add('A', '2026-05-20', 30e5)       # repeat within 30 days
    add('B', '2026-05-02', 10e5)                                      # under Rs 25 lakh
    add('C', '2026-05-03', 40e5, role='director', person='d')        # not a promoter
    add('S', '2026-05-04', 60e5, role='director', person='d', side='SELL')
    return pd.DataFrame(rows)


def test_promoter_accumulation_filters_and_flags_clusters():
    out = pv.promoter_accumulation(_trades(), '2026-06-01')
    assert list(out['isin']) == ['A'] and bool(out.loc[0, 'cluster']) and out.loc[0, 'value'] == 60e5


def test_heavy_selling_and_window():
    t = _trades()
    assert list(pv.heavy_selling(t, '2026-06-01')['isin']) == ['S']
    assert pv.heavy_selling(t, '2026-09-01').empty


def test_freshness_age():
    f = pv.freshness({'x': (pd.DataFrame({'d': ['2026-10-01', '2026-10-05']}), 'd')}, today='2026-10-09')
    assert f.loc[0, 'age_days'] == 4 and f.loc[0, 'rows'] == 2
