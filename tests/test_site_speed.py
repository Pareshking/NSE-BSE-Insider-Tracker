"""The site's faster paths (22 Oct 2026: Today's first load, the Company and Filings pages) give the same
output as the code they replaced, bit for bit, on random tables shaped like the real ones: blanks, ties,
repeated labels, deals inside and outside a filing's trade dates. The replaced code is kept here as the
reference."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from insiders_clean import ideas, signals

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'streamlit_app'))

REF = pd.Timestamp('2026-10-19')
ISINS = [f'INE{i:03d}A01010' for i in range(40)]


# ---- the code as it was before 22 Oct ---------------------------------------------------------------

def old_deals_also_filed(deals, trades):
    out = pd.Series(False, index=deals.index)
    if deals is None or deals.empty or trades is None or trades.empty:
        return out
    t = trades.dropna(subset=['isin', 'person_id']).copy()
    t['_to'] = pd.to_datetime(t['trade_date_to'], errors='coerce')
    t['_from'] = pd.to_datetime(t['trade_date_from'], errors='coerce').fillna(t['_to'])
    t = t.dropna(subset=['_to'])
    key = t.groupby(['isin', 'person_id', 'side'])
    spans = {k: list(zip(g['_from'], g['_to'])) for k, g in key}
    dd = pd.to_datetime(deals['date'], errors='coerce')
    for i, isin, cid, side, day in zip(deals.index, deals['isin'], deals['client_id'], deals['side'], dd):
        for a, b in spans.get((isin, cid, side), ()):
            if pd.notna(day) and a.normalize() <= day.normalize() <= b.normalize():
                out.at[i] = True
                break
    return out


def old_fund_events(deals, trades, ref, days=ideas.WINDOW, sh=None):
    if deals is None or deals.empty or 'client_type' not in deals:
        return ideas._ev([])
    d = deals[deals['is_primary'].astype('boolean').fillna(False) & ~deals['client_is_market_maker'].astype('boolean').fillna(False)
              & deals['client_type'].isin(signals.FUND_TYPES)].copy()
    d['date'] = pd.to_datetime(d['date'], errors='coerce')
    d = d[(d['date'] <= ref) & (d['date'] > ref - pd.Timedelta(days=days))].dropna(subset=['isin'])
    if trades is not None and not trades.empty and len(d):
        d = d[~old_deals_also_filed(d, trades)]
    if d.empty:
        return ideas._ev([])
    sign = d['side'].map({'BUY': 1, 'SELL': -1})
    total = d['isin'].map(ideas._shares_out(sh))
    by_shares = (pd.to_numeric(d['quantity'], errors='coerce') / total * 100 if 'quantity' in d
                 else pd.Series(float('nan'), index=d.index))
    d = d.assign(net_pct=by_shares.where(total.gt(0), pd.to_numeric(d['pct_of_mcap'], errors='coerce')) * sign,
                 net_val=pd.to_numeric(d['value'], errors='coerce') * sign)
    rows = []
    for isin, g in d.groupby('isin'):
        net = g['net_pct'].sum()
        if abs(net) < ideas.FUND_NET_PCT:
            continue
        side = 'BUY' if net > 0 else 'SELL'
        names = g.loc[g['side'] == side, 'client_name'].drop_duplicates().tolist()
        lead = (names[0] + (f' and {len(names) - 1} more' if len(names) > 1 else '')) if names else 'Funds'
        verb = 'bought' if net > 0 else 'sold'
        rows.append({'isin': isin, 'company': g['company'].iloc[-1], 'nse_symbol': g['nse_symbol'].iloc[-1],
                     'list': 'look' if net > 0 else 'warn', 'kind': 'Fund buying' if net > 0 else 'Funds selling',
                     'pct_of_company': abs(net),
                     'sentence': f'{lead} {verb} a net {abs(net):.2f}% of the company in bulk/block deals',
                     'value': abs(g['net_val'].sum()), 'last': g['date'].max()})
    return ideas._ev(rows)


def old_today(events, summary=None):
    parts = [e for e in events if e is not None and not e.empty]
    if not parts:
        return ideas._ev([]), ideas._ev([])
    ev = pd.concat(parts, ignore_index=True)
    reads = ideas._verdicts(summary)
    out = []
    for lst in ('look', 'warn'):
        x = ev[ev['list'] == lst].dropna(subset=['isin'])
        rows = []
        for isin, g in x.groupby('isin'):
            kinds = list(dict.fromkeys(g['kind']))
            order, name, members = ideas._group(lst, kinds)
            g = g.assign(_in=g['kind'].isin(members)).sort_values(['_in', 'pct_of_company', 'last'], ascending=False)
            lead = g.iloc[0].drop(labels='_in').to_dict()
            lead.update(kinds=kinds, group=name, group_order=order, reads={k: reads.get(k) or 'not_measured' for k in kinds},
                        others=[t for t in g['sentence'].drop_duplicates() if t != lead['sentence']])
            rows.append(lead)
        r = pd.DataFrame(rows)
        out.append(r.sort_values(['group_order', 'pct_of_company', 'last'], ascending=[True, False, False]).reset_index(drop=True)
                   if not r.empty else r)
    return out[0], out[1]


def old_eligible(trades):
    t = trades.copy()
    for c in ('is_market', 'is_primary', 'needs_review'):
        t[c] = t[c].astype('boolean').fillna(False)
    t = t[t['is_market'] & t['is_primary'] & ~t['needs_review']].copy()
    t['date'] = pd.to_datetime(t['trade_date_to'], errors='coerce')
    t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
    for c in ('value', 'pct_of_mcap', 'market_cap', 'signed_value'):
        t[c] = pd.to_numeric(t[c], errors='coerce')
    t['is_token'] = (t['person_role'].isin(signals.PROMOTER_ROLES) & (t['side'] == 'BUY')
                     & (t['value'] < signals.TOKEN_MAX_VALUE) & (t['market_cap'] > signals.TOKEN_MIN_MCAP))
    return t


# ---- random tables shaped like the clean ones --------------------------------------------------------

def trades(rng, n=1500):
    seen = REF - pd.to_timedelta(rng.integers(0, 120, n), unit='D')
    to = seen - pd.to_timedelta(rng.integers(0, 4, n), unit='D')
    frm = np.array(to - pd.to_timedelta(rng.integers(0, 6, n), unit='D'), dtype=object)
    frm[rng.random(n) < 0.1] = None                     # no 'from' date: the 'to' date stands for both
    to = np.array(to, dtype=object)
    to[rng.random(n) < 0.03] = None                     # no trade date at all
    isin = rng.choice(ISINS, n).astype(object)
    isin[rng.random(n) < 0.02] = None
    person = np.array([f'p{i}' for i in rng.integers(0, 120, n)], dtype=object)
    person[rng.random(n) < 0.02] = None
    side = rng.choice(['BUY', 'SELL', None], n, p=[0.55, 0.43, 0.02])
    value = pd.array(rng.uniform(1e5, 5e7, n), dtype='Float64')
    value[rng.random(n) < 0.03] = pd.NA
    return pd.DataFrame({
        'isin': isin, 'person_id': person, 'person_name': [f'Person {p}' for p in person], 'side': side,
        'person_role': rng.choice(['promoter', 'promoter_group', 'director', 'kmp', 'designated_person'], n),
        'trade_date_from': [pd.Timestamp(x).date() if x is not None else None for x in frm],
        'trade_date_to': [pd.Timestamp(x).date() if x is not None else None for x in to],
        'broadcast_date': [x.date() for x in seen], 'value': value, 'signed_value': value,
        'pct_of_mcap': pd.array(rng.uniform(0, 0.4, n), dtype='Float64'), 'market_cap': rng.uniform(1e9, 1e12, n),
        'quantity': pd.array(rng.uniform(100, 1e5, n), dtype='Float64'),
        'is_market': rng.random(n) < 0.8, 'is_primary': pd.array(rng.choice([True, False, None], n, p=[0.85, 0.1, 0.05]), dtype='boolean'),
        'needs_review': rng.random(n) < 0.05, 'company': [f'Co {i}' for i in isin], 'nse_symbol': [f'S{i}' for i in isin]})


def deals(rng, t, n=1200):
    d = pd.DataFrame({
        'isin': rng.choice(ISINS, n).astype(object), 'client_id': [f'f{i}' for i in rng.integers(0, 30, n)],
        'client_name': [f'Fund {i}' for i in rng.integers(0, 25, n)], 'side': rng.choice(['BUY', 'SELL'], n),
        'date': [x.date() for x in REF - pd.to_timedelta(rng.integers(0, 120, n), unit='D')],
        'client_type': rng.choice(['mutual_fund', 'fpi', 'insurer', 'individual', 'corporate'], n),
        'is_primary': rng.random(n) < 0.9, 'client_is_market_maker': rng.random(n) < 0.05,
        'pct_of_mcap': pd.array(rng.uniform(0, 0.6, n), dtype='Float64'),
        'value': pd.array(rng.uniform(1e6, 1e9, n), dtype='Float64'),
        'quantity': pd.array(rng.uniform(1e3, 1e6, n), dtype='Float64'),
        'company': [None if rng.random() < 0.05 else f'Deal co {i}' for i in range(n)],
        'nse_symbol': [f'D{i}' for i in range(n)]})
    # A third are an insider's own filed trade: same person, company and side, a day around the trade dates
    k = rng.choice(n, n // 3, replace=False)
    src = t.dropna(subset=['isin', 'person_id', 'side']).sample(len(k), replace=True, random_state=1)
    day = pd.to_datetime(src['trade_date_to'], errors='coerce').fillna(REF) + pd.to_timedelta(rng.integers(-7, 3, len(k)), unit='D')
    d.loc[k, 'isin'] = src['isin'].to_numpy()
    d.loc[k, 'client_id'] = src['person_id'].to_numpy()
    d.loc[k, 'side'] = src['side'].to_numpy()
    d.loc[k, 'date'] = [x.date() for x in day]
    d.loc[rng.choice(n, 20, replace=False), 'date'] = None
    d.loc[rng.choice(n, 10, replace=False), 'client_id'] = None
    return d


@pytest.mark.parametrize('seed', range(6))
def test_deals_also_filed_marks_the_same_deals(seed):
    rng = np.random.default_rng(seed)
    t = trades(rng)
    d = deals(rng, t)
    got = signals.deals_also_filed(d, t)
    assert got.any() and not got.all()
    pd.testing.assert_series_equal(got, old_deals_also_filed(d, t))
    # A repeated row label is marked on every row that carries it, as the loop did
    rep = d.set_axis(np.repeat(np.arange(len(d) // 2 + 1), 2)[:len(d)])
    pd.testing.assert_series_equal(signals.deals_also_filed(rep, t), old_deals_also_filed(rep, t))
    assert not signals.deals_also_filed(d.iloc[:0], t).any() and not signals.deals_also_filed(d, t.iloc[:0]).any()


def shareholding(rng):
    """Total shares for half the companies (the others fall back to value over market cap)."""
    return pd.DataFrame({'isin': ISINS[::2], 'quarter_end': pd.Timestamp('2026-09-30'),
                         'total_shares': rng.uniform(5e6, 5e8, len(ISINS[::2]))})


@pytest.mark.parametrize('seed', range(6))
@pytest.mark.parametrize('days', list(ideas.PERIODS.values()))
@pytest.mark.parametrize('with_sh', [False, True])
def test_fund_events_are_the_same_to_the_last_bit(seed, days, with_sh):
    rng = np.random.default_rng(seed)
    t = trades(rng)
    d = deals(rng, t)
    sh = shareholding(rng) if with_sh else None
    got, want = ideas.fund_events(d, t, REF, days=days, sh=sh), old_fund_events(d, t, REF, days=days, sh=sh)
    pd.testing.assert_frame_equal(got, want, check_exact=True)
    if days >= 30:
        assert len(want)


def test_fund_events_on_plain_float_columns_too():
    rng = np.random.default_rng(11)
    t = trades(rng)
    d = deals(rng, t)
    d['pct_of_mcap'], d['value'] = d['pct_of_mcap'].astype(float), d['value'].astype(float)
    pd.testing.assert_frame_equal(ideas.fund_events(d, t, REF), old_fund_events(d, t, REF), check_exact=True)


def events(rng, n=900):
    kinds = [k for lst in ('look', 'warn') for _, ks in ideas.GROUPS[lst] for k in ks] + ['Something else']
    pct = rng.choice([0.1, 0.25, 0.5, 1.0, np.nan], n)        # ties and blanks on purpose
    last = pd.Series(REF - pd.to_timedelta(rng.integers(0, 5, n), unit='D'))
    last[rng.random(n) < 0.1] = pd.NaT
    isin = rng.choice(ISINS[:15], n).astype(object)
    isin[rng.random(n) < 0.03] = None
    ev = pd.DataFrame({'isin': isin, 'company': [f'Co {i}' for i in range(n)], 'nse_symbol': [f'S{i}' for i in range(n)],
                       'list': rng.choice(['look', 'warn'], n), 'kind': rng.choice(kinds, n), 'pct_of_company': pct,
                       'sentence': [f'Sentence {i % 300}' for i in range(n)],
                       'value': [None if rng.random() < 0.3 else float(v) for v in rng.uniform(1e5, 1e8, n)],
                       'last': last, 'avg_price': np.nan, 'trade_to': np.nan, 'decision_makers': np.nan})
    return [ev.iloc[:300], ideas._ev([]), ev.iloc[300:700].drop(columns=['avg_price']), ev.iloc[700:]]


@pytest.mark.parametrize('seed', range(8))
def test_today_lists_are_the_same(seed):
    ev = events(np.random.default_rng(seed))
    for got, want in zip(ideas.today(ev), old_today(ev)):
        pd.testing.assert_frame_equal(got, want, check_exact=True)
    assert all(a.empty and b.empty for a, b in zip(ideas.today([]), old_today([])))


def test_today_lists_from_the_real_builders_are_the_same():
    rng = np.random.default_rng(3)
    t = trades(rng)
    t['trade_date_from'] = t['trade_date_from'].fillna(t['trade_date_to'])   # the sentence needs a first trade day
    e = signals.eligible(t)
    for days in ideas.PERIODS.values():
        ev = [ideas.insider_events(e, REF, None, days=days, marks=ideas.marked(e, REF)),
              ideas.fund_events(deals(rng, t), t, REF, days=days)]
        assert any(len(x) for x in ev)
        for got, want in zip(ideas.today(ev), old_today(ev)):
            pd.testing.assert_frame_equal(got, want, check_exact=True)
        pd.testing.assert_frame_equal(ideas.insider_events(e, REF, None, days=days), ev[0])


@pytest.mark.parametrize('seed', range(3))
def test_eligible_is_the_same(seed):
    t = trades(np.random.default_rng(seed))
    pd.testing.assert_frame_equal(signals.eligible(t), old_eligible(t), check_exact=True)
    rep = t.set_axis(np.repeat(np.arange(len(t) // 2 + 1), 2)[:len(t)])
    pd.testing.assert_frame_equal(signals.eligible(rep), old_eligible(rep), check_exact=True)


# ---- store.py: promoter group cut to each company's latest quarter, R2 objects fetched side by side ---

def page_members(pg: pd.DataFrame, sym: str):
    """screens/company.py's reading of the promoter-group table for one symbol."""
    pg = pg[pg['symbol'].astype(str).str.upper() == sym]
    if pg.empty:
        return None
    last = pg['quarter_end'].max()
    return last, pg[pg['quarter_end'] == last].sort_values('shares', ascending=False)


