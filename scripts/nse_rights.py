"""NSE Rights Issue extraction/validation with network/API diagnostics."""
from __future__ import annotations
import json, os, re, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90')); URL='https://www.nseindia.com/companies-listing/corporate-filings-RI'; OUT=Path('artifacts/nse_validation/rights')
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
def browser():
    o=Options()
    for x in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080','--lang=en-US',f'--user-agent={UA}']: o.add_argument(x)
    o.set_capability('goog:loggingPrefs', {'performance':'ALL','browser':'ALL'})
    return webdriver.Chrome(options=o)
def clean(v): return re.sub(r'\s+',' ',v or '').strip()
def extract_tables(d):
    out=[]
    for t in d.find_elements(By.TAG_NAME,'table'):
        rows=[]
        for tr in t.find_elements(By.TAG_NAME,'tr'):
            cells=[clean(c.text) for c in tr.find_elements(By.CSS_SELECTOR,'th,td')]
            if any(cells): rows.append(cells)
        if rows: out.append({'rows':rows,'row_count':max(0,len(rows)-1),'columns':rows[0],'sample':rows[1:4]})
    return out
def network(d):
    out=[]; seen=set()
    for item in d.get_log('performance'):
        try:
            msg=json.loads(item['message'])['message']
            if msg.get('method')=='Network.requestWillBeSent':
                r=msg['params']['request']; u=r.get('url','')
                if 'nseindia.com' in u and ('/api/' in u or 'corporate-filings' in u.lower()):
                    k=(r.get('method'),u,r.get('postData',''))
                    if k not in seen: seen.add(k); out.append({'method':r.get('method'),'url':u,'postData':r.get('postData','')})
        except Exception: pass
    return out
def main():
    OUT.mkdir(parents=True,exist_ok=True); d=browser(); report={'source':'NSE','dataset':'rights_issue','url':URL,'target_date':str(TARGET),'lookback_days':LOOKBACK,'windows':[]}
    try:
        for name,start in [('1d',TARGET),('7d',TARGET-timedelta(days=6)),('30d',TARGET-timedelta(days=29)),('90d',TARGET-timedelta(days=LOOKBACK-1))]:
            d.get(URL+f'?tabIndex=equity&from_date={start:%d-%m-%Y}&to_date={TARGET:%d-%m-%Y}'); time.sleep(8)
            tables=extract_tables(d)
            report['windows'].append({'name':name,'start':str(start),'end':str(TARGET),'final_url':d.current_url,'title':d.title,'table_count':len(tables),'meaningful_table_count':sum(t['row_count']>0 for t in tables),'tables':tables,'network_requests':network(d),'body_prefix':clean(d.find_element(By.TAG_NAME,'body').text)[:2000]})
    finally: d.quit()
    (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)); print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
