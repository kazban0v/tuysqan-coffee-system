#!/usr/bin/env python3
"""Owner-only, read-only Telegram controls. No shell execution."""
import argparse,fcntl,json,os,re,time,urllib.error,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUTTONS={'Сервер':'server','Выручка':'revenue','Заказы':'orders','Безопасность':'security','События':'events','Помощь':'help'}
ACTIONS=set(BUTTONS.values())|{'start','menu'}
KEYBOARD={'keyboard':[[{'text':a},{'text':b}] for a,b in [('Сервер','Выручка'),('Заказы','Безопасность'),('События','Помощь')]],'resize_keyboard':True,'is_persistent':True}
def now():return datetime.now(timezone.utc).isoformat()
def atomic_json(path,value):
 path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as output:json.dump(value,output,ensure_ascii=False)
 os.replace(tmp,path)
def read_state(folder,name):
 try:
  value=json.loads((folder/name).read_text());return value if isinstance(value,dict) else {}
 except (OSError,ValueError):return {}
def api(config,method,fields=None,timeout=8):
 if method not in {'getMe','getWebhookInfo','getUpdates','sendMessage','answerCallbackQuery','setMyCommands'}:return None,'method_not_allowed'
 token=config.get('bot_token','')
 if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',token):return None,'telegram_not_configured'
 request=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,data=json.dumps(fields or {}).encode(),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=timeout) as response:value=json.load(response)
  return (value.get('result'),'') if value.get('ok') else (None,'telegram_api_rejected')
 except urllib.error.HTTPError as error:return None,'telegram_http_'+str(error.code)
 except Exception:return None,'telegram_network_error'
def owner_id(config):
 value=str(config.get('owner_user_id',''));return int(value) if value.isdecimal() and int(value)>0 else None
def action_for(config,update):
 owner=owner_id(config);callback=update.get('callback_query')
 message=callback.get('message',{}) if isinstance(callback,dict) else update.get('message',{})
 sender=callback.get('from',{}) if isinstance(callback,dict) else message.get('from',{});chat=message.get('chat',{})
 if not owner or sender.get('id')!=owner or chat.get('id')!=owner or chat.get('type')!='private' or sender.get('is_bot'):return None
 stamp=message.get('date',0)
 if not callback and (not isinstance(stamp,int) or time.time()-stamp>300 or stamp>time.time()+60 or message.get('forward_origin')):return None
 if callback:action=callback.get('data','')
 else:
  text=message.get('text','').strip()
  if len(text)>100:return None
  action=BUTTONS.get(text)
  if not action and text.startswith('/'):action=text.split()[0][1:].split('@')[0]
 return action if action in ACTIONS else None
def local_status(config):
 url=config.get('bot_status_url','');parsed=urllib.parse.urlparse(url);secret=config.get('bot_api_token','')
 if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.path!='/internal/developer-bot-status/' or not secret:return None
 request=urllib.request.Request(url,headers={'Authorization':'Bearer '+secret})
 try:
  with urllib.request.urlopen(request,timeout=4) as response:return json.load(response)
 except Exception:return None
def money(value):
 try:return f'{float(value):,.0f}'.replace(',',' ')+' ₸'
 except (ValueError,TypeError,OverflowError):return 'недоступно'
def security_text(folder):
 data=read_state(folder,'ssh-state.json')
 try:
  age=(datetime.now(timezone.utc)-datetime.fromisoformat(data['last_check_at'])).total_seconds();active=0<=age<90 and data.get('source')=='systemd-journal' and data.get('journal_running') is True
 except (KeyError,TypeError,ValueError):active=False
 lines=['Безопасность','Доступ к боту: только ваш личный Telegram ID.','Выполнение команд, перезагрузка и изменение заказов через бота отключены.','SSH-наблюдение: '+('работает на этом сервере' if active else 'не подключено или нет свежего сигнала')]
 for event in data.get('history',[])[:4]:
  if event.get('kind')=='ssh_success':lines.append(f"SSH: {event.get('user','?')} · {event.get('ip','?')} · {event.get('at','')}")
 return '\n'.join(lines)
