"""Real rows for the design mocks: read from the repo's test fixtures (real NSE payloads) and nothing else.
Market data (market cap, price, 52-week range) is not in the fixtures; the mocks mark those cells as placeholders."""
import glob
import json
import sys
from datetime import date, datetime

from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[3])   # docs/design_v3/mock -> the repo
FX = ROOT + '/tests/fixtures'
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + '/streamlit_app')

from collectors.nse_events import parsers  # noqa: E402
from insiders_clean import issues  # noqa: E402


def d(s, fmt):
    return datetime.strptime(s, fmt).date()


def num(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


# ---- insider trades (SEBI PIT, NSE) ----
pit = json.load(open(FX + '/nse_pit_real.json'))
trades = []
for r in pit:
    mode = r['modeOfAcquisition']
    buy = r['transactionType'] == 'Acquisition'
    if mode not in ('Market Purchase', 'Market Sale'):
        continue
    if (mode == 'Market Purchase') != buy:      # the filing contradicts itself (mode vs transaction type): left out
        continue
    q = num(r['buyQuantity'] if buy else r['sellquantity'])
    v = num(r['buyValue'] if buy else r['sellValue'])
    b, a = num(r['beforeSharesNo']), num(r['afterSharesNo'])
    trades.append(dict(
        sym=r['symbol'], co=r['companyName'], who=' '.join(r['acqName'].split()), role=r['personCategory'],
        side='BUY' if buy else 'SELL', qty=q, value=v, price=v / q if q else None, before=b, after=a,
        hold_pct=((a - b) / b * 100) if b else None,
        traded=d(r['acqtoDt'], '%Y-%m-%d'), public=d(r['broadcastDt'][:11], '%d-%b-%Y')))
trades.sort(key=lambda t: (t['public'], t['traded']), reverse=True)
left_out = {}
for r in pit:
    left_out[r['modeOfAcquisition']] = left_out.get(r['modeOfAcquisition'], 0) + 1

# ---- SAST Reg 29 ----
sast = []
for r in json.load(open(FX + '/nse_events/sast_reg29.json')):
    sast.append(dict(sym=r['symbol'], co=r['company'], who=r['acquirerName'], promoter=r['promoterType'] == 'Y',
                     reg=r['regType'], side='BUY' if r['acqSaleType'] == 'Acquisition' else 'SELL', mode=r['acquisitionMode'],
                     shares=num(r['noOfShareAcq']) or num(r['noOfShareSale']),
                     pct=num(r.get('totAcqShare')) or num(r.get('totSaleShare')),
                     after=num(r.get('totAftShare')), day=r['timestamp'][:11]))

# ---- issues: In-Principle XBRL (ICDR minimum, allottees) ----
ip = {}
for f in glob.glob(FX + '/capital/pref_ip_*.xml'):
    x = issues.parse_xbrl(open(f, 'rb').read())
    m = x['main']
    secs = issues.groups_of(x, 'IssuedSecurity')
    allot = issues.groups_of(x, 'Allottees')
    ip[m['NSESymbol']] = dict(
        co=m['NameOfTheCompany'], cat=m['CategoryOfAllottee'], approved=num(m['AmountToBeRaised']),
        consideration=m['ConsiderationBy'] + (': ' + m['DescriptionOfOtherConsideration'] if m.get('DescriptionOfOtherConsideration') else ''),
        instruments='; '.join(dict.fromkeys(s['SecurityType'] for s in secs)),
        proposed=sum(num(s['NumberOfSecurities']) for s in secs),
        icdr=num(secs[0].get('MinimumIssuePricePerUnit')), board=m['DateOfBoardResolutionApprovingTheIssueOfSpecifiedSecurities'],
        allottees=[(a['NameOfAllottees'], a['AllottedSecurityType'], num(a['NumberOfSharesAllotted'])) for a in allot])

# listing records
ls = {}
for r in json.load(open(FX + '/capital/pref_listing.json')):
    ls.setdefault(r['nseSymbol'], []).append(dict(
        posted=d(r['systemDate'], '%d-%b-%Y'), raised=num(r['amountRaised']), price=num(r['offerPricePerSecurity']),
        shares=num(r['totalNumOfSharesAllotted']), approval=d(r['dateOfTradingApproval'], '%d-%b-%Y'),
        allot=d(r['dateOfAllotmentOfShares'], '%d-%b-%Y')))

# QIP listings
qips = []
for r in json.load(open(FX + '/capital/qip_listing.json')):
    qips.append(dict(sym=r['nsesymbol'], co=r['companyName'].title(), price=num(r['issPricePerUnit']),
                     amount=num(r['finalAmountOfIssueSize']), allottees=int(r['noOfAllottees']),
                     shares=num(r['noOfSharesAllotted']), listed=d(r['dateOfListing'], '%d-%b-%Y'),
                     disc=num(r['distPerShrsAvailed'])))

# shareholding by investor type (real XBRL)
holders = {}
for f in sorted(glob.glob(FX + '/nse_events/shp_categories/*.xml')):
    name, q = f.split('/')[-1][:-4].rsplit('_', 1)
    holders[name] = dict(q=q, **parsers.parse_shp_categories(open(f, encoding='utf-8', errors='ignore').read()))

# ---- bulk and block deals (real NSE files of March 2024 in the fixtures) and participant types ----
import csv  # noqa: E402
from insiders_clean import participants  # noqa: E402

deals = []
for kind, f in (('block', 'history/nse_block_2024.csv'), ('bulk', 'history/nse_bulk_2024.csv')):
    for r in list(csv.reader(open(FX + '/' + f, encoding='utf-8-sig')))[1:]:
        q, px = num(r[5]), num(r[6])
        t, conf, _ = participants.classify(r[3].strip())
        deals.append(dict(kind=kind, day=d(r[0], '%d-%b-%Y'), sym=r[1].strip(), co=r[2].strip(), client=r[3].strip(),
                          side=r[4].strip(), qty=q, px=px, value=q * px, type=t, conf=conf))

# QIP allottees of Inox Green Energy (listing XBRL): name, shares, % of issue, category
_x = issues.parse_xbrl(open(FX + '/capital/qip_ls_72568.xml', 'rb').read())
qip_allottees = [(g['NameOfAllottees'], num(g['NumberOfSharesAllotted']), num(g['PercentageOfTotalIssueSize']), g['CategoryOfAllotees'])
                 for k, g in _x['groups'].items() if k.startswith('Allottees')]


if __name__ == '__main__':
    buys = [t for t in trades if t['sym'] == 'HCLTECH' and t['side'] == 'BUY']
    sells = [t for t in trades if t['sym'] == 'HCLTECH' and t['side'] == 'SELL']
    print('HCL buys', len(buys), sum(t['value'] for t in buys) / 1e7, sum(t['qty'] for t in buys),
          sum(t['value'] for t in buys) / sum(t['qty'] for t in buys))
    print('HCL sells', len(sells), sum(t['value'] for t in sells) / 1e7, len({t['who'] for t in sells}))
    print(left_out)
    for k, v in holders.items():
        print(k, v['q'], {a: round(v.get(a + '_pct'), 2) if v.get(a + '_pct') is not None else None
                          for a in ('promoter', 'mf', 'insurance', 'banks_fi', 'fpi', 'retail')}, v.get('total_shares'))
    print({k: (v['icdr'], v['instruments'], v['cat']) for k, v in ip.items()})
    print(list(ls))
