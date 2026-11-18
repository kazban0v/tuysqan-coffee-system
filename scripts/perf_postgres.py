"""Local PostgreSQL cluster + Gunicorn + measured HTTP workload.
No production settings, data, DNS or external services are used.
"""
import argparse, asyncio, json, os, secrets, shutil, socket, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path
import psutil, psycopg
from psycopg import sql
from perf_pg_load import Workload
ROOT=Path(__file__).resolve().parent.parent
RUN=ROOT/'artifacts/postgres-performance/run'
RESULTS=ROOT/'artifacts/postgres-performance'
PYTHON=ROOT/'.venv/bin/python'


def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def settings_env():
    return dict(os.environ,TUYSQAN_PERF_LOCAL='1',TUYSQAN_PERF_SECRETS=str(RUN/'secrets.json'),DJANGO_SETTINGS_MODULE='config.perf_settings')


def db_connect(secret, database=None):
    return psycopg.connect(host='127.0.0.1',port=secret['pg_port'],dbname=database or secret['database'],user=secret['user'],password=secret['password'],autocommit=True)


def setup():
    RUN.mkdir(parents=True,exist_ok=True);RUN.chmod(0o700)
    path=RUN/'secrets.json'
    if not path.exists():
        secret={'database':'tuysqan_perf_20261108','user':'tuysqan_perf_owner','password':secrets.token_urlsafe(32),'secret_key':secrets.token_urlsafe(48),'host':'127.0.0.1','pg_port':free_port(),'http_port':free_port()}
        path.write_text(json.dumps(secret));path.chmod(0o600)
    secret=json.loads(path.read_text())
    if 'socket_dir' not in secret:
        secret['socket_dir']=tempfile.mkdtemp(prefix='tuysqan-perf-sock-')
        path.write_text(json.dumps(secret));path.chmod(0o600)
    Path(secret['socket_dir']).mkdir(mode=0o700,exist_ok=True)
    if not (RUN/'data/PG_VERSION').exists():
        password_file=RUN/'init-password';password_file.write_text(secret['password']);password_file.chmod(0o600)
        try:subprocess.run(['initdb','-D',str(RUN/'data'),'-U',secret['user'],'--auth-local=trust','--auth-host=scram-sha-256','--pwfile='+str(password_file),'--encoding=UTF8','--locale=C'],check=True,stdout=(RUN/'init.log').open('w'),stderr=subprocess.STDOUT)
        finally:password_file.unlink(missing_ok=True)
    if subprocess.run(['pg_ctl','-D',str(RUN/'data'),'status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0:
        options=f"-h 127.0.0.1 -p {secret['pg_port']} -k {secret['socket_dir']} -c shared_buffers=128MB -c max_connections=32 -c work_mem=4MB -c maintenance_work_mem=64MB -c fsync=on -c synchronous_commit=on -c log_min_duration_statement=1000"
        subprocess.run(['pg_ctl','-D',str(RUN/'data'),'-l',str(RUN/'postgres.log'),'-o',options,'-w','start'],check=True)
    with db_connect(secret,'postgres') as conn:
        exists=conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(secret['database'],)).fetchone()
        if not exists:conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(secret['database'])))
    if not (RUN/'fixture.json').exists():
        subprocess.run([str(PYTHON),str(ROOT/'scripts/perf_pg_fixture.py'),'seed',str(RUN/'fixture.json')],env=settings_env(),cwd=ROOT,check=True)
    return secret


class Monitor:
    def __init__(self, roots):
        self.roots=roots;self.rows=[];self.stop_event=threading.Event();self.phase='warmup';self.previous={};self.last=time.monotonic();self.thread=threading.Thread(target=self.run,daemon=True)
    def run(self):
        while not self.stop_event.wait(1):
            now=time.monotonic();elapsed=now-self.last;self.last=now;procs={}
            for pid in self.roots:
                try:
                    root=psutil.Process(pid);procs[root.pid]=root
                    for p in root.children(recursive=True):procs[p.pid]=p
                except psutil.Error:pass
            rss=uss=cpu=0;count=0
            for pid,p in procs.items():
                try:
                    value=p.cpu_times();total=value.user+value.system;before=self.previous.get(pid,total);self.previous[pid]=total;cpu+=max(0,total-before)/elapsed*100
                    rss+=p.memory_info().rss
                    try:uss+=p.memory_full_info().uss
                    except (psutil.Error,AttributeError):pass
                    count+=1
                except psutil.Error:pass
            self.rows.append({'phase':self.phase,'seconds':round(time.monotonic(),3),'cpu_percent_one_core':round(cpu,2),'rss_sum_mb':round(rss/1024**2,2),'uss_sum_mb':round(uss/1024**2,2),'processes':count})
    def summary(self,phase=None):
        rows=[r for r in self.rows if phase is None or r['phase']==phase]
        return {'samples':len(rows),'cpu_mean_percent_one_core':round(statistics.mean(r['cpu_percent_one_core'] for r in rows),2) if rows else None,'cpu_peak_percent_one_core':max((r['cpu_percent_one_core'] for r in rows),default=None),'rss_mean_mb':round(statistics.mean(r['rss_sum_mb'] for r in rows),2) if rows else None,'rss_peak_mb':max((r['rss_sum_mb'] for r in rows),default=None),'uss_peak_mb':max((r['uss_sum_mb'] for r in rows),default=None) or None}
    def start(self):self.thread.start()
    def stop(self):self.stop_event.set();self.thread.join()


