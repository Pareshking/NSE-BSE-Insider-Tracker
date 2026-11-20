"""Industry speed test (read-only, nothing stored): which way of getting the 4-level industry is fastest.

The full fetch asks BSE's quote header (ComHeadernew) once per scrip, 4-6 s apart: ~4,849 scrips, ~6-7 hours.
NSE's quote API refuses GitHub's runners (HTTP 403). This times the alternatives on a runner and prints what each
answers:
  A. BSE's scrip list filtered by industry (ListofScripData industry=...): one call per basic industry (~200)
     instead of one per scrip, if the filter works. Tried with each level's words for ABB.
  B. ComHeadernew paced at 1 s, then 4 at a time: answers, refusals, seconds per answer.
  C. NSE through the `nse` package's HTTP/2 session: quote-equity and NextApi getSymbolData for 3 symbols.
Stops a test at the first refusal (401/403/429); never retries around one.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collectors.bse.client import API, HEADERS  # noqa: E402

LIST = API + 'ListofScripData/w'
HEADER = API + 'ComHeadernew/w'
# ABB's words at each level (tests/fixtures/industry/bse_comheadernew_500002.json), and two more basic industries
FILTERS = ['Heavy Electrical Equipment', 'Electrical Equipment', 'Capital Goods', 'Industrials',
           'Commodity Chemicals', 'Precious Metals']
# BSE codes for the pace test: well-known large and small companies (real codes)
CODES = ['500002', '500010', '500034', '500087', '500112', '500180', '500209', '500247', '500295', '500325',
         '500390', '500400', '500410', '500440', '500470', '500483', '500510', '500520', '500547', '500570',
         '500575', '500660', '500696', '500790', '500820', '500825', '500870', '500878', '501425', '502355',
         '503100', '503806', '504067', '505200', '506395', '507685', '508869', '509480', '511218', '512599',
         '513375', '517334', '517354', '519552', '520056', '522275', '524715', '526612', '530005', '531344',
         '532174', '532187', '532215', '532281', '532454', '532500', '532538', '532540', '532555', '532648',
         '532755', '532868', '532898', '532921', '532977', '533096', '533278', '534816', '535755', '539448',
         '540005', '540115', '540133', '540376', '540611', '540719', '541143', '541450', '542066', '543320']


def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def header(s, code):
    t = time.monotonic()
    try:
        r = s.get(HEADER, params={'quotetype': 'EQ', 'scripcode': code, 'seriesid': ''}, timeout=30)
        ok = r.status_code == 200 and b'ISubGroup' in r.content
        return r.status_code, ok, time.monotonic() - t
    except requests.RequestException as exc:
        return type(exc).__name__, False, time.monotonic() - t


def test_list_filter(rep):
    s = session()
    out = rep['A_list_filter'] = {}
    base = {'Group': '', 'Scripcode': '', 'segment': 'Equity', 'status': 'Active'}
    t = time.monotonic()
    r = s.get(LIST, params=dict(base, industry=''), timeout=60)
    allrows = r.json() if r.status_code == 200 else []
    out['unfiltered'] = {'http': r.status_code, 'rows': len(allrows), 'seconds': round(time.monotonic() - t, 1)}
    for f in FILTERS:
        time.sleep(2)
        t = time.monotonic()
        try:
            r = s.get(LIST, params=dict(base, industry=f), timeout=60)
            rows = r.json() if r.status_code == 200 else []
        except Exception as exc:  # noqa: BLE001
            out[f] = f'{type(exc).__name__}: {exc}'
            continue
        rows = rows if isinstance(rows, list) else []
        out[f] = {'http': r.status_code, 'rows': len(rows), 'seconds': round(time.monotonic() - t, 1),
                  'has_ABB': any(str(x.get('SCRIP_CD')) == '500002' for x in rows if isinstance(x, dict)),
                  'INDUSTRY_values': sorted({str(x.get('INDUSTRY')) for x in rows if isinstance(x, dict)})[:5],
                  'sample': [x.get('Scrip_Name') for x in rows[:5] if isinstance(x, dict)]}
        print(f'A {f!r}: {out[f]}', flush=True)


def test_pace(rep):
    s = session()
    res = []
    t0 = time.monotonic()
    for code in CODES[:40]:
        st, ok, sec = header(s, code)
        res.append((code, st, ok))
        if st in (401, 403, 429):
            break
        time.sleep(1.0)
    took = time.monotonic() - t0
    rep['B1_pace_1s'] = {'asked': len(res), 'ok': sum(r[2] for r in res), 'refused': [r for r in res if r[1] in (401, 403, 429)],
                         'other': [r for r in res if not r[2] and r[1] not in (401, 403, 429)],
                         'seconds_per_answer': round(took / max(1, len(res)), 2)}
    print('B1', rep['B1_pace_1s'], flush=True)
    if rep['B1_pace_1s']['refused']:
        return
    time.sleep(10)
    sessions = [session() for _ in range(4)]
    t0 = time.monotonic()
    with ThreadPoolExecutor(4) as pool:
        res = list(pool.map(lambda ic: header(sessions[ic[0] % 4], ic[1]), enumerate(CODES[40:80])))
    took = time.monotonic() - t0
    rep['B2_four_at_a_time'] = {'asked': len(res), 'ok': sum(r[1] for r in res),
                                'statuses': sorted({str(r[0]) for r in res}),
                                'seconds_per_answer': round(took / max(1, len(res)), 2)}
    print('B2', rep['B2_four_at_a_time'], flush=True)


def test_nse(rep):
    out = rep['C_nse_package'] = {}
    try:
        from nse import NSE
        n = NSE(tempfile.mkdtemp(), server=True)
    except Exception as exc:  # noqa: BLE001
        out['error'] = f'{type(exc).__name__}: {exc}'
        return
    for sym in ('ABB', 'INFY', 'RELIANCE'):
        for name, url, params in (
                ('quote_equity', 'https://www.nseindia.com/api/quote-equity', {'symbol': sym}),
                ('next_symbol_data', 'https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi',
                 {'functionName': 'getSymbolData', 'marketType': 'N', 'series': 'EQ', 'symbol': sym})):
            time.sleep(2)
            try:
                r = n._session.get(url, params=params, timeout=30)
                out[f'{sym} {name}'] = {'http': r.status_code, 'bytes': len(r.content),
                                        'has_basicIndustry': b'basicIndustry' in r.content}
                if r.status_code == 200:
                    print(f'C {sym} {name}: {r.text[:1500]}', flush=True)
            except Exception as exc:  # noqa: BLE001
                out[f'{sym} {name}'] = f'{type(exc).__name__}: {exc}'
    try:
        r = n._session.get('https://www.nseindia.com/api/equity-stockIndices', params={'index': 'NIFTY TOTAL MARKET'},
                           timeout=60)
        j = r.json() if r.status_code == 200 else {}
        d = (j.get('data') or [{}, {}])
        out['equity_stockIndices'] = {'http': r.status_code, 'rows': len(d),
                                      'row_keys': sorted(d[1].keys()) if len(d) > 1 else [],
                                      'meta_keys': sorted((d[1].get('meta') or {}).keys()) if len(d) > 1 else []}
    except Exception as exc:  # noqa: BLE001
        out['equity_stockIndices'] = f'{type(exc).__name__}: {exc}'


def main():
    rep = {}
    for test in (test_list_filter, test_pace, test_nse):
        try:
            test(rep)
        except Exception as exc:  # noqa: BLE001
            rep[test.__name__] = f'{type(exc).__name__}: {exc}'
    print(json.dumps(rep, indent=1, default=str))


if __name__ == '__main__':
    main()
