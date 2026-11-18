#!/usr/bin/env python3
"""Linux journal observer. Never changes SSH/PAM settings or runs login commands."""
import argparse,fcntl,hashlib,ipaddress,json,os,re,selectors,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
from telegram_control import api,atomic_json,now,owner_id,read_state
ROOT=Path(__file__).resolve().parents[1]
ACCEPTED=re.compile(r'^Accepted (password|publickey|keyboard-interactive(?:/pam)?) for ([A-Za-z0-9_.@-]{1,64}) from ([0-9a-fA-F:.]+) port ([0-9]{1,5})(?: |$)')
FAILED=re.compile(r'^Failed (password|publickey|keyboard-interactive(?:/pam)?) for (?:invalid user )?([A-Za-z0-9_.@-]{1,64}) from ([0-9a-fA-F:.]+) port ([0-9]{1,5})(?: |$)')

def parse_entry(entry):
 if entry.get('SYSLOG_IDENTIFIER') not in ('sshd','sshd-session') and entry.get('_COMM') not in ('sshd','sshd-session'):return None
 message=entry.get('MESSAGE','')
 if not isinstance(message,str) or len(message)>4096:return None
 match=ACCEPTED.match(message);kind='ssh_success'
 if not match:match=FAILED.match(message);kind='ssh_failure'
 if not match:return None
 method,user,raw_ip,port=match.groups()
 try:ip=str(ipaddress.ip_address(raw_ip));port=int(port)
 except (ValueError,TypeError):return None
 if not 1<=port<=65535:return None
 try:at=datetime.fromtimestamp(int(entry['__REALTIME_TIMESTAMP'])/1000000,timezone.utc).isoformat()
 except (ValueError,TypeError,KeyError,OverflowError):return None
 cursor=entry.get('__CURSOR','')
 if not isinstance(cursor,str) or not cursor or len(cursor)>2048:return None
 return {'id':hashlib.sha256(cursor.encode()).hexdigest(),'kind':kind,'user':user,'ip':ip,'method':method,'port':port,'at':at}

def consume(entry,state,epoch=None):
 epoch=time.time() if epoch is None else epoch
 cursor=entry.get('__CURSOR');event=parse_entry(entry)
 if not event:
  if isinstance(cursor,str) and len(cursor)<=2048:state['cursor']=cursor
  return state
 if event['id'] in state.get('seen',[]):return state
 # Don't acknowledge the source cursor if the persistent delivery queue is full.
 if len(state.get('pending',[]))>=200:raise RuntimeError('security_queue_full')
 state['seen']=(state.get('seen',[])+[event['id']])[-512:]
 state['history']=([event]+state.get('history',[]))[:30]
 if event['kind']=='ssh_success':
  title='УСПЕШНЫЙ SSH-ВХОД ROOT' if event['user']=='root' else 'Успешная SSH-аутентификация'
  event['text']=f"Tuysqan · {title}\nПользователь: {event['user']}\nIP: {event['ip']}\nМетод: {event['method']}\nВремя UTC: {event['at']}\nЕсли это не вы — проверьте доступ к серверу."
  state.setdefault('pending',[]).append(event.copy())
 else:
  buckets={k:v for k,v in state.get('failures',{}).items() if v.get('at',0)>=epoch-300}
  # Bound attacker-controlled keys and group attempts rather than sending every failure.
  key=event['ip'];bucket=buckets.get(key,{'at':epoch,'times':[]});bucket['times']=([t for t in bucket.get('times',[]) if t>=epoch-300]+[epoch])[-200:];bucket['count']=len(bucket['times']);bucket['at']=epoch;buckets[key]=bucket
  state['failures']=dict(list(buckets.items())[-200:])
  if bucket['count']>=3 and epoch-state.get('last_failure_alert',0)>=60:
   alert={**event,'text':f"Tuysqan · Неудачные SSH-попытки\nIP: {event['ip']}\nПопыток за последние 5 минут (группа): {bucket['count']}\nПоследний пользователь: {event['user']}\nЭто не подтверждение успешного входа.\nUTC: {event['at']}"}
   state.setdefault('pending',[]).append(alert);state['last_failure_alert']=epoch;bucket['count']=0;bucket['times']=[]
 state['cursor']=cursor
 return state

def flush(config,state):
 for event in list(state.get('pending',[])):
  _,error=api(config,'sendMessage',{'chat_id':owner_id(config),'text':event['text'],'protect_content':True,
                'reply_markup':{'inline_keyboard':[[{'text':'Безопасность','callback_data':'security'}]]}})
  if error:state['last_error']=error;break
  state['pending'].remove(event);state['last_delivery_at']=now();state['last_error']=''
 return state

def journal_command(state):
 command=['/usr/bin/journalctl','--follow','--output=json','--no-pager','--unit=ssh.service','--unit=sshd.service']
 return command+(['--after-cursor='+state['cursor']] if state.get('cursor') else ['--lines=0'])

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=ROOT/'.local-monitoring.json');parser.add_argument('--fixture',type=Path);parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
 if args.fixture:
  if not args.dry_run:raise SystemExit('Fixture mode requires --dry-run; no notifications sent')
  state={}
  for line in args.fixture.read_text().splitlines():state=consume(json.loads(line),state)
  print(json.dumps({'events':len(state.get('history',[])),'alerts':len(state.get('pending',[])),'root_logins':sum(e['kind']=='ssh_success' and e['user']=='root' for e in state.get('history',[]))}));return
 if os.name!='posix' or not Path('/usr/bin/journalctl').exists():raise SystemExit('Linux systemd journal required; host configuration unchanged')
 config=json.loads(args.config.read_text())
 if not owner_id(config) or str(owner_id(config))!=str(config.get('chat_id')):raise SystemExit('Explicit personal owner ID required')
 folder=Path(config['state_dir']);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
 lock=(folder/'ssh-security.lock').open('a');os.chmod(folder/'ssh-security.lock',0o600)
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('SSH observer already running')
 path=folder/'ssh-state.json';state=read_state(folder,path.name)
 while True:
  process=subprocess.Popen(journal_command(state),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,bufsize=0)
  selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ);last_flush=0;buffer=b''
  try:
   while process.poll() is None:
    for key,_ in selector.select(timeout=1):
     chunk=os.read(key.fileobj.fileno(),65536)
     if not chunk:continue
     buffer+=chunk
     while b'\n' in buffer:
      line,buffer=buffer.split(b'\n',1)
      try:entry=json.loads(line)
      except (ValueError,TypeError):continue
      state=consume(entry,state);atomic_json(path,state) # Persist queue and cursor before sending.
     if len(buffer)>1048576:raise RuntimeError('journal_line_too_large')
    if time.monotonic()-last_flush>=5:
     state=flush(config,state);state.update(last_check_at=now(),source='systemd-journal',journal_running=True,running_pid=os.getpid());atomic_json(path,state);last_flush=time.monotonic()
  except RuntimeError:
   state['last_error']='security_queue_full'
  finally:
   selector.close()
   if process.poll() is None:process.terminate()
   process.wait(timeout=5)
   state['journal_running']=False;atomic_json(path,state)
  # Invalid cursor / journal access failure is visible, never silently drops history.
  state=flush(config,state);state['last_error']=state.get('last_error') or 'journal_stream_stopped';atomic_json(path,state);time.sleep(5)
if __name__=='__main__':main()
