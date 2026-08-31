from __future__ import annotations
import json, os, time
from datetime import date, datetime
from io import StringIO
from typing import Any
import pandas as pd, requests
TARGET_DATE=os.getenv('TARGET_DATE','2026-08-31'); D=date.fromisoformat(TARGET_DATE); DD=D.strftime('%d-%m-%Y'); YMD=D.strftime('%Y%m%d')
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0 Safari/537.36'
def result(source,dataset,method,**kw): return {'source':source,'dataset':dataset,'method':method,**kw}
def keys(x): return sorted(x[0].keys()) if isinstance(x,list) and x and isinstance(x[0],dict) else []
def get(s,url,**kw):
    t=time.perf_counter(); r=s.get(url,timeout=30,**kw); return r,round(time.perf_counter()-t,3)
def nse_direct():
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Referer':'https://www.nseindia.com/companies-listing/corporate-filings-insider-trading'})
    out=[]
    try: r,_=get(s,'https://www.nseindia.com/'); out.append(result('NSE','homepage','direct',status_code=r.status_code))
    except Exception as e: return [result('NSE','homepage','direct',status='error',error=str(e))]
    eps={'insider_trading':f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={DD}&to_date={DD}&csv=true','bulk_deals':f'https://www.nseindia.com/api/historical/bulk-deals?from={DD}&to={DD}','block_deals':f'https://www.nseindia.com/api/historical/block-deals?from={DD}&to={DD}'}
    for name,url in eps.items():
        try:
            r,elapsed=get(s,url); rec=result('NSE',name,'direct_api',status_code=r.status_code,elapsed_s=elapsed,bytes=len(r.content),content_type=r.headers.get('content-type',''))
            if r.ok: rec['body_prefix']=r.text[:250]; rec['payload_keys']=keys(r.json()) if 'json' in r.headers.get('content-type','').lower() else []
            out.append(rec)
        except Exception as e: out.append(result('NSE',name,'direct_api',status='error',error=str(e)))
    return out
def nse_package():
    out=[]
    try:
        from nse import NSE
        with NSE(download_folder='artifacts/nse',server=True,timeout=30) as nse:
            for kind in ('bulk_deals','block_deals'):
                try:
                    rows=nse.bulkdeals(kind,datetime.combine(D,datetime.min.time()),datetime.combine(D,datetime.min.time())); out.append(result('NSE',kind,'nse_package_server',status='success',count=len(rows),sample_keys=keys(rows)))
                except Exception as e: out.append(result('NSE',kind,'nse_package_server',status='error',error=str(e)))
    except Exception as e: out.append(result('NSE','library_import','nse_package_server',status='error',error=str(e)))
    return out
def bse_session():
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Referer':'https://www.bseindia.com/','Accept':'application/json, text/plain, */*','Accept-Language':'en-US,en;q=0.9'}); s.get('https://www.bseindia.com/',timeout=20); return s
def bse_api(term):
    s=bse_session(); url='https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w'; params={'pageno':'1','strCat':'-1','strPrevDate':YMD,'strScrip':'','strSearch':term,'strToDate':YMD,'strType':'C'}
    r,elapsed=get(s,url,params=params); rec=result('BSE','announcements_'+term.lower().replace(' ','_'),'official_api',status_code=r.status_code,elapsed_s=elapsed,bytes=len(r.content),url=r.url)
    if r.ok:
        try:
            p=r.json(); rows=p.get('Table',[]) if isinstance(p,dict) else []; rec.update(count=len(rows),sample_keys=keys(rows),sample=rows[:3])
        except Exception as e: rec['parse_error']=str(e)
    return rec
def bse_bulk_block_api():
    out=[]
    # Probe several known BSE API shapes; do not treat an empty response as success.
    candidates={'bulk_deals':['https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w'],'block_deals':['https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w']}
    for dataset,urls in candidates.items():
        for url in urls:
            try:
                s=bse_session(); params={'pageno':'1','strCat':'-1','strPrevDate':YMD,'strScrip':'','strSearch':dataset.replace('_',' '),'strToDate':YMD,'strType':'C'}; r,elapsed=get(s,url,params=params); rec=result('BSE',dataset,'official_api_probe',status_code=r.status_code,elapsed_s=elapsed,bytes=len(r.content),url=r.url)
                if r.ok:
                    try: p=r.json(); rows=p.get('Table',[]) if isinstance(p,dict) else []; rec.update(count=len(rows),sample_keys=keys(rows))
                    except Exception as e: rec['parse_error']=str(e)
                out.append(rec)
            except Exception as e: out.append(result('BSE',dataset,'official_api_probe',status='error',error=str(e)))
    return out
def bse_html():
    out=[]
    for dataset,url in {'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx'}.items():
        try:
            s=bse_session(); r,elapsed=get(s,url); tables=pd.read_html(StringIO(r.text)) if r.ok else []; out.append(result('BSE',dataset,'official_html',status_code=r.status_code,table_count=len(tables),row_counts=[len(x) for x in tables],elapsed_s=elapsed,body_prefix=r.text[:150]))
        except Exception as e: out.append(result('BSE',dataset,'official_html',status='error',error=str(e)))
    return out
def bse_browser():
    out=[]
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        o=Options(); [o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
        d=webdriver.Chrome(options=o)
        pages={'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','corporate_announcements':'https://www.bseindia.com/corporates/ann.html'}
        for dataset,url in pages.items():
            try:
                d.get(url); time.sleep(4); body=d.find_element('tag name','body').text; tables=d.execute_script("return Array.from(document.querySelectorAll('table')).map(t=>Array.from(t.querySelectorAll('tbody tr')).map(r=>Array.from(r.cells).map(c=>c.innerText.trim())).filter(x=>x.length)).filter(x=>x.length)"); out.append(result('BSE',dataset,'selenium_render',status='success',row_count=sum(map(len,tables)),table_count=len(tables),sample=tables[:2],title=d.title,current_url=d.current_url,contains_target_date=TARGET_DATE in body or D.strftime('%d/%m/%Y') in body))
            except Exception as e: out.append(result('BSE',dataset,'selenium_render',status='error',error=str(e)))
        d.quit()
    except Exception as e: out.append(result('BSE','browser_import','selenium_render',status='error',error=str(e)))
    return out
def main():
    os.makedirs('artifacts',exist_ok=True); os.makedirs('artifacts/nse',exist_ok=True); os.makedirs('artifacts/bse',exist_ok=True)
    results=nse_direct()+nse_package()+bse_html()+bse_bulk_block_api()+[bse_api(x) for x in ('Insider','Preferential','Rights Issue','Allotment')]+bse_browser()
    report={'target_date':TARGET_DATE,'phase':'BSE hardened acquisition probe','generated_at_utc':datetime.utcnow().isoformat(),'results':results}
    open('artifacts/acquisition_probe.json','w',encoding='utf-8').write(json.dumps(report,indent=2,default=str)); print(json.dumps(report,indent=2,default=str))
if __name__=='__main__': main()
