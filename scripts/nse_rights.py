"""NSE Rights Issue extraction using the first-party corporate-filings APIs."""
from __future__ import annotations
import json, os, re, time
from datetime import date, timedelta, datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

TARGET=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31')); LOOKBACK=int(os.getenv('LOOKBACK_DAYS','90')); URL='https://www.nseindia.com/companies-listing/corporate-filings-RI'; OUT=Path('artifacts/nse_validation/rights'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
APIS=['https://www.nseindia.com/api/corporate-further-issues-ri?index=FIRIIP','https://www.nseindia.com/api/corporate-further-issues-ri?index=FIRILS']

def browser():
    o=Options()
    for x in ['--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080','--lang=en-US',f'--user-agent={UA}']: o.add_argument(x)
    o.set_capability('goog:loggingPrefs', {'performance':'ALL','browser':'ALL'}); return webdriver.Chrome(options=o)
def clean(v): return re.sub(r'\s+',' ',v or '').strip()
def tables(d):
    out=[]
    for t in d.find_elements(By.TAG_NAME,'table'):
        rs=[]
        for tr in t.find_elements(By.TAG_NAME,'tr'):
            cells=[clean(c.text) for c in tr.find_elements(By.CSS_SELECTOR,'th,td')]
            if any(cells): rs.append(cells)
        if rs: out.append({'rows':rs,'row_count':max(0,len(rs)-1),'columns':rs[0]})
    return out
def js_fetch(d,url):
    script="""const url=arguments[0], done=arguments[arguments.length-1]; fetch(url,{credentials:'include',headers:{'Accept':'application/json,text/plain,*/*'}}).then(async r=>done(JSON.stringify({status:r.status,url:r.url,text:await r.text()}))).catch(e=>done(JSON.stringify({status:0,url:url,error:String(e)})));"""
    raw=json.loads(d.execute_async_script(script,url));
    text=raw.get('text','');
    try: raw['json']=json.loads(text)
    except Exception: raw['json']=None
    return raw
def flatten(obj):
    if isinstance(obj,list):
        if obj and all(isinstance(x,dict) for x in obj): return obj
        out=[]
        for x in obj: out.extend(flatten(x))
        return out
    if isinstance(obj,dict):
        out=[]
        for v in obj.values(): out.extend(flatten(v))
        return out
    return []
def date_values(r):
    vals=[]
    for k,v in r.items():
        if 'date' in str(k).lower() or 'dt' in str(k).lower() or 'timestamp' in str(k).lower():
            s=str(v or '')
            for f in ('%d-%b-%Y','%d-%m-%Y','%Y-%m-%d','%d/%m/%Y','%d-%b-%y'):
                try: vals.append(datetime.strptime(s[:11],f).date().isoformat()); break
                except: pass
    return vals
def main():
    d=browser(); report={'source':'NSE','dataset':'rights_issue','url':URL,'target_date':str(TARGET),'lookback_days':LOOKBACK,'api_endpoints':APIS,'windows':[]}
    try:
        for name,start in [('1d',TARGET),('7d',TARGET-timedelta(days=6)),('30d',TARGET-timedelta(days=29)),('90d',TARGET-timedelta(days=LOOKBACK-1))]:
            d.get(URL+f'?tabIndex=equity&from_date={start:%d-%m-%Y}&to_date={TARGET:%d-%m-%Y}'); time.sleep(6)
            api=[]; allrows=[]
            for u in APIS:
                x=js_fetch(d,u); rows=flatten(x.get('json')); api.append({'url':u,'status':x.get('status'),'bytes':len(x.get('text','')),'row_count':len(rows),'sample':rows[:3]}); allrows.extend(rows)
            ds=sorted({z for r in allrows for z in date_values(r)})
            report['windows'].append({'name':name,'start':str(start),'end':str(TARGET),'api':api,'api_rows':len(allrows),'api_distinct_dates':ds,'api_earliest_date':ds[0] if ds else None,'api_latest_date':ds[-1] if ds else None,'tables':tables(d),'body_prefix':clean(d.find_element(By.TAG_NAME,'body').text)[:2000]})
    finally: d.quit()
    (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)); print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=='__main__': main()
