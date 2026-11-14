"""The top search's options (owner, 14 Nov 2026: "search is not predictive or free search"): every company by name, NSE
symbol, BSE code and ISIN, and the people and funds who matter (promoters, directors and KMP who traded on the market in
the last 12 months; bulk/block clients with Rs 1 Cr or more of deals in that time, market makers out). Streamlit's box
filters the labels as one types, so whatever is in a label can be typed. Built once per data day."""
from __future__ import annotations

import pandas as pd
import streamlit as st

PEOPLE_DAYS = 365
DEAL_MIN = 1e7          # Rs 1 Cr of deals in the window to be listed
ROLES = ('promoter', 'promoter_group', 'director', 'kmp')


def search_options(ctx) -> tuple[list[str], dict]:
    return _options(ctx, str(ctx.ref))


@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def _options(_ctx, ref_key: str) -> tuple[list[str], dict]:
    ctx = _ctx
    labels, targets = [], {}
    sec = ctx.securities
    if sec is not None and not sec.empty:
        s = sec.dropna(subset=['nse_symbol']).drop_duplicates('nse_symbol')
        name = s['display_name'] if 'display_name' in s else s.get('company', s['nse_symbol'])
        for n, sym, code, isin in zip(name, s['nse_symbol'], s.get('bse_code', pd.Series(index=s.index, dtype=object)),
                                      s.get('isin', pd.Series(index=s.index, dtype=object))):
            parts = [str(n), str(sym)]
            if isinstance(code, str) and code.strip() or (code is not None and pd.notna(code) and str(code).strip()):
                parts.append(f'BSE {str(code).split(".")[0]}')
            if isinstance(isin, str) and isin:
                parts.append(isin)
            lab = ' · '.join(parts)
            labels.append(lab)
            targets[lab] = ('company', str(sym))
    ref = pd.Timestamp(ctx.ref) if ctx.ref is not None else None
    people = []
    t = ctx.trades
    if ref is not None and t is not None and not t.empty and {'person_id', 'person_name', 'person_role'} <= set(t.columns):
        seen = pd.to_datetime(t['broadcast_date'], errors='coerce')
        p = t[t['person_role'].isin(ROLES) & t['is_market'].astype('boolean').fillna(False)
              & (seen > ref - pd.Timedelta(days=PEOPLE_DAYS))].dropna(subset=['person_id', 'person_name'])
        people.append(p.drop_duplicates('person_id')[['person_id', 'person_name']].rename(columns={'person_id': 'id', 'person_name': 'name'}))
    d = ctx.deals
    if ref is not None and d is not None and not d.empty and {'client_id', 'client_name', 'value'} <= set(d.columns):
        w = d[(pd.to_datetime(d['date'], errors='coerce') > ref - pd.Timedelta(days=PEOPLE_DAYS))
              & ~d.get('client_is_market_maker', pd.Series(False, index=d.index)).astype('boolean').fillna(False)]
        big = w.groupby('client_id')['value'].sum()
        w = w[w['client_id'].isin(big[big >= DEAL_MIN].index)].dropna(subset=['client_id', 'client_name'])
        people.append(w.drop_duplicates('client_id')[['client_id', 'client_name']].rename(columns={'client_id': 'id', 'client_name': 'name'}))
    if people:
        pp = pd.concat(people, ignore_index=True).drop_duplicates('id')
        dup = pp['name'].duplicated(keep=False)
        for i, n, two in zip(pp['id'], pp['name'], dup):
            lab = f'Person or fund · {n}' + (f' · {i}' if two else '')
            if lab not in targets:
                labels.append(lab)
                targets[lab] = ('entity', str(i))
    co = sorted(x for x in labels if targets[x][0] == 'company')
    pe = sorted(x for x in labels if targets[x][0] == 'entity')
    return co + pe, targets
