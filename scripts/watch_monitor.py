#!/usr/bin/env python3
"""Independent localhost watchdog; keeps working if Django itself stops."""
import argparse,fcntl,json,os,re,time,urllib.request,urllib.parse,urllib.error
from datetime import datetime,timezone
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1]

def timestamp():return datetime.now(timezone.utc).isoformat()
def atomic_json(path,data):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.parent.chmod(0o700)
 tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as file:json.dump(data,file,ensure_ascii=False)
 os.replace(tmp,path)

def telegram(config,text):
 token=config.get('bot_token','');chat=str(config.get('chat_id',''))
 if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',token) or not re.fullmatch(r'-?\d+',chat):return False,'telegram_not_configured'
 request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',data=urllib.parse.urlencode({'chat_id':chat,'text':text,'disable_web_page_preview':'true','protect_content':'true','reply_markup':json.dumps({'inline_keyboard':[[{'text':'Состояние системы','callback_data':'server'},{'text':'Безопасность','callback_data':'security'}]]})}).encode())
 try:
  with urllib.request.urlopen(request,timeout=5) as response:result=json.load(response)
  return (True,'') if result.get('ok') else (False,'telegram_api_rejected')
 except urllib.error.HTTPError as error:return False,'telegram_http_'+str(error.code)
 except Exception:return False,'telegram_network_error'  # Never stringify token-bearing URLs.

def evaluate(config,previous,probe,metrics):
 conditions={}
 if not probe.get('reachable'):conditions['application']={'summary':'Приложение Django не отвечает','severity':'critical'}
 elif not probe.get('database_ok'):conditions['database']={'summary':'База данных недоступна','severity':'critical'}
 if probe.get('http_5xx_1m',0):conditions['http_5xx']={'summary':'Зафиксированы ошибки HTTP 5xx за последнюю минуту','severity':'critical'}
 if probe.get('slow_1m',0)>=3:conditions['slow_requests']={'summary':'Несколько запросов выполняются дольше двух секунд','severity':'warning'}
 for key,label,threshold in [('cpu','CPU',90),('memory','RAM',90),('disk','диска',90)]:
  if metrics[key]>=float(config.get(key+'_threshold',threshold)):
   conditions[key]={'summary':f'Высокое использование {label}: {metrics[key]:.0f}%','severity':'warning'}
 active=dict(previous.get('active_incidents') or {});streaks=dict(previous.get('streaks') or {});recoveries=dict(previous.get('pending_recoveries') or {});events=[]
 for key in set(conditions)|set(active)|set(streaks):
  present=key in conditions;streaks[key]=streaks.get(key,0)+1 if present else 0
  needed=3 if key in ('cpu','memory','disk') else int(config.get('failure_samples',2))
  if present and streaks[key]>=needed and key not in active:
   active[key]={**conditions[key],'opened_at':timestamp(),'delivered':False}
  if not present and key in active:
   old=active.pop(key)
   if old.get('delivered'):recoveries[key]={'kind':'recovery','key':key,'summary':{'application':'Приложение Django снова отвечает','database':'Связь с базой данных восстановлена','http_5xx':'Новых HTTP 5xx за последнюю минуту нет','slow_requests':'Поток медленных запросов прекратился','cpu':'Использование CPU ниже порога','memory':'Использование RAM ниже порога','disk':'Использование диска ниже порога'}.get(key,'Проверка снова проходит'),'at':timestamp()}
 # An undelivered alert is retried, but a delivered active incident is never spammed.
 for key,value in active.items():
  if not value.get('delivered'):events.append({'kind':'alert','key':key,**value})
 events=list(recoveries.values())+events
 return {**previous,'active_incidents':active,'streaks':streaks,'pending_recoveries':recoveries},events

def probe_health(config):
 url=config.get('health_url','http://127.0.0.1:8000/internal/monitor-health/');parsed=urllib.parse.urlparse(url)
 if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.path!='/internal/monitor-health/':return {'reachable':False}
 request=urllib.request.Request(url,headers={'Authorization':'Bearer '+config.get('health_token','')})
 try:
  with urllib.request.urlopen(request,timeout=3) as response:data=json.load(response)
 except urllib.error.HTTPError as error:
  if error.code==503:
   try:data=json.load(error)
   except Exception:return {'reachable':False}
  else:return {'reachable':False}
 except Exception:return {'reachable':False}
 host=data.get('host',{})
 return {'reachable':True,'database_ok':bool(host.get('database',{}).get('ok')),'http_5xx_1m':host.get('http_5xx_1m',0),'slow_1m':host.get('slow_1m',0)}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=ROOT/'.local-monitoring.json');parser.add_argument('--once',action='store_true');parser.add_argument('--test-message',action='store_true');args=parser.parse_args()
 try:config=json.loads(args.config.read_text())
 except Exception:raise SystemExit('Monitoring configuration unavailable')
 folder=Path(config.get('state_dir',str(ROOT/'.local-monitoring')));folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700)
 if args.test_message:
  ok,error=telegram(config,'Tuysqan Coffee: тестовое уведомление. Мониторинг подключён к этому чату. Финансовые данные и данные гостей в уведомления не передаются.')
  atomic_json(folder/'telegram-test.json',{'at':timestamp(),'ok':ok,'error':error})
  print('Telegram test delivered.' if ok else 'Telegram test failed: '+error);return
 lock=(folder/'watchdog.lock').open('a');os.chmod(folder/'watchdog.lock',0o600)
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('Monitoring watchdog already running')
 path=folder/'watchdog-state.json'
 try:state=json.loads(path.read_text())
 except Exception:state={}
 if not state.get('last_delivery_at'):
  try:
   test=json.loads((folder/'telegram-test.json').read_text())
   if test.get('ok'):state['last_delivery_at']=test['at']
  except Exception:pass
 while True:
  try:config=json.loads(args.config.read_text())
  except Exception:pass
  probe=probe_health(config);metrics={'cpu':psutil.cpu_percent(interval=.1),'memory':psutil.virtual_memory().percent,'disk':psutil.disk_usage(ROOT).percent}
  state,events=evaluate(config,state,probe,metrics);state.update(last_check_at=timestamp(),running_pid=os.getpid(),last_error=state.get('last_error',''))
  for event in events:
   prefix='Восстановление' if event['kind']=='recovery' else 'Проблема'
   message='Tuysqan Coffee · '+prefix+'\n'+event['summary']+'\n'+event.get('at',event.get('opened_at',''))
   ok,error=telegram(config,message)
   if ok:
    state['last_delivery_at']=timestamp();state['last_error']=''
    if event['kind']=='alert':state['active_incidents'][event['key']]['delivered']=True
    else:state['pending_recoveries'].pop(event['key'],None)
   else:state['last_error']=error
   state['history']=([{'at':timestamp(),'kind':event['kind'],'summary':event['summary'],'delivered':ok}]+state.get('history',[]))[:30]
  try:atomic_json(path,state)
  except OSError:state['last_error']='monitor_state_write_failed'
  if args.once:break
  time.sleep(max(5,int(config.get('interval_seconds',15))))
if __name__=='__main__':main()
