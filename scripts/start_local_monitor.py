"""Start only this localhost project and its independent private watchdog."""
import json,os,socket,subprocess,time,urllib.request
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];PYTHON=ROOT/'.venv/bin/python';FOLDER=ROOT/'.local-monitoring'
FOLDER.mkdir(exist_ok=True,mode=0o700);FOLDER.chmod(0o700)
cfg=json.loads((ROOT/'.local-monitoring.json').read_text())
def healthy():
 try:
  req=urllib.request.Request(cfg['health_url'],headers={'Authorization':'Bearer '+cfg['health_token']})
  with urllib.request.urlopen(req,timeout=2) as response:return bool(json.load(response).get('ok'))
 except Exception:return False
with socket.socket() as sock:occupied=sock.connect_ex(('127.0.0.1',8000))==0
if occupied and not healthy():raise SystemExit('Port8000 occupied by an unverified/unhealthy service; nothing replaced.')
if not occupied:
 log=FOLDER/'django.log';log.touch(mode=0o600,exist_ok=True);log.chmod(0o600)
 with log.open('a') as output:
  p=subprocess.Popen([str(PYTHON),'manage.py','runserver','127.0.0.1:8000'],cwd=ROOT,env=dict(os.environ,DJANGO_SETTINGS_MODULE='config.settings'),stdout=output,stderr=output,start_new_session=True)
 (FOLDER/'application-process.json').write_text(json.dumps({'pid':p.pid,'port':8000}));(FOLDER/'application-process.json').chmod(0o600)
 for _ in range(30):
  if healthy():break
  time.sleep(.2)
 if not healthy():raise SystemExit('Local app did not become healthy; inspect the private Django log.')
existing=False
try:
 state=json.loads((FOLDER/'watchdog-state.json').read_text());p=psutil.Process(state['running_pid'])
 existing=Path(p.cwd())==ROOT and str(ROOT/'scripts/watch_monitor.py') in p.cmdline()
except Exception:pass
if not existing:
 log=FOLDER/'watchdog.log';log.touch(mode=0o600,exist_ok=True);log.chmod(0o600)
 with log.open('a') as output:subprocess.Popen([str(PYTHON),str(ROOT/'scripts/watch_monitor.py')],cwd=ROOT,stdout=output,stderr=output,start_new_session=True)
print('Local app healthy on 127.0.0.1:8000; independent monitoring started.')
# Read-only Telegram controls run separately from request handling and watchdog.
config_now=json.loads((ROOT/'.local-monitoring.json').read_text())
if config_now.get('owner_user_id'):
 bot_running=False
 try:
  bot_state=json.loads((FOLDER/'telegram-control-state.json').read_text());bot_process=psutil.Process(bot_state['running_pid'])
  bot_running=Path(bot_process.cwd())==ROOT and str(ROOT/'scripts/telegram_control.py') in bot_process.cmdline()
 except Exception:pass
 if not bot_running:
  bot_log=FOLDER/'telegram-control.log';bot_log.touch(mode=0o600,exist_ok=True);bot_log.chmod(0o600)
  with bot_log.open('a') as output:subprocess.Popen([str(PYTHON),str(ROOT/'scripts/telegram_control.py')],cwd=ROOT,stdout=output,stderr=output,start_new_session=True)
 print('Owner-only Telegram control listener started or already running.')
