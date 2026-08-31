from __future__ import annotations

import json, os, re, time
from datetime import date, datetime
from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

TARGET_DATE = date.fromisoformat(os.getenv('TARGET_DATE', '2026-08-31'))
SECOND_DATE = date.fromisoformat(os.getenv('SECOND_DATE', '2026-08-28'))
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/139.0 Safari/537.36'
OUT = Path('artifacts/data_validation')
OUT.mkdir(parents=True, exist_ok=True)


def norm_text(v):
    if v is None: return ''
    s = str(v).upper().strip()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^A-Z0-9 .&/-]', '', s)
    return s.strip()


def norm_name(v):
    s = norm_text(v)
    s = re.sub(r'\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CO|COMPANY|HUF)\b', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def norm_symbol(v): return re.sub(r'[^A-Z0-9]', '', norm_text(v))


def num(v):
    if v is None or v == '': return None
    s = re.sub(r'[^0-9.\-]', '', str(v))
    try: return float(s) if '.' in s else int(s)
    except Exception: return None


def parse_date(v):
    if v is None: return None
    s = str(v).strip()
    for fmt in ('%d/%m/%Y','%d-%m-%Y','%d %b %Y','%d %b %y','%d-%b-%Y','%Y-%m-%d','%d-%m-%y','%d/%b/%Y'):
        try: return datetime.strptime(s, fmt).date()
        except Exception: pass
    return None


def get_session(domain):
    s = requests.Session()
    ref = 'https://www.nseindia.com/' if domain == 'NSE' else 'https://www.bseindia.com/'
    s.headers.update({'User-Agent': UA, 'Referer': ref, 'Accept': 'application/json,text/plain,*/*', 'Accept-Language': 'en-US,en;q=0.9'})
    try: s.get(ref, timeout=20)
    except Exception: pass
    return s


def nse_data(d):
    out=[]; dd=d.strftime('%d-%m-%Y'); s=get_session('NSE')
    url=f'https://www.nseindia.com/api/corporates-pit?index=equities&from_date={dd}&to_date={dd}&csv=true'
    try:
        r=s.get(url,timeout=30); text=r.content.decode('utf-8-sig',errors='replace')
        if r.ok and text.lstrip().startswith(('"SYMBOL','SYMBOL')):
            df=pd.read_csv(StringIO(text)); out.append(('insider_trading',df.fillna('').to_dict('records'),{'method':'official_csv','status':r.status_code,'columns':list(df.columns)}))
        else: out.append(('insider_trading',[],{'method':'official_csv','status':r.status_code,'content_prefix':text[:200]}))
    except Exception as e: out.append(('insider_trading',[],{'method':'official_csv','error':str(e)}))
    try:
        from nse import NSE
        with NSE(download_folder=str(OUT/'nse'),server=True,timeout=30) as nse:
            for kind in ('bulk_deals','block_deals'):
                try:
                    rows=[dict(x) for x in nse.bulkdeals(kind,datetime.combine(d,datetime.min.time()),datetime.combine(d,datetime.min.time()))]
                    out.append((kind,rows,{'method':'nse_package_server','columns':sorted(rows[0].keys()) if rows else [],'status':'success'}))
                except Exception as e: out.append((kind,[],{'method':'nse_package_server','status':'error','error':str(e)}))
    except Exception as e:
        out.extend([(k,[],{'method':'nse_package_server','status':'error','error':str(e)}) for k in ('bulk_deals','block_deals')])
    return out


def bse_browser(d):
    results=[]
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        o=Options()
        for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu',f'--user-agent={UA}'): o.add_argument(x)
        driver=webdriver.Chrome(options=o)
    except Exception as e: return [('browser_import',[],{'status':'error','error':str(e)})]
    pages={'bulk_deals':'https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx','block_deals':'https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx','insider_trading':'https://www.bseindia.com/corporates/insider_trading_new?expandable=2','rights_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_ri','preferential_issue':'https://www.bseindia.com/markets/publicissues/furtherissuesummary_pref'}
    for dataset,url in pages.items():
        try:
            driver.get(url); time.sleep(4)
            title=driver.title; current=driver.current_url
            tables=driver.execute_script("""return Array.from(document.querySelectorAll('table')).map(t=>({headers:Array.from(t.querySelectorAll('thead th')).map(x=>(x.innerText||'').trim()),rows:Array.from(t.querySelectorAll('tbody tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length)})).filter(x=>x.rows.length);""")
            inputs=driver.execute_script("""return Array.from(document.querySelectorAll('input,select,button')).map(x=>({tag:x.tagName,type:x.type||'',name:x.name||'',id:x.id||'',value:x.value||'',text:(x.innerText||'').trim()})).filter(x=>x.name||x.id||x.value||x.text).slice(0,120);""")
            rows=[]; headers=[]
            for t in tables:
                h=t.get('headers') or []
                for row in t.get('rows',[]):
                    if h and len(h)==len(row): rows.append(dict(zip(h,row))); headers=h
                    else: rows.append({f'col_{i}':v for i,v in enumerate(row)})
            historical_test={'attempted':False,'status':'not_attempted','target_date':SECOND_DATE.isoformat(),'matched_rows':0}
            date_controls=[c for c in inputs if str(c.get('type','')).lower()=='date' or any(t in norm_text(str(c)) for t in ('FROM DATE','TO DATE','DATE FROM','DATE TO','START DATE','END DATE'))]
            if date_controls:
                historical_test['attempted']=True
                try:
                    target_str=SECOND_DATE.strftime('%Y-%m-%d')
                    driver.execute_script("""
                    const val=arguments[0];
                    const nodes=Array.from(document.querySelectorAll('input,select')).filter(x => x.type==='date' || /date|from|to|start|end/i.test((x.name||'')+' '+(x.id||'')) || /date|from|to|start|end/i.test(x.value||''));
                    for (const n of nodes) { try { const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set; if(setter) setter.call(n,val); else n.value=val; n.dispatchEvent(new Event('input',{bubbles:true})); n.dispatchEvent(new Event('change',{bubbles:true})); } catch(e){} }
                    const buttons=Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a')).filter(x => /search|submit|go|apply|refresh|view/i.test((x.innerText||x.value||'').trim()));
                    if(buttons.length) buttons[0].click();
                    """,target_str)
                    time.sleep(4)
                    hist_tables=driver.execute_script("""return Array.from(document.querySelectorAll('table')).map(t=>({headers:Array.from(t.querySelectorAll('thead th')).map(x=>(x.innerText||'').trim()),rows:Array.from(t.querySelectorAll('tbody tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length)})).filter(x=>x.rows.length);""")
                    hist_rows=[]
                    for ht in hist_tables:
                        h=ht.get('headers') or []
                        for row in ht.get('rows',[]): hist_rows.append(dict(zip(h,row)) if h and len(h)==len(row) else {f'col_{i}':v for i,v in enumerate(row)})
                    matched=sum(1 for hr in hist_rows if any(parse_date(v)==SECOND_DATE for v in hr.values()))
                    historical_test.update(status='success' if matched else 'no_match',matched_rows=matched,row_count=len(hist_rows),controls_used=date_controls[:20])
                except Exception as he: historical_test.update(status='error',error=str(he))
            parsed_dates=[p.isoformat() for r in rows for p in [parse_date(v) for v in r.values()] if p]
            body=driver.find_element('tag name','body').text
            contains_target=any(x in body for x in (d.strftime('%d/%m/%Y'),d.strftime('%d-%m-%Y'),d.strftime('%d %b %Y'),d.strftime('%d %b %y'))) or any(parse_date(v)==d for r in rows for v in r.values())
            results.append((dataset,rows,{'method':'selenium_render','status':'success','title':title,'url':current,'columns':headers,'table_count':len(tables),'row_count':len(rows),'parsed_dates':sorted(set(parsed_dates))[:50],'contains_target_date':contains_target,'controls':inputs,'historical_date_test':historical_test}))
        except Exception as e: results.append((dataset,[],{'method':'selenium_render','status':'error','error':str(e)}))
    driver.quit(); return results


def pick(r,*names):
    for n in names:
        nn=norm_text(n)
        for k,v in r.items():
            nk=norm_text(k)
            if nk==nn or nn in nk: return v
    return ''


def normalize(dataset,source,rows):
    out=[]
    for r in rows:
        x={'source':source,'dataset':dataset,'raw':r}
        if dataset=='insider_trading':
            x.update(event_date=pick(r,'DATE','DT_DATE','DATE OF DISCLOSURE'),symbol=pick(r,'SYMBOL','SCRIP NAME','Security Name','Security'),company=pick(r,'COMPANY','COMPANY NAME'),person=pick(r,'NAME OF THE ACQUIRER/DISPOSER','NAME OF ACQUIRER/DISPOSER','NAME','CLIENT NAME','Name of the Person'),side=pick(r,'BUY/SELL','TRANSACTION TYPE','TYPE OF TRANSACTION','BUY/SELL (B/S)'),quantity=pick(r,'NO. OF SECURITIES','NO. OF SECURITY','QUANTITY','QTY'),price=pick(r,'PRICE','TRADE PRICE','VALUE'))
        elif dataset in ('bulk_deals','block_deals'):
            x.update(event_date=pick(r,'BD_DT_DATE','DATE','Date'),symbol=pick(r,'BD_SYMBOL','SYMBOL','SCRIP NAME','Security Code'),company=pick(r,'BD_SCRIP_NAME','SECURITY NAME','Company'),person=pick(r,'BD_CLIENT_NAME','CLIENT NAME','Client Name'),side=pick(r,'BD_BUY_SELL','BUY/SELL','DEAL TYPE','Buy/Sell'),quantity=pick(r,'BD_QTY_TRD','QUANTITY','Quantity'),price=pick(r,'BD_TP_WATP','TRADE PRICE','Trade Price'))
        else:
            x.update(event_date=pick(r,'DATE'),symbol=pick(r,'SYMBOL','SCRIP','SECURITY CODE'),company=pick(r,'COMPANY','SECURITY NAME','NAME OF THE COMPANY'),person=pick(r,'PERSON','APPLICANT','CLIENT'),side=pick(r,'TYPE','BUY/SELL','DEAL'),quantity=pick(r,'QUANTITY','NO OF SHARES'),price=pick(r,'PRICE','VALUE'))
        x['date_iso']=parse_date(x.get('event_date')).isoformat() if parse_date(x.get('event_date')) else ''
        x['symbol_norm']=norm_symbol(x.get('symbol')); x['company_norm']=norm_name(x.get('company')); x['person_norm']=norm_name(x.get('person')); x['side_norm']=norm_text(x.get('side')); x['quantity_num']=num(x.get('quantity')); x['price_num']=num(x.get('price'))
        out.append(x)
    return out


def dedup_for(dataset,rows):
    fields=(['date_iso','symbol_norm','company_norm','person_norm','side_norm','quantity_num','price_num'] if dataset=='insider_trading' else ['date_iso','symbol_norm','person_norm','side_norm','quantity_num','price_num'] if dataset in ('bulk_deals','block_deals') else ['date_iso','symbol_norm','company_norm','quantity_num','price_num'])
    seen={}; unique=[]; dups=[]
    for r in rows:
        k=tuple(r.get(f) for f in fields)
        if k in seen: dups.append({'duplicate_of':seen[k],'key':k,'record':r})
        else: seen[k]=len(unique); unique.append(r)
    return unique,dups,fields


def similarity(a,b):
    vals=[SequenceMatcher(None,a.get(f,''),b.get(f,'')).ratio() for f in ('symbol_norm','company_norm','person_norm') if a.get(f) and b.get(f)]
    return max(vals) if vals else 0.0


def cross_match(nse,bse,dataset):
    matches=[]
    for i,a in enumerate(nse):
        for j,b in enumerate(bse):
            if a.get('date_iso') and b.get('date_iso') and a['date_iso']!=b['date_iso']: continue
            if a.get('symbol_norm') and b.get('symbol_norm') and a['symbol_norm']!=b['symbol_norm']: continue
            qty_equal=a.get('quantity_num') is not None and a.get('quantity_num')==b.get('quantity_num')
            price_equal=a.get('price_num') is not None and b.get('price_num') is not None and abs(a['price_num']-b['price_num'])<1e-9
            person_sim=similarity(a,b); side_equal=bool(a.get('side_norm') and b.get('side_norm') and a['side_norm'][0]==b['side_norm'][0])
            score=(0.35 if qty_equal else 0)+(0.25 if price_equal else 0)+(0.25 if person_sim>=0.9 else 0)+(0.15 if side_equal else 0)
            if score>=0.75: matches.append({'nse_index':i,'bse_index':j,'score':round(score,3),'quantity_equal':qty_equal,'price_equal':price_equal,'person_similarity':round(person_sim,3),'side_equal':side_equal,'action':'collapse_candidate' if dataset in ('insider_trading','rights_issue','preferential_issue') else 'flag_only_exchange_specific'})
    return matches


def run():
    all_sources=[]
    for d,label in ((TARGET_DATE,'target'),(SECOND_DATE,'historical_probe')):
        for ds,rows,meta in nse_data(d): all_sources.append({'source':'NSE','dataset':ds,'date':d.isoformat(),'rows':rows,'meta':meta,'label':label})
        if label=='target':
            for ds,rows,meta in bse_browser(d): all_sources.append({'source':'BSE','dataset':ds,'date':d.isoformat(),'rows':rows,'meta':meta,'label':label})
    report={'generated_at_utc':datetime.utcnow().isoformat(),'target_date':TARGET_DATE.isoformat(),'historical_probe_date':SECOND_DATE.isoformat(),'source_specific':[],'cross_exchange':[]}
    canonical={}
    for item in all_sources:
        norm=normalize(item['dataset'],item['source'],item['rows']); unique,dups,fields=dedup_for(item['dataset'],norm)
        rec={'source':item['source'],'dataset':item['dataset'],'probe_date':item['date'],'label':item['label'],'method':item['meta'].get('method'),'status':item['meta'].get('status','success'),'raw_row_count':len(item['rows']),'normalized_row_count':len(norm),'unique_row_count':len(unique),'duplicate_row_count':len(dups),'dedup_key_fields':fields,'columns':item['meta'].get('columns',sorted(item['rows'][0].keys()) if item['rows'] else []),'parsed_date_values':sorted(set(x.get('date_iso') for x in norm if x.get('date_iso'))),'contains_target_date':item['meta'].get('contains_target_date'),'historical_date_test':item['meta'].get('historical_date_test'),'sample_normalized':unique[:5],'duplicates':dups[:20]}
        report['source_specific'].append(rec); canonical[(item['source'],item['dataset'],item['label'])]=unique
        if item['label']=='target': Path(OUT/f"{item['source'].lower()}_{item['dataset']}_normalized.json").write_text(json.dumps(unique,indent=2,default=str),encoding='utf-8')
    for ds in sorted(set(k[1] for k in canonical if k[2]=='target')):
        n=canonical.get(('NSE',ds,'target'),[]); b=canonical.get(('BSE',ds,'target'),[])
        if n and b: report['cross_exchange'].append({'dataset':ds,'nse_unique':len(n),'bse_unique':len(b),'candidate_matches':cross_match(n,b,ds)[:500],'policy':'insider/issue candidates may collapse after review; bulk/block matches are flags only because exchanges are separate execution venues'})
    Path(OUT/'validation_report.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8'); print(json.dumps(report,indent=2,default=str))

if __name__=='__main__': run()