def test_promoter_group_cut_shows_each_company_the_same_members():
    from data import store
    rng = np.random.default_rng(5)
    n = 3000
    q = np.array(['2025-12-31', '2026-03-31', '2026-06-30', '2026-09-30', None], dtype=object)
    pg = pd.DataFrame({'isin': rng.choice(ISINS, n), 'symbol': rng.choice(['ABC', 'abc', 'XYZ', 'NIL', None, 'QQ'], n),
                       'quarter_end': pd.to_datetime(rng.choice(q, n, p=[0.2, 0.2, 0.2, 0.3, 0.1])),   # as the clean step writes it
                       'member_name': [f'M{i}' for i in range(n)], 'shares': rng.choice([10.0, 20.0, 30.0], n)})
    pg.loc[pg['symbol'] == 'NIL', 'quarter_end'] = pd.NaT          # a company whose quarters are all blank
    cut = store._latest_only(pg, 'symbol', 'quarter_end')
    assert len(cut) < len(pg)
    for sym in ('ABC', 'XYZ', 'NIL', 'NONE', 'QQ', 'MISSING'):
        a, b = page_members(pg, sym), page_members(cut, sym)
        if a is None:
            assert b is None
            continue
        assert (a[0] == b[0]) or (pd.isna(a[0]) and pd.isna(b[0]))
        pd.testing.assert_frame_equal(a[1], b[1])
    # Dates as text with blanks do not order: the table is kept whole rather than guessed at
    text = pg.assign(quarter_end=rng.choice(q, n))
    assert store._latest_only(text, 'symbol', 'quarter_end') is text


