"""NSE Bulk Deals acquisition with direct historical API evidence.

The nse package's historical helper can return a single anchor date despite a
multi-day request in some environments. Certification therefore uses NSE's
first-party /api/historical/bulk-deals endpoint directly and records the exact
requested range plus the returned dates.
"""
from __future__ import annotations
import json, os, time
from datetime import date, timedelta
from pathlib import Path
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE='https://www.nseindia.com'; PAGE=f'{BASE}/market-data/large-deals'
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90')); OUT=Path('artifacts/nse_bulk'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def session():
    o=Options()
    for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080',f'--user-agent={UA}'):
        o.add_argument(x)
    d=webdriver.Chrome(options=o)
    try:
        d.get(PAGE); time.sleep(4); cookies={c['name']:c['value'] for c in d.get_cookies()}
    finally: d.quit()
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Accept-Language':'en-US,en;q=0.9','Referer':PAGE}); s.cookies.update(cookies); return s

def fetch(s,start,end):
    u=f'{BASE}/api/historical/bulk-deals'; p={'from':start.strftime('%d-%m-%Y'),'to':end.strftime('%d-%m-%Y')}
    r=s.get(u,params=p,timeout=40); result={'request_url':r.url,'status':r.status_code,'bytes':len(r.content),'start_date':str(start),'end_date':str(end)}
    try:
        obj=r.json(); rows=obj.get('data',[]) if isinstance(obj,dict) else (obj if isinstance(obj,list) else []); result.update({'mode':'json','count':len(rows),'columns':sorted(rows[0]) if rows else [],'distinct_dates':sorted({str(x.get('BD_DT_DATE') or x.get('mTIMESTAMP') or x.get('date')) for x in rows if x.get('BD_DT_DATE') or x.get('mTIMESTAMP') or x.get('date')}),'rows':rows})
    except Exception as e: result.update({'mode':'non_json','count':0,'parse_error':str(e),'prefix':r.text[:500],'rows':[]})
    return result

def main():
    s=session(); windows=[]; all_rows=[]
    specs=[('1d',TARGET),('7d',TARGET-timedelta(days=6)),('30d',TARGET-timedelta(days=29)),('90d',TARGET-timedelta(days=LOOKBACK-1))]
    for name,start in specs:
        x=fetch(s,start,TARGET); windows.append({k:v for k,v in x.items() if k!='rows'}); Path(OUT/f'{name}.json').write_text(json.dumps(x,indent=2,default=str)); all_rows.extend(x['rows'])
    report={'dataset':'bulk_deals','source':'NSE','target_date':str(TARGET),'lookback_days':LOOKBACK,'method':'NSE first-party historical API','windows':windows,'count':len(all_rows),'unique_observations':len({json.dumps(r,sort_keys=True,default=str) for r in all_rows}),'columns':sorted(all_rows[0]) if all_rows else [],'rows':all_rows}
    Path(OUT/'report.json').write_text(json.dumps(report,indent=2,default=str)); print(json.dumps({k:report[k] for k in report if k!='rows'},indent=2))
if __name__=='__main__': main()
