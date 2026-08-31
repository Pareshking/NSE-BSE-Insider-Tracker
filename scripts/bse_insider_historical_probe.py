import json,time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoAlertPresentException
H='28/08/2026'
o=Options();[o.add_argument(x) for x in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--disable-gpu')]
d=webdriver.Chrome(options=o);d.get('https://www.bseindia.com/corporates/insider_trading_new?expandable=2');time.sleep(4)
res={'target_date':H}
try:
    els=[x for x in d.find_elements('css selector','input[name="datepicker"]') if x.is_displayed()]
    res['visible_date_inputs']=len(els);vals=[]
    for e in els[:2]:
        e.click();e.send_keys(Keys.CONTROL,'a');e.send_keys(H);e.send_keys(Keys.TAB);time.sleep(.3);vals.append(e.get_attribute('value'))
    res['entered_values']=vals;d.find_element('id','btnsubmit').click();time.sleep(2)
    try:
        a=d.switch_to.alert;res['alert']=a.text;a.accept()
    except NoAlertPresentException:res['alert']=None
    rows=d.execute_script("return Array.from(document.querySelectorAll('table tr')).map(r=>Array.from(r.cells).map(c=>(c.innerText||'').trim())).filter(x=>x.length)")
    res['row_count']=len(rows);res['sample_rows']=rows[:5]
except Exception as e:res['error']=str(e)
d.quit();print(json.dumps(res,indent=2))
