"""NSE Insider Trading acquisition using a browser-bootstrapped PIT session."""
from __future__ import annotations
import os, json, time, re
from datetime import date, timedelta
from pathlib import Path
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

BASE='https://www.nseindia.com'; PAGE=f'{BASE}/companies-listing/corporate-filings-insider-trading'; API=f'{BASE}/api/corporates-pit'
TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90')); OUT=Path('artifacts/nse_insider'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'

def browser_session():
    o=Options()
    for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080',f'--user-agent={UA}'):
        o.add_argument(x)
    d=webdriver.Chrome(options=o)
    try:
        d.get(PAGE); time.sleep(5); cookies={c['name']:c['value'] for c in d.get_cookies()}; title=d.title; url=d.current_url
    finally: d.quit()
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'en-US,en;q=0.9','Accept':'application/json,text/plain,*/*','Referer':PAGE}); s.cookies.update(cookies); return s,title,url,cookies

def clean_json_bytes(content):
    text=content.decode('utf-8','replace').strip()
    # Akamai/proxy layers have occasionally wrapped the JSON in non-printable
    # framing bytes; remove only bytes outside the JSON document boundaries.
    start=min([p for p in (text.find('{'),text.find('[')) if p>=0],default=-1)
    end=max(text.rfind('}'),text.rfind(']'))
    if start>=0 and end>=start: text=text[start:end+1]
    return json.loads(text)

def fetch(s,start,end):
    p={'index':'equities','from_date':start.strftime('%d-%m-%Y'),'to_date':end.strftime('%d-%m-%Y')}; h={'Referer':PAGE,'Accept':'application/json,text/plain,*/*'}
    r=s.get(API,params=p,headers=h,timeout=40); result={'start':str(start),'end':str(end),'status':r.status_code,'url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type','')}
    try:
        obj=clean_json_bytes(r.content); rows=obj.get('data',[]) if isinstance(obj,dict) else (obj if isinstance(obj,list) else []); result.update({'mode':'json','count':len(rows),'columns':sorted(rows[0].keys()) if rows and isinstance(rows[0],dict) else [],'rows':rows,'distinct_transaction_dates':sorted({str(x.get('date')) for x in rows if isinstance(x,dict) and x.get('date')})})
        if not rows:
            rcsv=s.get(API,params={**p,'csv':'true'},headers={**h,'Accept':'text/csv,*/*;q=0.9'},timeout=40); result.update({'csv_fallback_status':rcsv.status_code,'csv_fallback_bytes':len(rcsv.content),'csv_fallback_prefix':rcsv.text[:500]})
    except Exception as e: result.update({'mode':'non_json','count':0,'parse_error':str(e),'prefix':r.text[:500],'rows':[]})
    return result

def main():
    s,browser_title,browser_url,cookies=browser_session(); page=s.get(PAGE,headers={'Referer':BASE+'/'},timeout=30); windows=[]
    for name,start in [('1d',TARGET),('7d',TARGET-timedelta(days=6)),('30d',TARGET-timedelta(days=29)),('90d',TARGET-timedelta(days=LOOKBACK-1))]:
        x=fetch(s,start,TARGET); windows.append({k:v for k,v in x.items() if k!='rows'}); Path(OUT/f'{name}.json').write_text(json.dumps(x,indent=2,default=str),encoding='utf-8')
    report={'target_date':str(TARGET),'lookback_days':LOOKBACK,'browser_title':browser_title,'browser_url':browser_url,'page_status':page.status_code,'page_bytes':len(page.content),'cookie_names':sorted(cookies),'windows':windows}
    Path(OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
