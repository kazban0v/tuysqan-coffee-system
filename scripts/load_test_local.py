"""Isolated HTTP workload. Never reads or writes the working business database.
Usage: .venv/bin/python scripts/load_test_local.py --output artifacts/load-before.json
A local laptop result is not a benchmark of a 2 GB Linux VPS.
"""
import argparse, concurrent.futures, http.client, json, os, random, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent


def serve(manifest_path, history_orders, sqlite_mode):
    sys.path.insert(0, str(ROOT))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
    from config import settings as cfg
    temp = Path(tempfile.mkdtemp(prefix='tuysqan-load-'))
    cfg.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(temp/'load.sqlite3'), 'OPTIONS': {**cfg.DATABASES['default'].get('OPTIONS', {}), 'timeout': 10, 'transaction_mode': sqlite_mode}}}
    cfg.SESSION_COOKIE_NAME = 'load_session'
    cfg.CSRF_COOKIE_NAME = 'load_csrf'
    cfg.SECRET_KEY = 'isolated-load-test-key-not-for-production'
    import django
    django.setup()
    import logging
    logging.getLogger('django.request').addHandler(logging.StreamHandler())
    from django.core.signals import got_request_exception
    import traceback
    def report_exception(sender, **kwargs): traceback.print_exc()
    got_request_exception.connect(report_exception, weak=False)
    from django.core.management import call_command
    call_command('migrate', verbosity=0)
    from django.contrib.auth.models import User, Group
    from django.test import Client
    from django.test.utils import CaptureQueriesContext
    from django.db import connection
    from django.utils import timezone
    from django.core.wsgi import get_wsgi_application
    from core.models import Table, MenuCategory, MenuItem, Customer, Order, OrderItem, Payment, AuditEvent, AppSettings, LoyaltyPolicy
    from uuid import uuid4
    from datetime import timedelta
    staff = {}
    for role in ['cashier', 'kitchen', 'owner']:
        user = User.objects.create(username='load-'+role)
        user.groups.add(Group.objects.create(name=role))
        staff[role] = user
    tables = [Table.objects.create(name=f'Стол {i}', is_test=False) for i in range(1, 9)]
    categories = [MenuCategory.objects.create(slug=f'load-{i}', name_ru=f'Категория {i}', name_kz=f'Санат {i}') for i in range(10)]
    MenuItem.objects.bulk_create([MenuItem(slug=f'load-{i}', category=categories[i%10], name_ru=f'Тестовая позиция {i}', name_kz=f'Тест {i}', kind='drink' if i%3==0 else 'food', price=1000+i*10, is_test=False) for i in range(126)])
    items = list(MenuItem.objects.all())
    guests = [Customer.objects.create(name=f'Тестовый гость {i}', phone=f'+7700100{i:04}', phone_verified_at=timezone.now(), consent_at=timezone.now(), is_test=False) for i in range(60)]
    now = timezone.now()
    Order.objects.bulk_create([Order(customer=guests[i%60], table=tables[i%8], status='accepted' if i>=history_orders-24 else 'served', payment_method='cash', subtotal=5000,total=5000,actual_paid=5000 if i<history_orders-24 else 0,payment_status='paid' if i<history_orders-24 else 'unpaid', paid_at=now if i<history_orders-24 else None, served_at=now if i<history_orders-24 else None,idempotency_key=str(uuid4()),payload_hash='load',is_test=False) for i in range(history_orders)])
    orders = list(Order.objects.order_by('pk'))
    Order.objects.exclude(pk__in=[order.pk for order in orders[-24:]]).update(created_at=now-timedelta(days=180))
    OrderItem.objects.bulk_create([OrderItem(order=order,menu_item=items[j],name_ru=items[j].name_ru,name_kz=items[j].name_kz,kind=items[j].kind,unit_price=items[j].price,quantity=1,status='pending' if order.status=='accepted' else 'ready') for order in orders for j in (1,2,3,6)])
    Payment.objects.bulk_create([Payment(order=o,amount=5000,method='cash',confirmed_by=staff['cashier'],idempotency_key=str(uuid4())) for o in orders[:-24]])
    AuditEvent.objects.bulk_create([AuditEvent(order=o,action='payment_confirmed',actor=staff['cashier'],before={'payment_status':'unpaid'},after={'payment_status':'paid'}) for o in orders[:-24]])
    AppSettings.get(); LoyaltyPolicy.get()
    clients = {}
    for role, user in staff.items():
        client=Client();client.force_login(user);client.get('/admin/cashier/' if role!='kitchen' else '/admin/kitchen/')
        clients[role] = client
    client=Client();session=client.session;session['customer_id']=orders[-1].customer_id;session['table_token']=tables[0].token();session.save();client.get('/account/')
    clients['guest']=client
    paths={'cashier':'/api/staff/orders/','kitchen':'/api/kitchen/','guest':f'/api/orders/{orders[-1].public_id}/','account':'/account/','menu':'/table/'+tables[0].token()+'/','admin':'/admin/'}
    query_counts={}
    for name, path in paths.items():
        c=clients.get(name, clients['guest'] if name in ['menu','account'] else clients['owner'])
        with CaptureQueriesContext(connection) as captured:
            response=c.get(path)
        if response.status_code!=200:raise RuntimeError(f'Fixture {name}: {response.status_code}')
        query_counts[name]=len(captured)
    cookies={name:'; '.join(f'{key}={value.value}' for key,value in c.cookies.items()) for name,c in clients.items()}
    from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
    from socketserver import ThreadingMixIn
    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads=True
    class Quiet(WSGIRequestHandler):
        def log_message(self,*args):pass
    connection.close()
    server=make_server('127.0.0.1',0,get_wsgi_application(),server_class=Server,handler_class=Quiet)
    manifest={'port':server.server_port,'cookies':cookies,'csrf':clients['cashier'].cookies['load_csrf'].value,'guest_csrf':clients['guest'].cookies['load_csrf'].value,'table_token':tables[0].token(),'paths':paths,'queries':query_counts,'item_id':items[1].pk,'fixture':{'orders':history_orders,'order_items':history_orders*4,'menu_items':126,'active_orders':24,'customers':60},'db':str(temp/'load.sqlite3')}
    manifest_path.write_text(json.dumps(manifest));manifest_path.chmod(0o600)
    orders.clear()
    import gc
    gc.collect()
    try:server.serve_forever()
    finally:
        import shutil
        server.server_close();shutil.rmtree(temp,ignore_errors=True)


