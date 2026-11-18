"""Closed-loop authenticated HTTP clients; all identities belong to synthetic fixture."""
import asyncio, collections, json, math, time, uuid
import httpx


def stats(rows,elapsed):
    values=sorted(row['ms'] for row in rows)
    def pct(p):return round(values[max(0,math.ceil(len(values)*p)-1)],2) if values else None
    failed=[row for row in rows if not row['ok']]
    return {'requests':len(rows),'rps':round(len(rows)/elapsed,2),'p95_ms':pct(.95),'p99_ms':pct(.99),'errors':len(failed),'error_percent':round(100*len(failed)/max(1,len(rows)),3),'statuses':dict(collections.Counter(str(r['status']) for r in rows)),'failure_examples':failed[:12]}


class Workload:
    def __init__(self,base,fixture):
        self.base=base;self.fixture=fixture;self.rows=[];self.expected=[];self.stage='setup';self.logic_errors=[]
    def client(self,identity):
        return httpx.AsyncClient(base_url=self.base,headers={'Cookie':identity['cookie'],'X-CSRFToken':identity['csrf']},timeout=30,limits=httpx.Limits(max_connections=128,max_keepalive_connections=20),trust_env=False)
    async def request(self,client,method,path,payload=None,label=''):
        started=time.perf_counter()
        try:
            response=await client.request(method,path,json=payload) if payload is not None else await client.request(method,path)
            status=response.status_code
            try:data=response.json()
            except ValueError:data={}
            row={'stage':self.stage,'label':label or path.split('?')[0],'ms':(time.perf_counter()-started)*1000,'status':status,'ok':status in (200,201)}
            if not row['ok']:row['detail']=str(data.get('error',''))[:180]
            self.rows.append(row)
            return data if row['ok'] else None
        except Exception as error:
            self.rows.append({'stage':self.stage,'label':label,'ms':(time.perf_counter()-started)*1000,'status':0,'ok':False,'detail':type(error).__name__})
            return None
    def qr_payload(self,identity,key,offer=None):
        payload={'idempotency_key':key,'table_token':identity['table_token'],'payment_method':'cash','drink_preference':'immediately','items':[{'id':self.fixture['food_id'],'quantity':1},{'id':self.fixture['drink_id'],'quantity':1}]}
        if offer:payload.update(discount_choice=False,discount_offer_token=offer['token'])
        return payload
    def expectation(self,result,key,identity=None,paid=False,status=None):
        if not result or 'order' not in result:return None
        o=result['order']
        final_key='claim:'+identity['scope']+':'+key if identity else key
        entry={'key':final_key,'public_id':o['public_id'],'paid':paid,'status':status}
        self.expected.append(entry);return entry
    async def phase(self,count,duration):
        self.stage=f'clients-{count}';rows_start=len(self.rows);started=time.perf_counter();until=started+duration
        queue=asyncio.Queue();staff=self.fixture['staff']
        async def lifecycle():
            async with self.client(staff['cashier']) as cashier,self.client(staff['kitchen']) as kitchen:
                while True:
                    job=await queue.get()
                    try:
                        if job is None:return
                        order,entry=job;path=f"/api/staff/orders/{order['public_id']}/action/"
                        result=await self.request(cashier,'POST',path,{'action':'accept_and_pay','amount':order['total'],'cash_received':'5000','payment_method':'cash','idempotency_key':'life-pay-'+str(uuid.uuid4())},'cashier-accept-pay')
                        if not result:continue
                        entry['paid']=True
                        if not await self.request(kitchen,'POST',path,{'action':'food_eta','eta':10},'kitchen-food-time'):continue
                        if not await self.request(cashier,'POST',path,{'action':'drink_eta','eta':5},'cashier-drink-time'):continue
                        food_id=next(i['id'] for i in order['items'] if i['kind']=='food')
                        if not await self.request(kitchen,'POST',path,{'action':'item_ready','item_id':food_id},'kitchen-ready'):continue
                        if not await self.request(cashier,'POST',path,{'action':'drinks_ready'},'bar-ready'):continue
                        if not await self.request(cashier,'POST',path,{'action':'ready'},'cashier-ready'):continue
                        if await self.request(cashier,'POST',path,{'action':'serve'},'cashier-served'):entry['status']='served'
                    finally:queue.task_done()
        async def poll_staff(role,path):
            async with self.client(staff[role]) as client:
                while time.perf_counter()<until:
                    await self.request(client,'GET',path,label=role+'-queue')
                    await asyncio.sleep(min(2,max(0,until-time.perf_counter())))
        async def guest(index):
            identity=self.fixture['guests'][index]
            async with self.client(identity) as client:
                await asyncio.sleep(index/count*.5)
                await self.request(client,'GET','/table/'+identity['table_token']+'/',label='qr-menu')
                offer=await self.request(client,'GET','/api/account/discount-offer/',label='discount-offer')
                key=f'vu-{count}-{index}-'+str(uuid.uuid4())
                result=await self.request(client,'POST','/api/orders/',self.qr_payload(identity,key,offer),'qr-create')
                entry=self.expectation(result,key,identity)
                if not entry:return
                await queue.put((result['order'],entry));cycle=0
                while time.perf_counter()<until:
                    await self.request(client,'GET',f"/api/orders/{entry['public_id']}/",label='guest-status')
                    if cycle%4==0:await self.request(client,'GET','/account/',label='guest-account')
                    cycle+=1
                    await asyncio.sleep(min(3,max(0,until-time.perf_counter())))
        workers=[asyncio.create_task(lifecycle()) for _ in range(4)]
        await asyncio.gather(*(guest(i) for i in range(count)),poll_staff('cashier','/api/staff/orders/'),poll_staff('kitchen','/api/kitchen/'))
        await queue.join()
        for _ in workers:await queue.put(None)
        await asyncio.gather(*workers)
        elapsed=time.perf_counter()-started;rows=self.rows[rows_start:]
        report={'clients':count,'duration_seconds':round(elapsed,2),**stats(rows,elapsed),'by_operation':{name:stats([r for r in rows if r['label']==name],elapsed) for name in sorted({r['label'] for r in rows})}}
        print(json.dumps({k:v for k,v in report.items() if k!='by_operation'}),flush=True)
        return report
    async def bursts(self):
        self.stage='concurrent-writes';reports=[]
        staff=self.fixture['staff']['cashier']
        async with self.client(staff) as cashier:
            for count in [16,50,100]:
                start=len(self.rows);began=time.perf_counter()
                async def create(index):
                    key=f'burst-{count}-{index}-'+str(uuid.uuid4())
                    if index%2:
                        identity=self.fixture['guests'][index%100]
                        async with self.client(identity) as guest:
                            offer=await self.request(guest,'GET','/api/account/discount-offer/',label='burst-offer')
                            result=await self.request(guest,'POST','/api/orders/',self.qr_payload(identity,key,offer),'burst-qr-create')
                            self.expectation(result,key,identity)
                    else:
                        payload={'idempotency_key':key,'fulfillment':'takeaway','payment_method':'cash','accept_order':True,'items':[{'id':self.fixture['food_id'],'quantity':1}]}
                        result=await self.request(cashier,'POST','/api/staff/pos/',payload,'burst-pos-create')
                        self.expectation(result,f"pos:{self.fixture['cashier_id']}:{key}")
                await asyncio.gather(*(create(i) for i in range(count)))
                reports.append({'kind':'unique-orders','concurrent_saves':count,**stats(self.rows[start:],time.perf_counter()-began)})
            # Identical requests race on exactly the same key, then retry once after contention.
            identity=self.fixture['guests'][99]
            async with self.client(identity) as guest:
                offer=await self.request(guest,'GET','/api/account/discount-offer/',label='retry-offer')
                key='same-qr-'+str(uuid.uuid4());payload=self.qr_payload(identity,key,offer)
                start=len(self.rows);began=time.perf_counter()
                replies=await asyncio.gather(*(self.request(guest,'POST','/api/orders/',payload,'same-key-qr') for _ in range(16)))
                retry=await self.request(guest,'POST','/api/orders/',payload,'same-key-qr-retry')
                self.expectation(retry,key,identity)
                ids={r['order']['public_id'] for r in replies if r and 'order' in r}
                reports.append({'kind':'same-key-qr','distinct_response_order_ids':len(ids),'retry_ok':bool(retry),**stats(self.rows[start:],time.perf_counter()-began)})
            key='same-pos-'+str(uuid.uuid4());payload={'idempotency_key':key,'fulfillment':'takeaway','payment_method':'cash','accept_order':True,'items':[{'id':self.fixture['food_id'],'quantity':1}]}
            start=len(self.rows);began=time.perf_counter()
            replies=await asyncio.gather(*(self.request(cashier,'POST','/api/staff/pos/',payload,'same-key-pos') for _ in range(16)))
            retry=await self.request(cashier,'POST','/api/staff/pos/',payload,'same-key-pos-retry')
            self.expectation(retry,f"pos:{self.fixture['cashier_id']}:{key}")
            ids={r['order']['public_id'] for r in replies if r and 'order' in r}
            reports.append({'kind':'same-key-pos','distinct_response_order_ids':len(ids),'retry_ok':bool(retry),**stats(self.rows[start:],time.perf_counter()-began)})
            # Payment retries on the same accepted order with one payment key.
            if retry:
                o=retry['order'];key='same-payment-'+str(uuid.uuid4());path=f"/api/staff/orders/{o['public_id']}/action/"
                payment={'action':'pay','amount':o['total'],'cash_received':'5000','payment_method':'cash','idempotency_key':key}
                start=len(self.rows);began=time.perf_counter()
                replies=await asyncio.gather(*(self.request(cashier,'POST',path,payment,'same-key-payment') for _ in range(16)))
                reports.append({'kind':'same-key-payment',**stats(self.rows[start:],time.perf_counter()-began)})
                if any(replies):self.expected[-1]['paid']=True
                # Conflicting payment must be rejected and must not change already paid facts.
                bad=await cashier.post(path,json={**payment,'amount':'1','idempotency_key':'bad-'+str(uuid.uuid4())})
                reports.append({'kind':'conflicting-payment','status':bad.status_code,'rejected':bad.status_code==400})
        return reports
