"""Capture BSE first-party API requests, headers and response bodies from the live Angular pages.

This is intentionally diagnostic: it does not certify completeness and does not
mix NSE data. It is used to discover the real API contract before implementing
historical parameterization.
"""
from __future__ import annotations
import json, os, time
from datetime import date
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

OUT=Path('artifacts/bse_api_probe'); OUT.mkdir(parents=True,exist_ok=True)
TARGET=os.getenv('TARGET_DATE') or str(date.today())
PAGES={
 'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx',
 'block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx',
 'insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2',
 'rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri',
 'preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref',
}
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
o=Options()
for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080',f'--user-agent={UA}'): o.add_argument(x)
o.set_capability('goog:loggingPrefs',{'performance':'ALL','browser':'ALL'})
d=webdriver.Chrome(options=o)

def collect():
    requests={}; responses=[]
    for item in d.get_log('performance'):
        try:
            msg=json.loads(item['message'])['message']; method=msg.get('method'); p=msg.get('params',{})
            if method=='Network.requestWillBeSent':
                r=p.get('request',{}); u=r.get('url','')
                if 'api.bseindia.com' in u:
                    requests[p['requestId']]={'url':u,'method':r.get('method'),'headers':r.get('headers',{}),'postData':r.get('postData','')}
            elif method=='Network.responseReceived':
                r=p.get('response',{}); u=r.get('url','')
                if 'api.bseindia.com' in u:
                    responses.append({'requestId':p.get('requestId'),'url':u,'status':r.get('status'),'mimeType':r.get('mimeType'),'headers':r.get('headers',{})})
        except Exception: pass
    out=[]
    for resp in responses:
        x=dict(resp); req=requests.get(resp.get('requestId'),{}); x.update({'method':req.get('method'),'request_headers':req.get('headers',{}),'postData':req.get('postData','')})
        try:
            body=d.execute_cdp_cmd('Network.getResponseBody',{'requestId':resp['requestId']}).get('body','')
            x['body_bytes']=len(body); x['body_prefix']=body[:200000]
            try:
                obj=json.loads(body); x['json_type']=type(obj).__name__; x['json_keys']=list(obj)[:50]; x['json_sample']=obj if isinstance(obj,dict) else obj[:3]
            except Exception: pass
        except Exception as e: x['body_error']=str(e)
        out.append(x)
    return out

report={'source':'BSE','target_date':TARGET,'pages':{}}
try:
    for name,url in PAGES.items():
        d.get(url); time.sleep(6); report['pages'][name]={'url':d.current_url,'title':d.title,'api_requests':collect()}
finally: d.quit()
(OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)); print(json.dumps({k:len(v['api_requests']) for k,v in report['pages'].items()},indent=2))