def percentile(values,p):
    return round(sorted(values)[max(0, __import__('math').ceil(len(values)*p)-1)]*1000,1) if values else None


def run(output, duration, history_orders, sqlite_mode):
    with tempfile.TemporaryDirectory(prefix='tuysqan-load-driver-') as directory:
        manifest_path=Path(directory)/'manifest.json'
        with output.with_suffix('.server.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,__file__,'--serve',str(manifest_path),'--orders',str(history_orders),'--sqlite-mode',sqlite_mode],cwd=ROOT,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+60
                while not manifest_path.exists():
                    if proc.poll() is not None:raise RuntimeError('Fixture failed; see artifacts/load-server.log')
                    if time.monotonic()>deadline:raise TimeoutError('Fixture startup')
                    time.sleep(.1)
                manifest=json.loads(manifest_path.read_text());rng=random.Random(17)
                scenarios=['guest']*10+['qr']+['cashier']*2+['kitchen']*2+['menu']*2+['account']*2+['pos']
                def request(name):
                    import uuid
                    role='cashier' if name=='pos' else 'guest' if name in ['account','menu','guest','qr'] else name
                    headers={'Cookie':manifest['cookies'][role]}
                    path=manifest['paths'].get(name,'/api/staff/pos/');method='GET';body=None
                    if name in ('pos','qr'):
                        method='POST';headers.update({'Content-Type':'application/json','X-CSRFToken':manifest['csrf']})
                        payload={'fulfillment':'takeaway','payment_method':'cash','accept_order':True,'idempotency_key':str(uuid.uuid4()),'items':[{'id':manifest['item_id'],'quantity':1}]}
                        if name=='qr':
                            path='/api/orders/';payload['table_token']=manifest['table_token'];headers['X-CSRFToken']=manifest['guest_csrf']
                        body=json.dumps(payload)
                    start=time.perf_counter();conn=http.client.HTTPConnection('127.0.0.1',manifest['port'],timeout=25)
                    try:
                        conn.request(method,path,body,headers);response=conn.getresponse();payload=response.read()
                        return {'scenario':name,'seconds':time.perf_counter()-start,'status':response.status,'bytes':len(payload)}
                    except Exception as error:return {'scenario':name,'seconds':time.perf_counter()-start,'status':0,'error':str(error)}
                    finally:conn.close()
                stages=[];rss_peak=0
                with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                    for rate in [1,4,8]:
                        futures=[];started=time.monotonic()
                        for n in range(rate*duration):
                            wait=started+n/rate-time.monotonic()
                            if wait>0:time.sleep(wait)
                            futures.append(pool.submit(request,scenarios[rng.randrange(len(scenarios))]))
                            rss=int(subprocess.check_output(['ps','-o','rss=','-p',str(proc.pid)],text=True).strip() or 0)
                            rss_peak=max(rss_peak,rss)
                        rows=[f.result() for f in futures];elapsed=time.monotonic()-started
                        stages.append({'target_rps':rate,'requests':len(rows),'elapsed_seconds':round(elapsed,2),'achieved_rps':round(len(rows)/elapsed,2),'errors':sum(r['status'] not in (200,201) for r in rows),'p50_ms':percentile([r['seconds'] for r in rows],.5),'p95_ms':percentile([r['seconds'] for r in rows],.95),'p99_ms':percentile([r['seconds'] for r in rows],.99),'by_scenario':{name:{'requests':len(v),'p95_ms':percentile([r['seconds'] for r in v],.95),'errors':sum(r['status'] not in (200,201) for r in v)} for name in scenarios if (v:=[r for r in rows if r['scenario']==name])},'failures':[r for r in rows if r['status'] not in (200,201)]})
                        print(json.dumps(stages[-1],ensure_ascii=False),flush=True)
                # A short simultaneous-write burst checks contention separately from polling.
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                    burst=list(pool.map(request,['pos','qr']*8))
                report={'sqlite_transaction_mode':sqlite_mode,'write_burst':{'requests':len(burst),'errors':sum(r['status'] not in (200,201) for r in burst),'p95_ms':percentile([r['seconds'] for r in burst],.95),'failures':[r for r in burst if r['status'] not in (200,201)]},'database_bytes':Path(manifest['db']).stat().st_size,'environment':'Local macOS, threaded WSGI, SQLite, separate synthetic DB; not a 2-vCPU/2-GB VPS measurement','fixture':manifest['fixture'],'queries_per_request':manifest['queries'],'server_peak_rss_mb':round(rss_peak/1024,1),'stages':stages}
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                if manifest_path.exists():
                    import shutil
                    shutil.rmtree(Path(json.loads(manifest_path.read_text())['db']).parent,ignore_errors=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--serve',type=Path);parser.add_argument('--output',type=Path,default=ROOT/'artifacts/load-test.json');parser.add_argument('--duration',type=int,default=12);parser.add_argument('--orders',type=int,default=1000);parser.add_argument('--sqlite-mode',choices=['DEFERRED','IMMEDIATE'],default='IMMEDIATE')
    args=parser.parse_args()
    if args.serve:serve(args.serve,args.orders,args.sqlite_mode)
    else:run(args.output,args.duration,args.orders,args.sqlite_mode)
