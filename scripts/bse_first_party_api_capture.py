"""Capture and validate first-party BSE API contracts from live pages."""
from __future__ import annotations
import json,os,re,time
from datetime import date,timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
END=date.fromisoformat(os.getenv('TARGET_DATE') or str(date.today()));LOOKBACK=int(os.getenv('LOOKBACK_DAYS') or '90');START=END-timedelta(days=max(0,LOOKBACK-1));OUT=Path('artifacts/bse_api_contract');OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36';PAGES={'bulk':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','insider':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','rights':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'};KNOWN={'BulkDeal_Beta':'bulk','BlockDeal_Beta':'block','getCorp_Regulation_ng':'insider','Pubissues_FurtherIssuesummary_RI_isd_ng':'rights','Pubissues_FurtherIssuesummary_Pref_isd_ng':'preferential','Pubissues_FurtherXbrlview_pref_ng':'preferential'}
o=Options()
for a in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}'):o.add_argument(a)
o.set_capability('goog:loggingPrefs',{'performance':'ALL','browser':'ALL'});d=webdriver.Chrome(options=o)
def controls():return d.execute_script("return Array.from(document.querySelectorAll('input,select,button')).map(x=>({id:x.id||'',name:x.name||'',value:x.value||'',type:x.type||'',text:(x.innerText||'').trim(),cls:x.className||''})).filter(x=>x.id||x.name||x.value||x.text)")
def set_dates():
 nodes=d.find_elements('css selector',"input[name='datepicker'],input[id*='datepicker' i],input[class*='datepicker' i]")
 if len(nodes)<2:nodes=[x for x in d.find_elements('css selector','input') if re.search(r'date|from|to',((x.get_attribute('id') or '')+' '+(x.get_attribute('name') or '')+' '+(x.get_attribute('class') or '')),re.I)]
 if len(nodes)<2:return {'status':'no_date_controls','count':len(nodes)}
 for n,v in zip(nodes[:2],(START.strftime('%d/%m/%Y'),END.strftime('%d/%m/%Y'))):
  try:n.click();n.send_keys(Keys.CONTROL,'a');n.send_keys(v);n.send_keys(Keys.TAB)
  except Exception:pass
 clicked=d.execute_script("const xs=Array.from(document.querySelectorAll('button,input[type=submit],input[type=button],a'));const n=xs.find(x=>/search|submit|show/i.test((x.innerText||x.value||'').trim())&&!/reset|clear/i.test((x.innerText||x.value||'').trim()));if(n){n.click();return true}return false");time.sleep(4);alert=None
 try:
  a=d.switch_to.alert;alert=a.text;a.accept()
 except Exception:pass
 return {'status':'attempted','clicked_search':bool(clicked),'alert':alert,'start':str(START),'end':str(END)}
def capture_api():
 events=[];reqs={}
 for item in d.get_log('performance'):
  try:
   m=json.loads(item['message'])['message'];p=m.get('params',{});method=m.get('method')
   if method=='Network.requestWillBeSent':
    r=p.get('request',{});u=r.get('url','')
    if 'api.bseindia.com' in u:reqs[p['requestId']]={'url':u,'method':r.get('method'),'headers':r.get('headers',{}),'postData':r.get('postData','')}
   elif method=='Network.responseReceived':
    r=p.get('response',{});u=r.get('url','')
    if 'api.bseindia.com' in u:
     x={'requestId':p.get('requestId'),'url':u,'status':r.get('status'),'mimeType':r.get('mimeType'),'headers':r.get('headers',{})};x.update(reqs.get(p.get('requestId'),{}))
     try:
      body=d.execute_cdp_cmd('Network.getResponseBody',{'requestId':p.get('requestId')}).get('body','');x['body_bytes']=len(body);x['body']=body[:1000000]
      try:
       obj=json.loads(body);x['json_type']=type(obj).__name__;x['json_keys']=list(obj)[:50]
       if isinstance(obj,dict):
        vals=[]
        for k,v in obj.items():
         if isinstance(v,list):vals.extend(v[:3])
        x['json_sample']=vals[:3]
       elif isinstance(obj,list):x['json_sample']=obj[:3]
      except Exception as e:x['json_error']=str(e)
     except Exception as e:x['body_error']=str(e)
     events.append(x)
  except Exception:pass
 return events
report={'source':'BSE','start_date':str(START),'end_date':str(END),'lookback_days':LOOKBACK,'datasets':{}}
try:
 for ds,url in PAGES.items():
  d.get(url);time.sleep(5);before=controls();hist=set_dates();time.sleep(2);events=capture_api();classified=[]
  for e in events:
   matches=[(name,cat) for name,cat in KNOWN.items() if name.lower() in e.get('url','').lower() or name.lower() in e.get('postData','').lower()]
   if matches:e['known_services']=matches;classified.append(e)
  report['datasets'][ds]={'controls':before,'historical_test':hist,'api_request_count':len(events),'known_api_count':len(classified),'known_api':classified,'all_api_urls':[e.get('url') for e in events]}
finally:d.quit()
(OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps({k:(v['api_request_count'],v['known_api_count'],v['historical_test'].get('status')) for k,v in report['datasets'].items()},indent=2))
