"""Private local monitoring. Never includes secrets or customer data in alerts."""
import hashlib
import json
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
import psutil


def config():
    path=Path(getattr(settings,'MONITOR_CONFIG_PATH',settings.BASE_DIR/'.local-monitoring.json'))
    try:
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def state_dir():
    return Path(getattr(settings,'MONITOR_STATE_DIR',settings.BASE_DIR/'.local-monitoring'))


def events_dir():
    identity=connection.settings_dict['ENGINE']+':'+str(connection.settings_dict['NAME'])
    return state_dir()/hashlib.sha256(identity.encode()).hexdigest()[:16]


def record_request(request,status,elapsed):
    if status<500 and elapsed<2:return
    if getattr(request.resolver_match,'route','')=='internal/monitor-health/':return
    try:
        folder=events_dir();folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700)
        now=timezone.now();file=folder/(now.date().isoformat()+'.jsonl')
        if file.exists() and file.stat().st_size>1024*1024:return
        route=getattr(request.resolver_match,'route',None) or 'unresolved'
        entry={'at':now.isoformat(),'kind':'http_5xx' if status>=500 else 'slow','status':status,'milliseconds':round(elapsed*1000),'route':route[:180]}
        # One append-only write: no request body, query, IP, token or traceback.
        fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:os.write(fd,(json.dumps(entry,ensure_ascii=False)+'\n').encode())
        finally:os.close(fd)
    except Exception:pass  # Monitoring must not break an order.


class RequestMetricsMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        started=time.monotonic();response=self.get_response(request)
        record_request(request,response.status_code,time.monotonic()-started)
        return response


def recent_events():
    now=timezone.now();rows=[]
    for day in (now.date(),(now-timedelta(days=1)).date()):
        try:
            for line in (events_dir()/(day.isoformat()+'.jsonl')).read_text().splitlines():
                try:
                    item=json.loads(line);at=__import__('datetime').datetime.fromisoformat(item['at'])
                    if now-timedelta(hours=24)<=at<=now:rows.append(item)
                except (ValueError,KeyError,TypeError):continue
        except OSError:continue
    rows.sort(key=lambda r:r['at'],reverse=True)
    return rows


def server_snapshot(fresh=False):
    key='developer-host:'+str(os.getpid())
    cached=cache.get(key)
    if cached and not fresh:return cached
    now=timezone.now();memory=psutil.virtual_memory();disk=shutil.disk_usage(settings.BASE_DIR);process=psutil.Process()
    database={'ok':False,'milliseconds':None,'engine':connection.vendor,'size_bytes':None}
    started=time.monotonic()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM django_migrations LIMIT 1');cursor.fetchone()
            cursor.execute('SELECT 1 FROM core_order LIMIT 1');cursor.fetchone()
            if connection.vendor=='postgresql':cursor.execute('SELECT pg_database_size(current_database())');database['size_bytes']=cursor.fetchone()[0]
            elif connection.vendor=='sqlite':
                name=str(connection.settings_dict['NAME'])
                if name not in (':memory:','') and not name.startswith('file:memory'):database['size_bytes']=Path(name).stat().st_size
        database.update(ok=True,milliseconds=round((time.monotonic()-started)*1000,1))
    except Exception:database['error']='database_unavailable'
    rows=recent_events();cutoff=(now-timedelta(minutes=1)).isoformat()
    result={'checked_at':now.isoformat(),'cpu_percent':psutil.cpu_percent(interval=.05),'cpu_count':psutil.cpu_count(),'memory_percent':memory.percent,'memory_used_bytes':memory.total-memory.available,'memory_total_bytes':memory.total,'process_rss_bytes':process.memory_info().rss,'process_uptime_seconds':round(time.time()-process.create_time()),'disk_used_percent':round(disk.used/disk.total*100,1),'disk_free_bytes':disk.free,'database':database,'http_5xx_24h':sum(r['kind']=='http_5xx' for r in rows),'http_5xx_1m':sum(r['kind']=='http_5xx' and r['at']>=cutoff for r in rows),'slow_1m':sum(r['kind']=='slow' and r['at']>=cutoff for r in rows),'events':rows[:15]}
    cache.set(key,result,10)
    return result


def watchdog_snapshot():
    try:
        data=json.loads((state_dir()/'watchdog-state.json').read_text())
        # Explicit allowlist; never pass configuration/credentials into a template/API.
        return {k:data.get(k) for k in ('last_check_at','last_delivery_at','last_error','active_incidents','history','running_pid')}
    except (OSError,ValueError):return {}