def reply_text(action,data,folder):
 if action in ('start','menu','help'):
  return ('Tuysqan · ваше управление\n\nСервер — CPU, RAM, диск и база.\nВыручка — оплаты минус возвраты.\nЗаказы — активные и неоплаченные.\nБезопасность — SSH-наблюдение.\nСобытия — аварии и восстановления.\n\nДоступ только в вашем личном чате. Сейчас источник — локальный компьютер; после подключения VPS — сервер. Время событий — UTC.')
 if action=='security':return security_text(folder)
 if action=='events':
  rows=read_state(folder,'watchdog-state.json').get('history',[])[:6]
  return '\n'.join(['События мониторинга']+[str(r.get('summary',''))[:200]+' · '+str(r.get('at','')) for r in rows]+([] if rows else ['Событий пока нет.']))
 if not data:return 'Приложение сейчас недоступно. Независимый наблюдатель продолжает проверку. Попробуйте позже.'
 host,business=data.get('host',{}),data.get('business',{})
 if action=='server':
  return ('Состояние системы · '+('локальная среда' if data.get('local_only',True) else 'сервер')+f"\nCPU: {host.get('cpu_percent','?')}%\nRAM: {host.get('memory_percent','?')}%\nДиск занят: {host.get('disk_used_percent','?')}%\nБаза: "+('доступна' if host.get('database',{}).get('ok') else 'недоступна')+f"\nПроверено: {host.get('checked_at','?')}")
 if business.get('available') is False or not business:return 'Финансовые показатели сейчас недоступны. Попробуйте позже.'
 if action=='revenue':return 'Выручка · оплаты минус возвраты\nСегодня: '+money(business.get('today',{}).get('net'))+'\nПоследние 7 дней: '+money(business.get('week',{}).get('net'))+'\nТекущий месяц: '+money(business.get('month',{}).get('net'))+'\nЭто выручка, не чистая прибыль.'
 return f"Заказы\nАктивные: {business.get('active_orders','?')}\nОжидают оплаты: {business.get('unpaid_orders','?')}\nНеоплаченная сумма: "+money(business.get('unpaid_total'))
def send_reply(config,text):return api(config,'sendMessage',{'chat_id':owner_id(config),'text':text,'reply_markup':KEYBOARD,'protect_content':True})
def process_update(config,update,state,folder):
 uid=update.get('update_id')
 if not isinstance(uid,int) or uid<state.get('offset',0):return state
 action=action_for(config,update)
 if action:
  if time.time()-state.get('last_reply_at_epoch',0)>=2:
   data=local_status(config) if action in ('server','revenue','orders') else None
   _,error=send_reply(config,reply_text(action,data,folder))
   if error:state['last_error']=error;return state
   state['last_reply_at_epoch']=time.time();state['last_error']=''
  if update.get('callback_query'):api(config,'answerCallbackQuery',{'callback_query_id':update['callback_query'].get('id'),'text':'Готово'})
 state['offset']=uid+1;return state
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=ROOT/'.local-monitoring.json');parser.add_argument('--send-menu',action='store_true');args=parser.parse_args()
 try:config=json.loads(args.config.read_text())
 except (OSError,ValueError):raise SystemExit('Private monitoring config unavailable')
 if not owner_id(config) or str(owner_id(config))!=str(config.get('chat_id')):raise SystemExit('Explicit matching personal owner ID and chat ID required')
 folder=Path(config['state_dir']);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
 if args.send_menu:
  _,error=send_reply(config,reply_text('menu',None,folder));print('Owner menu delivered.' if not error else 'Owner menu failed: '+error);return
 lock=(folder/'telegram-control.lock').open('a');os.chmod(folder/'telegram-control.lock',0o600)
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('Owner bot listener already running')
 webhook,error=api(config,'getWebhookInfo')
 if error or webhook is None:raise SystemExit('Cannot verify Telegram webhook: '+error)
 if webhook.get('url'):raise SystemExit('Existing webhook detected; not replaced')
 commands=[{'command':k,'description':v} for k,v in [('menu','Открыть меню'),('server','Состояние системы'),('revenue','Выручка'),('orders','Заказы'),('security','Безопасность'),('events','События')]]
 api(config,'setMyCommands',{'commands':commands,'scope':{'type':'chat','chat_id':owner_id(config)}})
 path=folder/'telegram-control-state.json';state=read_state(folder,path.name)
 while True:
  state.update(running_pid=os.getpid(),last_poll_at=now());atomic_json(path,state)
  updates,error=api(config,'getUpdates',{'offset':state.get('offset',0),'timeout':25,'allowed_updates':['message','callback_query']},timeout=32)
  if error:state['last_error']=error;atomic_json(path,state);time.sleep(5);continue
  state['last_error']=''
  for update in updates or []:
   old=state.get('offset',0);state=process_update(config,update,state,folder);atomic_json(path,state)
   if state.get('offset',0)==old:time.sleep(3);break
if __name__=='__main__':main()
