"""Seed/check ONLY the PostgreSQL fixture selected by guarded perf_settings."""
import json, os, sys
from pathlib import Path
from decimal import Decimal
from datetime import timedelta
from uuid import uuid4
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));os.environ['DJANGO_SETTINGS_MODULE']='config.perf_settings'
import django
django.setup()
from django.db import connection
from django.test import Client
from django.core.management import call_command
from django.utils import timezone
from django.contrib.auth.models import User,Group
from django.db.models import Sum,Count,F
from core.models import *
from core import services


def seed(manifest_path):
    call_command('migrate',verbosity=0)
    if Order.objects.exists(): raise RuntimeError('Fixture is not empty; create a new isolated database')
    users={}
    for role in ['owner','cashier','kitchen']:
        user=User.objects.create(username='perf-'+role);user.groups.add(Group.objects.get_or_create(name=role)[0]);users[role]=user
    tables=[Table.objects.create(name=f'Стол {i}',is_test=False) for i in range(1,9)]
    cats=[MenuCategory.objects.create(slug=f'perf-{i}',name_ru=f'Тест {i}',name_kz=f'Тест {i}') for i in range(10)]
    MenuItem.objects.bulk_create([MenuItem(slug=f'perf-{i}',category=cats[i%10],kind='drink' if i%3==0 else 'food',name_ru=f'Тестовая позиция {i}',name_kz=f'Тест {i}',price=750 if i%3==0 else 1250,is_test=False) for i in range(126)])
    food=MenuItem.objects.filter(kind='food').first();drink=MenuItem.objects.filter(kind='drink').first()
    guests=Customer.objects.bulk_create([Customer(name=f'Тестовый гость {i}',phone=f'+770020{i:05}',phone_verified_at=timezone.now(),consent_at=timezone.now(),is_test=False) for i in range(2000)])
    orders=[]
    for i in range(36500):
        orders.append(Order(customer=guests[i%2000],table=tables[i%8],source='web',status='served',payment_status='paid',payment_method='cash',total=3250,subtotal=3250,actual_paid=3250,paid_at=timezone.now()-timedelta(days=1+i%365),served_at=timezone.now()-timedelta(days=1+i%365),idempotency_key='history-'+str(uuid4()),payload_hash='isolated-history',is_test=False))
    Order.objects.bulk_create(orders,batch_size=1000)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE core_order SET created_at = CURRENT_TIMESTAMP - ((id % 365 + 1) * INTERVAL '1 day')")
    lines=[]
    for o in orders:
        lines.extend([OrderItem(order=o,menu_item=food,name_ru=food.name_ru,name_kz=food.name_kz,kind='food',unit_price=1250,quantity=2,status='ready'),OrderItem(order=o,menu_item=drink,name_ru=drink.name_ru,name_kz=drink.name_kz,kind='drink',unit_price=750,quantity=1,status='ready')])
    OrderItem.objects.bulk_create(lines,batch_size=1000)
    payments=Payment.objects.bulk_create([Payment(order=o,amount=3250,method='cash',confirmed_by=users['cashier'],idempotency_key='history-pay-'+str(uuid4())) for o in orders],batch_size=1000)
    LoyaltyEntry.objects.bulk_create([LoyaltyEntry(customer_id=p.order.customer_id,order_id=p.order_id,payment=p,amount=3250,kind='purchase') for p in payments],batch_size=1000)
    events=[]
    for o,p in zip(orders,payments):
        events.extend([AuditEvent(order=o,actor=users['cashier'],action='accept',before={'status':'new'},after={'status':'accepted'}),AuditEvent(order=o,actor=users['cashier'],action='payment_confirmed',before={'payment_status':'unpaid'},after={'payment_id':p.pk,'payment_status':'paid','cash_received':'5000.00','change':'1750.00'}),AuditEvent(order=o,actor=users['cashier'],action='serve',before={'status':'ready'},after={'status':'served'})])
    AuditEvent.objects.bulk_create(events,batch_size=1000)
    policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
    AppSettings.get()
    # Dedicated customers use the actual phone-first, unverified QR flow, without SMS.
    live=Customer.objects.bulk_create([Customer(name=f'QR тест {i}',phone=f'+770030{i:05}',consent_at=timezone.now(),is_test=False) for i in range(100)])
    sessions=[]
    for i,guest in enumerate(live):
        client=Client();session=client.session
        session['claim_customer_id']=guest.pk;session['claim_order_scope']=str(uuid4());session['claim_order_ids']=[];session['table_token']=tables[i%8].token();session.save()
        response=client.get('/account/')
        if response.status_code!=200:raise RuntimeError('Invalid guest fixture')
        sessions.append({'customer_id':guest.pk,'scope':session['claim_order_scope'],'cookie':'; '.join(f'{k}={v.value}' for k,v in client.cookies.items()),'csrf':client.cookies['tuysqan_perf_csrf'].value,'table_token':tables[i%8].token()})
    staff={}
    for role,user in users.items():
        client=Client();client.force_login(user);client.get('/admin/kitchen/' if role=='kitchen' else '/admin/cashier/')
        staff[role]={'cookie':'; '.join(f'{k}={v.value}' for k,v in client.cookies.items()),'csrf':client.cookies['tuysqan_perf_csrf'].value}
    # Pre-create common walk-in identity so contention tests measure orders, not first-time setup.
    Customer.objects.create(phone='pos-walk-in',name='Гость кассы',consent_at=timezone.now(),is_test=False)
    with connection.cursor() as cursor:cursor.execute('ANALYZE')
    manifest={'guests':sessions,'staff':staff,'cashier_id':users['cashier'].pk,'food_id':food.pk,'drink_id':drink.pk,'history_orders':36500,'history_items':73000,'history_payments':36500,'history_events':109500,'max_history_id':orders[-1].pk}
    manifest_path.write_text(json.dumps(manifest));manifest_path.chmod(0o600)
    print(json.dumps({k:v for k,v in manifest.items() if k.startswith('history_')}),flush=True)


