"""NSE Insider Trading acquisition: official NSE PIT endpoint with page-session bootstrap."""
from __future__ import annotations
import os, json, time
from datetime import date, timedelta
from pathlib import Path
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE='https://www.nseindia.com'; PAGE=f'{BASE}/companies-listing/corporate-filings-insider-trading'; API=f'{BASE}/api/corporates-pit'
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90')); OUT=Path('artifacts/nse_insider'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def browser_cookies():
    o=Options()
    for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080',f'--user-agent={UA}'):
        o.add_argument(x)
    d=webdriver.Chrome(options=o)
    try:
        d.get(PAGE); time.sleep(5)
        return {c['name']:c['value'] for c in d.get_cookies()}, d.title, d.current_url
    finally: d.quit()

def fetch(s,start,end):
    p={'index':'equities','from_date':start.strftime('%d-%m-%Y'),'to_date':end.strftime('%d-%m-%Y')}
    headers={'Referer':PAGE,'Accept':'application/json,text/plain,*/*'}
    r=s.get(API,params=p,headers=headers,timeout=40)
    result={'start':str(start),'end':str(end),'status':r.status_code,'url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type','')}
    try:
        obj=r.json(); rows=obj.get('data',[]) if isinstance(obj,dict) else []
        result['mode']='json'; result['count']=len(rows); result['columns']=sorted(rows[0].keys()) if rows else []; result['rows']=rows
        result['distinct_transaction_dates']=sorted({str(row.get('date')) for row in rows if row.get('date')})
        if not rows:
            rcsv=s.get(API,params={**p,'csv':'true'},headers={**headers,'Accept':'text/csv,*/*;q=0.9'},timeout=40)
            result['csv_fallback_status']=rcsv.status_code; result['csv_fallback_bytes']=len(rcsv.content); result['csv_fallback_prefix']=rcsv.text[:500]
    except Exception as e:
        result['mode']='non_json'; result['count']=0; result['parse_error']=str(e); result['prefix']=r.text[:500]; result['rows']=[]
    return result

def main():
    cookies,browser_title,browser_url=browser_cookies(); s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'en-US,en;q=0.9','Accept-Encoding':'gzip, deflate, br','Connection':'keep-alive'}); s.cookies.update(cookies)
    page=s.get(PAGE,headers={'Referer':BASE+'/'},timeout=30)
    report={'target_date':str(TARGET),'lookback_days':LOOKBACK,'browser_title':browser_title,'browser_url':browser_url,'page_status':page.status_code,'page_bytes':len(page.content),'cookie_names':sorted(cookies),'windows':[]}
    for name,start in [('1d',TARGET),('7d',TARGET-timedelta(days=6)),('30d',TARGET-timedelta(days=29)),('90d',TARGET-timedelta(days=LOOKBACK-1))]:
        x=fetch(s,start,TARGET); report['windows'].append({'name':name,**{k:v for k,v in x.items() if k!='rows'}}); Path(OUT/f'{name}.json').write_text(json.dumps(x,indent=2,default=str),encoding='utf-8')
    Path(OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