@pytest.fixture()
def fake_r2(monkeypatch):
    from data import store
    from lib import r2_data
    calls, lock = [], threading.Lock()

    def get(client, key):
        with lock:
            calls.append(key)
        time.sleep(0.05)
        if key.endswith('broken.parquet'):
            raise r2_data.R2ReadError('down')
        return None if key.endswith('missing.parquet') else f'body of {key}'.encode()

    monkeypatch.delenv('INSIDERS_LOCAL_DATA', raising=False)
    monkeypatch.setattr(store, '_local', lambda: None)
    monkeypatch.setattr(r2_data, 'r2_configured', lambda: True)
    monkeypatch.setattr(r2_data, 'get_client', lambda: object())
    monkeypatch.setattr(r2_data, '_get_bytes', get)
    monkeypatch.setattr(store, '_FETCHED', {})
    return store, calls


def test_prefetch_reads_side_by_side_and_each_object_is_used_once(fake_r2):
    store, calls = fake_r2
    keys = [f'clean/current/t{i}.parquet' for i in range(20)] + ['clean/current/securities.parquet',
                                                                 'clean/current/missing.parquet', 'clean/current/broken.parquet']
    t0 = time.monotonic()
    assert store.prefetch(keys) == 21
    assert time.monotonic() - t0 < 0.05 * len(keys) / 2   # ten at a time, not one after another
    calls.clear()
    assert store._read('clean/current/t3.parquet') == b'body of clean/current/t3.parquet' and not calls
    assert store._read('clean/current/t3.parquet') == b'body of clean/current/t3.parquet' and calls == ['clean/current/t3.parquet']
    calls.clear()
    for _ in range(2):   # securities is read twice (the cut table and the model basket's whole list)
        store._read('clean/current/securities.parquet')
    assert not calls
    store._read('clean/current/securities.parquet')
    assert calls == ['clean/current/securities.parquet']
    calls.clear()
    assert store._read('clean/current/missing.parquet') is None and calls == ['clean/current/missing.parquet']
    with pytest.raises(Exception, match='down'):   # a failed prefetch is fetched again and fails as before
        store._read('clean/current/broken.parquet')


def test_prefetched_bytes_go_stale(fake_r2, monkeypatch):
    store, calls = fake_r2
    store.prefetch(['clean/current/a.parquet'])
    monkeypatch.setattr(store, 'FETCHED_TTL', -1)
    calls.clear()
    store._read('clean/current/a.parquet')
    assert calls == ['clean/current/a.parquet']


def test_no_prefetch_on_a_local_folder(tmp_path, monkeypatch):
    from data import store
    monkeypatch.setenv('INSIDERS_LOCAL_DATA', str(tmp_path))
    assert store.prefetch() == 0