def check(expect_path):
    expected=json.loads(expect_path.read_text())
    result={}
    failures=[]
    for entry in expected:
        q=Order.objects.filter(pk__gt=36500,idempotency_key=entry['key'])
        count=q.count()
        if count!=1:
            failures.append({'key':entry['key'],'problem':'order_count','actual':count});continue
        order=q.first()
        computed=sum(i.line_total for i in order.items.all())
        if order.subtotal!=computed or order.total!=computed-order.discount_amount:failures.append({'key':entry['key'],'problem':'total'})
        if entry.get('paid'):
            payments=list(order.payments.filter(reversed_at=None))
            if len(payments)!=1 or order.payment_status!='paid' or order.actual_paid!=order.total or payments[0].amount!=order.total:failures.append({'key':entry['key'],'problem':'payment'})
        elif order.payments.exists() or order.actual_paid!=0:failures.append({'key':entry['key'],'problem':'unexpected_payment'})
        if entry.get('status') and order.status!=entry['status']:failures.append({'key':entry['key'],'problem':'status','actual':order.status})
        if not order.events.filter(action='order_created').exists():failures.append({'key':entry['key'],'problem':'missing_audit'})
        if order.notifications.filter(kind='new_order').count()!=1:failures.append({'key':entry['key'],'problem':'outbox_count'})
        if order.events.filter(action='order_created').count()!=1:failures.append({'key':entry['key'],'problem':'duplicate_creation_audit'})
        if entry.get('paid'):
            facts=services.payment_cash_facts(order)
            if Decimal(facts['cash_received'])!=5000 or Decimal(facts['change'])!=5000-order.total:failures.append({'key':entry['key'],'problem':'cash_change'})
            if order.customer.phone!='pos-walk-in' and LoyaltyEntry.objects.filter(payment__order=order,kind='purchase').count()!=1:failures.append({'key':entry['key'],'problem':'loyalty_count'})
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_database_size(current_database())');size=cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()");connections=cursor.fetchone()[0]
    result={'expected_unique_orders':len(expected),'failures':failures,'database_bytes':size,'connections':connections,'orders_created_since_fixture':Order.objects.filter(pk__gt=36500).count(),'payments_created_since_fixture':Payment.objects.exclude(idempotency_key__startswith='history-pay-').count(),'duplicate_order_groups':list(Order.objects.values('customer_id','idempotency_key').annotate(n=Count('pk')).filter(n__gt=1)),'duplicate_payments':list(Payment.objects.values('idempotency_key').annotate(n=Count('pk')).filter(n__gt=1))}
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='seed':seed(Path(sys.argv[2]))
    elif sys.argv[1]=='check':check(Path(sys.argv[2]))
    elif sys.argv[1]=='counts':print(json.dumps({'orders_created_since_fixture':Order.objects.filter(pk__gt=36500).count(),'payments_created_since_fixture':Payment.objects.exclude(idempotency_key__startswith='history-pay-').count()}))
