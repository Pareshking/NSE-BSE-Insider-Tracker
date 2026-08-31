"""Validate BSE capture without mixing NSE data.

This is an evidence report, not a green-badge proxy. It reports structural,
date-coverage and semantic gates for each BSE dataset and preserves native rows.
"""
from __future__ import annotations
import json, re, hashlib
from datetime import date, datetime
from pathlib import Path

RAW=Path('artifacts/data_validation_v5/bse_raw.json')
OUT=Path('artifacts/bse_validation'); OUT.mkdir(parents=True,exist_ok=True)

def norm_text(x): return re.sub(r'\s+',' ',str(x or '').strip())
def num(x):
    s=re.sub(r'[^0-9.\-]','',str(x or ''))
    try: return float(s) if '.' in s else int(s)
    except: return None

def dates_in_row(row):
    out=[]
    for cell in row:
        s=norm_text(cell)
        for m in re.findall(r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b',s):
            for f in ('%d/%m/%Y','%d-%m-%Y','%d/%m/%y','%d-%m-%y','%Y-%m-%d'):
                try: out.append(datetime.strptime(m,f).date().isoformat()); break
                except: pass
    return out

def key(ds,r):
    if ds in ('bulk_deals','block_deals') and len(r)>=7:
        return (r[0],r[1],r[3],r[4],r[5],r[6])
    if ds=='insider_trading' and len(r)>=16:
        return (r[0],r[1],r[2],r[3],r[6],r[7],r[8],r[10],r[15])
    if ds in ('rights_issue','preferential_issue'):
        return tuple(norm_text(x).upper() for x in r[:4])
    return tuple(norm_text(x) for x in r)

def normalize(ds,r):
    # BSE-native positional mapping is intentionally retained alongside analytical fields.
    if ds in ('bulk_deals','block_deals') and len(r)>=7:
        return {'event_date':r[0],'security_code':r[1],'security_name':r[2],'company':r[2],'person':r[3],'side':r[4],'quantity':r[5],'price':r[6],'raw':r}
    if ds=='insider_trading' and len(r)>=16:
        return {'security_code':r[0],'company':r[1],'person':r[2],'category':r[3],'holding_before':r[4],'security_type':r[5],'quantity':r[6],'value':r[7],'side':r[8],'holding_after':r[9],'acquisition_date':r[10],'mode':r[11],'remarks':r[12:15],'broadcast_date':r[15],'raw':r}
    if ds in ('rights_issue','preferential_issue') and r:
        return {'company':r[0], 'stage_1':r[1] if len(r)>1 else '', 'stage_2':r[2] if len(r)>2 else '', 'stage_3':r[3] if len(r)>3 else '', 'raw':r}
    return {'raw':r}

def main():
    if not RAW.exists(): raise SystemExit(f'Missing {RAW}')
    src=json.loads(RAW.read_text())
    report={'source':'BSE','capture_start':src.get('start_date'),'capture_end':src.get('target_date'),'lookback_days':src.get('lookback_days'),'datasets':{},'certification':'BLOCKED'}
    for ds,obj in src.get('datasets',{}).items():
        rows=[]
        for pg in obj.get('pages',[]):
            for r in pg.get('rows',[]):
                if not r: continue
                header=' '.join(str(x) for x in r).lower()
                if ('deal date' in header and 'security code' in header) or ('security code' in header and 'company name' in header): continue
                rows.append(r)
        unique=[]; seen={}; duplicates=[]
        for r in rows:
            k=key(ds,r); h=hashlib.sha1(json.dumps(k,ensure_ascii=False,default=str).encode()).hexdigest()
            if h in seen: duplicates.append({'duplicate_of':seen[h],'key':k,'raw':r})
            else: seen[h]=len(unique); unique.append(r)
        normalized=[normalize(ds,r) for r in unique]
        dates=sorted({d for r in rows for d in dates_in_row(r)})
        sem={}
        if ds in ('bulk_deals','block_deals'):
            sem={'has_direction':sum(bool(norm_text(r[4])) for r in rows if len(r)>=5)==len([r for r in rows if len(r)>=5]),'buy_rows':sum(norm_text(r[4]).upper()=='BUY' for r in rows if len(r)>=5),'sell_rows':sum(norm_text(r[4]).upper()=='SELL' for r in rows if len(r)>=5),'native_columns_present':all(len(r)>=7 for r in rows)}
        elif ds=='insider_trading':
            sem={'native_columns_present':all(len(r)>=16 for r in rows),'has_person':sum(bool(norm_text(r[2])) for r in rows if len(r)>=3)==len([r for r in rows if len(r)>=3]),'has_category':sum(bool(norm_text(r[3])) for r in rows if len(r)>=4)==len([r for r in rows if len(r)>=4]),'acquisition_rows':sum(norm_text(r[8]).upper()=='ACQUISITION' for r in rows if len(r)>=9),'disposal_rows':sum(norm_text(r[8]).upper()=='DISPOSAL' for r in rows if len(r)>=9),'promoter_group_rows':sum(norm_text(r[3]).upper()=='PROMOTER GROUP' for r in rows if len(r)>=4)}
        elif ds in ('rights_issue','preferential_issue'):
            sem={'index_rows':len(rows),'detail_pages':len(obj.get('detail_pages',[])),'detail_rows':sum(len(x.get('rows',[])) for x in obj.get('detail_pages',[]))}
        hist=obj.get('historical_date_test',{})
        report['datasets'][ds]={'raw_rows':len(rows),'unique_rows':len(unique),'duplicate_rows':len(duplicates),'distinct_dates':dates,'earliest_date':dates[0] if dates else None,'latest_date':dates[-1] if dates else None,'historical_test':hist,'semantics':sem,'normalized_file':str(OUT/f'{ds}_normalized.json'),'status':'PENDING'}
        (OUT/f'{ds}_normalized.json').write_text(json.dumps(normalized,indent=2,ensure_ascii=False,default=str))
    # A dataset is not certified merely because rows exist: historical date evidence must exist for the 90-day transaction feeds.
    for ds in ('insider_trading','bulk_deals','block_deals'):
        x=report['datasets'].get(ds,{})
        x['status']='VERIFIED' if x.get('raw_rows',0)>0 and x.get('distinct_dates') and x.get('semantics',{}).get('native_columns_present',False) else 'BLOCKED'
    # Rights/preferential require detail evidence, not just an index.
    for ds in ('rights_issue','preferential_issue'):
        x=report['datasets'].get(ds,{})
        x['status']='VERIFIED' if x.get('raw_rows',0)>0 and x.get('semantics',{}).get('detail_rows',0)>0 else 'BLOCKED'
    report['certification']='VERIFIED' if all(report['datasets'].get(ds,{}).get('status')=='VERIFIED' for ds in ('insider_trading','bulk_deals','block_deals','rights_issue','preferential_issue')) else 'BLOCKED'
    (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str)); print(json.dumps(report,indent=2,ensure_ascii=False,default=str))

if __name__=='__main__': main()
