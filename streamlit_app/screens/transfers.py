"""Inter-se and off-market transfers: insider filings that change who holds
the shares without a market trade -- gifts, inter-se transfers between
promoter entities, off-market deals, ESOPs, preferential allotments, pledges.
They move individual holdings, often not the promoter group's total, and are
never counted as buying or selling anywhere on the site."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from ui import kit

from screens.ctx import load, need_data

GROUPS = {
    'Gifts and inter-se': ('gift', 'inter_se', 'inheritance', 'transmission'),
    'Off-market': ('off_market',),
    'ESOPs': ('esop',),
    'Preferential and schemes': ('preferential', 'scheme', 'conversion', 'bonus', 'rights'),
    'Pledges': ('pledge', 'pledge_created', 'pledge_released', 'pledge_invoked', 'revoke'),
}


def render():
    ctx = load()
    kit.head('Inter-se and off-market transfers', 'Holdings that changed hands without a market trade. Never counted '
                                                  'as buying or selling.')
    if not need_data(ctx):
        return
    t = ctx.trades[ctx.trades['is_primary'].astype('boolean').fillna(False)
                   & ~ctx.trades['is_market'].astype('boolean').fillna(False)].copy()
    t['seen'] = pd.to_datetime(t['broadcast_date'], errors='coerce')
    kind = t['kind'].astype(str)
    group = pd.Series('Other', index=t.index)
    for name, kinds in GROUPS.items():
        group[kind.isin(kinds) | kind.str.startswith(kinds)] = name
    t['group'] = group
    t['mode'] = t['mode_raw'].fillna(t['kind'])
    counts = t['group'].value_counts()
    kit.tiles([kit.Tile(name, kit.count(counts.get(name, 0)), kit.rupees(t.loc[t['group'] == name, 'value'].sum()))
               for name in list(GROUPS)[:4]])
    names = [n for n in list(GROUPS) + ['Other'] if counts.get(n, 0)]
    if not names:
        kit.empty('No off-market filings in the data.')
        return
    for tab, name in zip(st.tabs([f'{n} · {kit.indian(counts[n])}' for n in names]), names):
        with tab:
            rows = t[t['group'] == name].sort_values('seen', ascending=False)
            kit.table(rows, [
                kit.Col('company', 'Company', 'co'), kit.Col('person_name', 'Person', 'person'),
                kit.Col('side', 'Side', 'side'), kit.Col('mode', 'Mode as filed'),
                kit.Col('quantity', 'Shares', 'shares', phone=False), kit.Col('value', 'Value', 'money'),
                kit.Col('holding_change_pct', 'Own holding Δ', 'spct', phone=False),
                kit.Col('seen', 'Made public', 'date')], limit=200, download=f'transfers_{name[:12].lower().replace(" ", "_")}')
    kit.caption('A gift or inter-se transfer moves shares between members of the promoter group: one person\'s holding '
                'falls, another\'s rises, the group total usually does not change.')