def stop_pg():
    if (RUN/'data/PG_VERSION').exists():subprocess.run(['pg_ctl','-D',str(RUN/'data'),'-m','fast','-w','stop'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


async def benchmark(secret,duration,counts,output):
    fixture=json.loads((RUN/'fixture.json').read_text())
    cmd=[str(PYTHON),'-m','gunicorn','config.wsgi:application','--bind',f"127.0.0.1:{secret['http_port']}",'--workers','2','--threads','2','--worker-class','gthread','--timeout','30','--keep-alive','5','--max-requests','10000','--max-requests-jitter','1000','--error-logfile',str(RUN/'gunicorn.log'),'--capture-output','--pid',str(RUN/'gunicorn.pid')]
    pg_pid=int((RUN/'data/postmaster.pid').read_text().splitlines()[0])
    gunicorn=subprocess.Popen(cmd,cwd=ROOT,env=settings_env(),stdout=(RUN/'gunicorn-stdout.log').open('w'),stderr=subprocess.STDOUT)
    baseline=json.loads(subprocess.check_output([str(PYTHON),str(ROOT/'scripts/perf_pg_fixture.py'),'counts'],env=settings_env(),cwd=ROOT,text=True))
    monitor=Monitor([pg_pid,gunicorn.pid]);work=Workload(f"http://127.0.0.1:{secret['http_port']}",fixture)
    try:
        import httpx
        deadline=time.monotonic()+30
        async with httpx.AsyncClient(trust_env=False) as client:
            while True:
                if gunicorn.poll() is not None:raise RuntimeError('Gunicorn failed; inspect run/gunicorn.log')
                try:
                    response=await client.get(work.base+'/')
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                if time.monotonic()>deadline:raise TimeoutError('Gunicorn startup')
                await asyncio.sleep(.2)
        monitor.start();phases=[]
        for count in counts:
            monitor.phase=f'clients-{count}';phase=await work.phase(count,duration);phase['resources']=monitor.summary(monitor.phase);phases.append(phase)
            (RESULTS/'progress.json').write_text(json.dumps(phases,ensure_ascii=False,indent=2))
        monitor.phase='concurrent-writes';bursts=await work.bursts()
        expectations=RUN/'expected.json';expectations.write_text(json.dumps(work.expected));expectations.chmod(0o600)
        check=subprocess.check_output([str(PYTHON),str(ROOT/'scripts/perf_pg_fixture.py'),'check',str(expectations)],env=settings_env(),cwd=ROOT,text=True)
        integrity=json.loads(check)
        integrity['orders_created_this_run']=integrity['orders_created_since_fixture']-baseline['orders_created_since_fixture']
        integrity['unaccounted_orders_this_run']=integrity['orders_created_this_run']-integrity['expected_unique_orders']
        integrity['payments_created_this_run']=integrity['payments_created_since_fixture']-baseline['payments_created_since_fixture']
        report={'environment':{'os':sys.platform,'architecture':os.uname().machine,'host_logical_cpus':psutil.cpu_count(),'host_ram_mb':round(psutil.virtual_memory().total/1024**2),'gunicorn_workers':2,'threads_per_worker':2,'postgresql':subprocess.check_output(['postgres','--version'],text=True).strip(),'postgres_shared_buffers_mb':128,'postgres_max_connections':32,'hard_cpu_limit':False,'hard_ram_limit':False,'limitations':'Native macOS; no container/VM runtime installed. Two workers are not a hard 2-vCPU cap. RSS sums overcount shared PostgreSQL pages; USS excludes shared buffers. HTTP loopback, no TLS/proxy/browser asset fetching; not a full Linux VPS test.','workload':'100 max independent phone-first sessions, one QR order/client/stage, polling every 3s (4x production frequency), staff queues every 2s (5x), full kitchen/bar/payment/served lifecycle; PostgreSQL durable commits enabled.'},'fixture':{k:v for k,v in fixture.items() if k.startswith('history_')},'phases':phases,'bursts':bursts,'integrity':integrity,'resources_all':monitor.summary(),'write_resources':monitor.summary('concurrent-writes'),'raw_samples_file':output.stem+'-resources.json','raw_requests_file':output.stem+'-requests.json'}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        output.with_name(output.stem+'-resources.json').write_text(json.dumps(monitor.rows,indent=2)+'\n')
        output.with_name(output.stem+'-requests.json').write_text(json.dumps(work.rows,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'result':str(output),'integrity':integrity,'resources':report['resources_all'],'bursts':bursts},ensure_ascii=False),flush=True)
    finally:
        monitor.stop_event.set()
        if monitor.thread.is_alive():monitor.stop()
        gunicorn.terminate()
        try:gunicorn.wait(timeout=15)
        except subprocess.TimeoutExpired:gunicorn.kill();gunicorn.wait()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--duration',type=int,default=40);parser.add_argument('--clients',default='10,30,50,100');parser.add_argument('--output',type=Path,default=RESULTS/'postgres-gunicorn.json');parser.add_argument('--stop',action='store_true');parser.add_argument('--init-only',action='store_true');args=parser.parse_args()
    if args.stop:stop_pg();sys.exit(0)
    secret=setup()
    if args.init_only:print('Dedicated local PostgreSQL fixture prepared.');sys.exit(0)
    try:asyncio.run(benchmark(secret,args.duration,[int(x) for x in args.clients.split(',')],args.output))
    finally:stop_pg()
