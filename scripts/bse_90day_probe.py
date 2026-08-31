import json, os, re, time
from datetime import date, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

END=date.fromisoformat(os.getenv('TARGET_DATE','2026-08-31'))
START=END-timedelta(days=int(os.getenv('LOOKBACK_DAYS','90'))-1)
OUT=Path('artifacts/bse_90day'); OUT.mkdir(parents=True,exist_ok=True)
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139 Safari/537.36'
pages={
 'insider':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2',
 'bulk':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx',
 'block':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx',
}
o=Options(); [o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}')]
d=webdriver.Chrome(options=o)

def snapshot():
 return d.execute_script("""return {tables:Array.from(document.querySelectorAll('table')).map(t=>Array.from(t.querySelectorAll('tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(r=>r.length)),controls:Array.from(document.querySelectorAll('input,select,button')).map(x=>({type:x.type||'',name:x.name||'',id:x.id||'',value:x.value||'',text:(x.innerText||'').trim(),disabled:!!x.disabled}))};""")

def date_controls(s):
 return [x for x in s['controls'] if re.search(r'date|from|to|start|end|datepicker', (x['id']+' '+x['name']+' '+x['text']).lower()) and x['type'] not in ('button','submit')]

def rows(s):
 return [r for t in s['tables'] for r in t if r and not re.fullmatch(r'\d+',r[0] or '')]

out={}
for name,url in pages.items():
 d.get(url); time.sleep(4); before=snapshot(); initial=rows(before); dc=date_controls(before)
 result={'url':d.current_url,'title':d.title,'start':str(START),'end':str(END),'initial_rows':len(initial),'date_controls':dc[:20],'status':'not_tested'}
 # Fill first two date-like inputs with start/end; if only one exists, test the start date.
 vals=[START.strftime('%d/%m/%Y'),END.strftime('%d/%m/%Y')]
 if dc:
  try:
   d.execute_script("""const els=arguments[0], vals=arguments[1]; els.slice(0,2).forEach((x,i)=>{x.value=vals[i];x.dispatchEvent(new Event('input',{bubbles:true}));x.dispatchEvent(new Event('change',{bubbles:true}));}); const bs=Array.from(document.querySelectorAll('button,input[type=submit],a')); const b=bs.find(x=>/search|submit|go|view/i.test((x.innerText||x.value||'').trim())&&!/reset/i.test((x.innerText||x.value||'').trim())); if(b)b.click();""",dc,vals)
   time.sleep(4); after=snapshot(); ar=rows(after)
   result.update(status='changed' if len(ar)!=len(initial) or ar[:5]!=initial[:5] else 'no_change',after_rows=len(ar),sample_dates=[r[0] for r in ar[:20]])
  except Exception as e: result.update(status='error',error=str(e))
 else:
  result['status']='no_date_controls_found'
 out[name]=result
Path(OUT/'result.json').write_text(json.dumps({'lookback_days':90,'start':str(START),'end':str(END),'datasets':out},indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
d.quit()
