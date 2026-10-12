"""Deal participant types and investor groups (insiders_clean/participants.py), on real NSE client names."""
import pandas as pd

from insiders_clean.participants import add_participant_columns, classify, group_of, load_aliases, report


def test_types_from_real_names():
    cases = {
        'SBI MUTUAL FUND': 'mutual_fund', 'TATA AIA LIFE INSURANCE COMPANY LIMITED': 'insurer',
        'NATIONAL PENSION SYSTEM (NPS) TRUST': 'pension', 'GOVERNMENT OF SINGAPORE': 'fpi',
        'NORGES BANK ON ACCOUNT OF THE GOVERNMENT PENSION FUND GLOBAL': 'fpi',
        'GOLDMAN SACHS INVESTMENTS MAURITIUS I LIMITED': 'fpi', 'KOTAK MAHINDRA BANK LIMITED': 'bank',
        'MORGAN STANLEY ASIA SINGAPORE PTE': 'fpi', 'GHISALLO MASTER FUND LP': 'fpi',
        'PI OPPORTUNITIES AIF V LLP': 'pms_aif', 'CARNELIAN AIF CATEGORY I TRUST-SCHEME 1': 'pms_aif',
        'PINE OAK GLOBAL FUND': 'fund_other', 'QE SECURITIES LLP': 'broker',
        'J B BODA INSURANCE & REINSURANCE BROKERS PRIVATE LIMITED': 'broker',
        'YSK FAMILY TRUST': 'trust', 'CHAUBARA EATS PRIVATE LIMITED': 'corporate',
        'THAKKAR NILESHKUMAR FARSHURAM HUF': 'individual', 'VISHAL MAHESH WAGHELA': 'individual',
        'SUMITRA': 'unknown',
    }
    for name, kind in cases.items():
        assert classify(name)[0] == kind, name
    assert classify('VISHAL MAHESH WAGHELA')[1] == 'low' and classify('SBI MUTUAL FUND')[1] == 'high'


def test_groups_and_market_maker_override():
    al = load_aliases()
    assert group_of('HDFC STANDARD LIFE INSURANCE COMPANY LTD', al) == ('HDFC Life Insurance Company Limited', 'alias')
    assert group_of('PINE OAK GLOBAL FUND - CLASS B', al)[0] == group_of('PINE OAK GLOBAL FUND', al)[0]
    assert group_of('NUVAMA CROSSOVER OPPORTUNITIES FUND - SERIES IIIA', al)[1] == 'series'
    d = pd.DataFrame({'client_id': ['a', 'b', 'c'], 'client_name': ['PINE OAK GLOBAL FUND', 'PINE OAK GLOBAL FUND - CLASS B', 'HRTI PRIVATE LIMITED'],
                      'client_is_market_maker': [False, False, True]})
    out = add_participant_columns(d)
    assert out['investor_group_id'].iloc[0] == out['investor_group_id'].iloc[1]
    assert tuple(out.iloc[2][['client_type', 'client_type_confidence']]) == ('prop_hft', 'high')
    assert report(out)['groups_with_several_ids'] == 1
