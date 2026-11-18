"""Authoritative transactional operations shared by web, POS and local Telegram."""
import hashlib
import json
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction, IntegrityError
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import *
from .preparation import drink_plan,food_plan

ETA_CHOICES=(5,10,15,20,25,30)
TERMINAL={'served','rejected','cancelled'}
ROLES={'owner','manager','cashier','kitchen'}

def role_of(user):
    if not user or not user.is_authenticated or not user.is_active: return ''
    if user.is_superuser: return 'owner'
    names=set(user.groups.values_list('name',flat=True))
    return next((r for r in ['owner','manager','cashier','kitchen'] if r in names),'')

def require_role(user,roles):
    if role_of(user) not in roles: raise PermissionDenied('Недостаточно прав / Рұқсат жоқ')

def audit(action,actor=None,order=None,reason='',before=None,after=None,channel='web',customer=None):
    return AuditEvent.objects.create(action=action,actor=actor if actor and actor.is_authenticated else None,order=order,reason=reason,before=before or {},after=after or {},channel=channel,customer=customer)

def money(value):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or result<0 or result>Decimal('999999999'): raise ValueError()
        if result!=result.quantize(Decimal('.01')): raise ValueError()
        return result.quantize(Decimal('.01'))
    except (InvalidOperation,ValueError,TypeError): raise ValidationError('Некорректная сумма / Сома қате')

def bounded_text(value,limit=500):
    if not isinstance(value,str) or len(value)>limit: raise ValidationError('Текст слишком длинный или имеет неверный формат')
    return value.strip()

def phone_normalize(value):
    phone=re.sub(r'[\s()\-]','',str(value))
    if phone.startswith('8') and len(phone)==11: phone='+7'+phone[1:]
    if not re.fullmatch(r'\+7\d{10}',phone): raise ValidationError('Введите номер в формате +7XXXXXXXXXX')
    return phone

def request_otp(session_key,phone,name,consent,marketing=False):
    phone=phone_normalize(phone)
    name=bounded_text(name,120)
    if not name or consent is not True: raise ValidationError('Имя и согласие на обработку данных обязательны')
    now=timezone.now()
    if OTPChallenge.objects.filter(phone=phone,created_at__gt=now-timedelta(seconds=45)).exists(): raise ValidationError('Повторный код можно получить через 45 секунд')
    if OTPChallenge.objects.filter(Q(phone=phone)|Q(session_key=session_key),created_at__gt=now-timedelta(hours=1)).count()>=10: raise ValidationError('Лимит запросов кода: попробуйте позже')
    code=f'{secrets.randbelow(1000000):06d}'
    OTPChallenge.objects.filter(phone=phone,session_key=session_key,consumed_at=None).update(consumed_at=now)
    OTPChallenge.objects.create(phone=phone,session_key=session_key,name=name,consent=True,marketing=marketing is True,code_hash=make_password(code),expires_at=now+timedelta(minutes=5))
    return code

def verify_otp(session_key,phone,code):
    phone=phone_normalize(phone)
    now=timezone.now()
    with transaction.atomic():
        challenge=OTPChallenge.objects.select_for_update().filter(phone=phone,session_key=session_key,consumed_at=None).order_by('-created_at').first()
        if not challenge or challenge.expires_at<=now or challenge.attempts>=5: raise ValidationError('Код истёк или превышен лимит попыток')
        OTPChallenge.objects.filter(pk=challenge.pk).update(attempts=F('attempts')+1)
        valid=check_password(str(code),challenge.code_hash)
        if valid:
            changed=OTPChallenge.objects.filter(pk=challenge.pk,consumed_at=None).update(consumed_at=now)
            if not changed: raise ValidationError('Код уже использован')
            customer,created=Customer.objects.get_or_create(phone=phone,defaults={'name':challenge.name,'phone_verified_at':now,'consent_at':now,'marketing_consent':challenge.marketing,'marketing_consent_at':now if challenge.marketing else None,'is_test':True})
            if not created:
                customer.name=challenge.name; customer.phone_verified_at=now; customer.consent_at=now
                customer.marketing_consent=challenge.marketing; customer.marketing_consent_at=now if challenge.marketing else None
                customer.save()
            audit('customer_phone_verified',customer=customer,after={'demo':True,'marketing':customer.marketing_consent})
    if not valid: raise ValidationError('Неверный код / Код қате')
    return customer

def resolve_table(token):
    if not token: raise ValidationError('Откройте подписанную QR-ссылку тестового столика')
    try:
        code=signing.Signer(salt='tuysqan-table-v1').unsign(token)
        return Table.objects.get(code=code,active=True)
    except (signing.BadSignature,Table.DoesNotExist,ValueError,ValidationError): raise ValidationError('QR-ссылка столика недействительна')

def menu_lines(raw):
    if not isinstance(raw,list) or not raw or len(raw)>80: raise ValidationError('Добавьте от 1 до 80 позиций')
    lines=[]
    for entry in raw:
        if not isinstance(entry,dict): raise ValidationError('Некорректная позиция')
        try:
            ident=int(entry['id']); qty=int(entry['quantity'])
            if isinstance(entry['quantity'],bool) or str(qty)!=str(entry['quantity']) or not 1<=qty<=99: raise ValueError()
            item=MenuItem.objects.get(pk=ident,available=True)
        except (KeyError,TypeError,ValueError,MenuItem.DoesNotExist): raise ValidationError('Товар недоступен или количество неверно')
        lines.append({'menu_item':item,'quantity':qty,'comment':bounded_text(entry.get('comment',''),500)})
    return lines

def snapshot(order):
    return {'status':order.status,'payment_status':order.payment_status,'subtotal':str(order.subtotal),'total':str(order.total),'actual_paid':str(order.actual_paid),'discount_percent':order.discount_percent,'discount_source':order.discount_source,'residential_complex':order.residential_complex,'food_eta_at':order.food_eta_at.isoformat() if order.food_eta_at else None,'food_eta_minutes':order.food_eta_minutes,'drink_eta_at':order.drink_eta_at.isoformat() if order.drink_eta_at else None,'drink_eta_minutes':order.drink_eta_minutes,'items':[{'id':x.menu_item_id,'quantity':x.quantity,'price':str(x.unit_price),'comment':x.comment,'status':x.status,'eta_at':x.eta_at.isoformat() if x.eta_at else None} for x in order.items.all()]}

def applicable_discount_percent(customer):
    # Anonymous guests have no identified loyalty account. Policy stays inactive until confirmed.
    if not customer or not customer.phone_verified_at or customer.is_test:
        return 0
    return 0 # All new discounts require an explicit guest choice.

DISCOUNT_OFFER_SALT='tuysqan-discount-offer-v1'
DISCOUNT_OFFER_MAX_AGE=600

def loyalty_phone_customer(customer):
    return bool(customer and not customer.is_test and re.fullmatch(r'\+7\d{10}',customer.phone))

def eligible_discount_percent(customer):
    """Unified phone account eligibility; this is not proof of SMS ownership."""
    if not loyalty_phone_customer(customer):return 0
    return max(0,min(100,int(customer.discount_percent)))

def discount_offer(customer=None,phone=None,context=''):
    normalized=phone_normalize(phone if phone is not None else customer.phone)
    percent=eligible_discount_percent(customer)
    tier=customer.available_loyalty_tiers[0] if customer and percent else None
    payload={'threshold':str(tier['threshold']) if tier else None,'subject':salted_hmac(DISCOUNT_OFFER_SALT,normalized).hexdigest(),'context':salted_hmac(DISCOUNT_OFFER_SALT,str(context)).hexdigest(),'percent':percent}
    return {'percent':percent,'token':signing.dumps(payload,salt=DISCOUNT_OFFER_SALT,compress=True)}

def discount_selection(customer,payload,actor=None,context='',unverified_claim=False):
    if 'discount_choice' not in payload:
        if payload.get('discount_source')=='residential':raise ValidationError('Выберите применение скидки / Жеңілдікті таңдаңыз')
        rate=0 if unverified_claim else applicable_discount_percent(customer)
        return {'discount_percent':rate,'discount_choice':'legacy','discount_offer_percent':rate,'loyalty_eligible':False}
    choice=payload.get('discount_choice')
    source=payload.get('discount_source','loyalty')
    if source not in ('loyalty','residential'):raise ValidationError('Выберите одну скидку / Бір жеңілдікті таңдаңыз')
    if source=='residential':
        require_role(actor,{'owner','manager','cashier'})
        if payload.get('residential_complex') not in ('vremena_goda','premiera') or payload.get('residency_confirmed') is not True:
            raise ValidationError('Кассир должен подтвердить ЖК гостя / Қонақтың ТК-сын кассир растауы керек')
    if not isinstance(choice,bool):raise ValidationError('Выберите применение скидки / Жеңілдікті қолдануды таңдаңыз',code='offer_changed')
    rate=eligible_discount_percent(customer)
    if not loyalty_phone_customer(customer):
        if choice:raise ValidationError('Скидка недоступна / Жеңілдік қолжетімсіз',code='offer_changed')
        return {'discount_percent':0,'discount_choice':'not_available','discount_offer_percent':0,'loyalty_eligible':False}
    token=payload.get('discount_offer_token')
    try:
        if not isinstance(token,str) or len(token)>2048:raise signing.BadSignature()
        offer=signing.loads(token,salt=DISCOUNT_OFFER_SALT,max_age=DISCOUNT_OFFER_MAX_AGE)
    except signing.SignatureExpired:
        raise ValidationError('Предложение скидки истекло. Проверьте скидку ещё раз / Жеңілдікті қайта тексеріңіз',code='offer_expired')
    except (signing.BadSignature,ValueError,TypeError):
        raise ValidationError('Проверьте скидку ещё раз / Жеңілдікті қайта тексеріңіз',code='offer_changed')
    expected_context=f'pos:{actor.pk}' if actor else context
    if (not isinstance(offer,dict) or offer.get('subject')!=salted_hmac(DISCOUNT_OFFER_SALT,customer.phone).hexdigest() or
        offer.get('context')!=salted_hmac(DISCOUNT_OFFER_SALT,str(expected_context)).hexdigest() or offer.get('percent')!=rate or offer.get('threshold')!=(str(customer.available_loyalty_tiers[0]['threshold']) if rate else None)):
        raise ValidationError('Доступная скидка изменилась. Выберите заново / Жеңілдік өзгерді, қайта таңдаңыз',code='offer_changed')
    if source=='residential':
        return {'discount_percent':10 if choice else 0,'discount_choice':'applied' if choice else 'declined','discount_offer_percent':10,'loyalty_eligible':True,'discount_source':'residential' if choice else '', 'residential_complex':payload['residential_complex'] if choice else ''}
    if choice and rate<=0:raise ValidationError('Скидка недоступна / Жеңілдік қолжетімсіз',code='offer_changed')
    return {'discount_percent':rate if choice else 0,'discount_choice':'applied' if choice else 'declined' if rate else 'not_available','discount_offer_percent':rate,'loyalty_eligible':True,'discount_source':'loyalty' if choice else ''}

def reserve_loyalty(order):
    tier=next((t for t in order.customer.available_loyalty_tiers if int(t['percent'])==order.discount_percent),None)
    if not tier:raise ValidationError('Уровень скидки уже использован или зарезервирован / Жеңілдік пайдаланылған',code='offer_changed')
    try:
        with transaction.atomic():
            LoyaltyRedemption.objects.update_or_create(order=order,defaults={'customer':order.customer,'threshold':Decimal(str(tier['threshold'])),'percent':order.discount_percent,'active':True,'consumed_at':None})
    except IntegrityError:
        raise ValidationError('Уровень скидки уже занят другим заказом / Жеңілдік басқа тапсырыста',code='offer_changed')


def replace_lines(order,lines):
    order.items.all().delete() # Allowed only before payment and preparation; audit preserves prior lines.
    OrderItem.objects.bulk_create([OrderItem(order=order,menu_item=x['menu_item'],name_ru=x['menu_item'].name_ru,name_kz=x['menu_item'].name_kz,kind=x['menu_item'].kind,unit_price=x['menu_item'].price,quantity=x['quantity'],comment=x['comment']) for x in lines])
    order.subtotal=sum((x['menu_item'].price*x['quantity'] for x in lines),Decimal('0'))
    order.discount_amount=(order.subtotal*order.discount_percent/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    order.total=order.subtotal-order.discount_amount

def validate_preference(lines,preference,takeaway=False):
    if takeaway:return ''
    kinds={x['menu_item'].kind for x in lines}
    if kinds=={'food','drink'}:
        if preference not in ['immediately','with_food']: raise ValidationError('Выберите: напитки сразу или вместе с блюдами')
        return preference
    return ''

def notification_payload(order):
    return {'number':order.number,'order_id':str(order.public_id),'table':str(order.table or ('С собой' if order.source=='pos' else 'Касса')),'customer':order.customer.name,'phone':order.customer.phone,'payment_method':order.payment_method,'drink_preference':order.drink_preference,'comment':order.comment,'items':[{'name':i.name_ru,'kind':i.kind,'quantity':i.quantity,'comment':i.comment} for i in order.items.all()],'actions':['accept','reject','eta','ready'],'eta_choices':list(ETA_CHOICES),'is_test':order.is_test}

def enqueue(order,kind='new_order'):
    return OutboxMessage.objects.create(order=order,kind=kind,payload=notification_payload(order))

@transaction.atomic
def create_order(customer,payload,actor=None,unverified_claim=False,discount_context=''):
    if not customer or (not unverified_claim and not customer.phone_verified_at and not (actor and customer.phone=='pos-walk-in')): raise PermissionDenied('Недействительная гостевая сессия')
    if actor: require_role(actor,{'owner','manager','cashier'})
    key=bounded_text(payload.get('idempotency_key',''),100)
    if not key or len(key)<8: raise ValidationError('Нужен ключ повторной отправки')
    canonical={k:payload.get(k) for k in ['items','table_token','payment_method','drink_preference','comment']}
    if 'discount_choice' in payload:canonical['discount_choice']=payload['discount_choice']
    for field in ('discount_source','residential_complex','residency_confirmed'):
        if field in payload:canonical[field]=payload[field]
    fingerprint=payload['_pos_fingerprint'] if actor and payload.get('_pos_fingerprint') else hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    previous=Order.objects.filter(customer=customer,idempotency_key=key).first()
    if previous:
        if previous.payload_hash!=fingerprint: raise ValidationError('Этот ключ уже использован для другого заказа')
        return previous,False
    customer=Customer.objects.select_for_update().get(pk=customer.pk)
    # Re-read retry after acquiring the customer lock (PostgreSQL concurrent submissions).
    previous=Order.objects.filter(customer=customer,idempotency_key=key).first()
    if previous:
        if previous.payload_hash!=fingerprint:raise ValidationError('Этот ключ уже использован для другого заказа')
        return previous,False
    discount=discount_selection(customer,payload,actor,discount_context,unverified_claim)
    lines=menu_lines(payload.get('items'))
    method=payload.get('payment_method')
    if method not in dict(Order.PAYMENT_METHODS): raise ValidationError('Выберите способ оплаты')
    table=None if actor and payload.get('fulfillment')=='takeaway' else resolve_table(payload.get('table_token'))
    preference=validate_preference(lines,payload.get('drink_preference',''),takeaway=bool(actor and payload.get('fulfillment')=='takeaway'))
    comment=bounded_text(payload.get('comment',''),1000)
    # Preserve fixture provenance. New operational orders do not inherit test revenue flags.
    # A concurrent identical request may commit after the fast-path lookup above.
    # get_or_create uses a savepoint and re-reads the unique key after that race;
    # only the winning request creates lines, audit events and outbox messages.
    order,created=Order.objects.get_or_create(customer=customer,idempotency_key=key,defaults={
        'table':table,'payload_hash':fingerprint,'payment_method':method,
        'drink_preference':preference,'comment':comment,
        'is_test':bool(customer.is_test or (table is not None and table.is_test) or any(x['menu_item'].is_test for x in lines)),
        'source':'pos' if actor else 'web',**discount,
        'customer_identity_verified':bool(customer.phone_verified_at) and not unverified_claim})
    if not created:
        if order.payload_hash!=fingerprint:raise ValidationError('Этот ключ уже использован для другого заказа')
        return order,False
    if order.discount_source=='loyalty':reserve_loyalty(order)
    replace_lines(order,lines); order.save()
    audit('order_created',actor,order,after=snapshot(order),customer=customer)
    enqueue(order) # Durable local outbox; no network call in order creation.
    return order,True


@transaction.atomic
def create_pos_order(actor,payload):
    require_role(actor,{'owner','manager','cashier'})
    mode=payload.get('fulfillment','dine_in')
    if mode not in ('dine_in','takeaway'): raise ValidationError('Выберите заказ в зале или с собой')
    payload=dict(payload)
    if mode=='takeaway':payload['drink_preference']=''
    accept=payload.get('accept_order',False)
    if not isinstance(accept,bool): raise ValidationError('Некорректный способ сохранения заказа')
    eta=None
    raw_eta=payload.get('drink_eta',payload.get('eta'))
    if mode=='takeaway' and 'drink_eta' not in payload:raw_eta=None
    if accept and raw_eta not in (None,''):
        eta=preparation_minutes(raw_eta)
    raw_key=bounded_text(payload.get('idempotency_key',''),70)
    if len(raw_key)<8: raise ValidationError('Нужен ключ повторной отправки')
    key=f'pos:{actor.pk}:{raw_key}'
    customer_data=payload.get('customer')
    identity=None
    if customer_data is not None:
        if not isinstance(customer_data,dict): raise ValidationError('Некорректные данные гостя')
        phone=phone_normalize(customer_data.get('phone',''))
        if customer_data.get('consent') is not True: raise ValidationError('Необходимо согласие на обработку данных')
        identity={'phone':phone,'name':bounded_text(customer_data.get('name',''),120),'consent':True}
    canonical={k:payload.get(k) for k in ['items','payment_method','drink_preference','comment']}
    canonical.update({'table_token':payload.get('table_token') if mode=='dine_in' else None,'fulfillment':mode,'accept_order':accept,'eta':eta,'customer':identity})
    if 'drink_eta' in payload:canonical['drink_eta']=eta
    if 'discount_choice' in payload:canonical['discount_choice']=payload['discount_choice']
    for field in ('discount_source','residential_complex','residency_confirmed'):
        if field in payload:canonical[field]=payload[field]
    fingerprint=hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    previous=Order.objects.select_for_update().filter(source='pos',idempotency_key=key).first()
    if previous:
        allowed_hashes={fingerprint}
        if mode=='takeaway':
            # Preserve retries of historical POS requests without rewriting orders.
            for preference in ('','immediately','with_food',None):
                for old_eta in (None,*ETA_CHOICES):
                    legacy=dict(canonical,drink_preference=preference,eta=old_eta)
                    allowed_hashes.add(hashlib.sha256(json.dumps(legacy,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
        if previous.payload_hash not in allowed_hashes: raise ValidationError('Этот ключ уже использован для другого заказа')
        return previous,False
    if mode=='dine_in' and resolve_table(payload.get('table_token')).is_test:
        raise ValidationError('Выберите рабочий столик')
    if any(x['menu_item'].is_test for x in menu_lines(payload.get('items'))):
        raise ValidationError('Тестовые позиции недоступны для продажи')
    if identity:
        customer=Customer.objects.select_for_update().filter(phone=identity['phone'],is_test=False).first()
        if customer is None:
            if not identity['name']: raise ValidationError('Укажите имя нового гостя')
            customer,created=Customer.objects.get_or_create(phone=identity['phone'],defaults={'name':identity['name'],'consent_at':timezone.now(),'is_test':False})
            if customer.is_test:
                customer.name=identity['name'];customer.is_test=False;customer.phone_verified_at=None
                customer.consent_at=timezone.now();customer.marketing_consent=False;customer.marketing_consent_at=None
                customer.save(update_fields=['name','is_test','phone_verified_at','consent_at','marketing_consent','marketing_consent_at'])
    else:
        customer,_=Customer.objects.get_or_create(phone='pos-walk-in',defaults={'name':'Гость кассы','consent_at':timezone.now(),'is_test':False})
        if customer.is_test:
            customer.is_test=False;customer.phone_verified_at=None
            customer.save(update_fields=['is_test','phone_verified_at'])
    internal=dict(payload,idempotency_key=key,fulfillment=mode,_pos_fingerprint=fingerprint)
    if mode=='takeaway': internal['table_token']=None
    order,created=create_order(customer,internal,actor=actor,unverified_claim=True)
    if created and accept: order=act_on_order(order.public_id,actor,'accept',{'drink_eta':eta})
    return order,created

def lock_order(order_id):
    order=Order.objects.select_for_update().get(public_id=order_id)
    # Conditional write obtains SQLite's write lock as well as guarding stale revisions.
    if not Order.objects.filter(pk=order.pk,version=order.version).update(version=F('version')+1): raise ValidationError('Заказ изменился. Обновите страницу')
    order.version+=1
    return order

def kitchen_released(order):
    return order.status in ['accepted','preparing','ready'] and (AppSettings.get().kitchen_release=='acceptance' or order.payment_status=='paid')

def kitchen_queue():
    query=Order.objects.filter(status__in=['accepted','preparing','ready'],items__kind='food').distinct()
    if AppSettings.get().kitchen_release=='payment': query=query.filter(payment_status='paid')
    return query.order_by('created_at')

def selected_payment_method(order,payment_method=None):
    method=order.payment_method if payment_method is None else payment_method
    if method not in dict(Order.PAYMENT_METHODS): raise ValidationError('Выберите способ оплаты')
    return method

@transaction.atomic
def confirm_payment(order,actor,amount,reason='',key='',cash_received=None,payment_method=None):
    require_role(actor,{'owner','manager','cashier'})
    # Lock without updating the version: an exact retry must be read-only.
    order=Order.objects.select_for_update().get(public_id=order.public_id)
    method=selected_payment_method(order,payment_method)
    amount=money(amount); reason=bounded_text(reason,1000)
    if amount<=0: raise ValidationError('Оплата должна быть больше нуля')
    tender=None
    if cash_received is not None:
        if method!='cash': raise ValidationError('Полученная наличная сумма доступна только для оплаты наличными')
        tender=money(cash_received)
        if tender<amount: raise ValidationError('Полученная сумма меньше суммы оплаты')
    if order.status in ['new','rejected','cancelled']: raise ValidationError('Сначала примите заказ')
    if order.payment_status=='paid':
        current=order.payments.filter(reversed_at=None).order_by('-created_at','-pk').first()
        facts=payment_cash_facts(order)
        stored_tender=money(facts['cash_received']) if facts['cash_received'] is not None else None
        supplied_key=bounded_text(key,100)
        keyed=Payment.objects.filter(idempotency_key=supplied_key).first() if supplied_key else None
        if (not current or order.actual_paid!=amount or current.amount!=amount or current.method!=method or
                current.reason!=reason or stored_tender!=tender or (keyed and keyed.pk!=current.pk)):
            raise ValidationError('Оплата уже подтверждена с другими данными. Используйте отдельную отмену оплаты с причиной')
        return order
    if amount!=order.total and not reason: raise ValidationError('Укажите причину отличия фактической суммы')
    key=bounded_text(key or f'payment-{order.public_id}-{order.payments.count()}',100)
    if Payment.objects.filter(idempotency_key=key).exists(): raise ValidationError('Ключ оплаты уже использован')
    before=snapshot(order);before['payment_method']=order.payment_method
    order=lock_order(order.public_id)
    order.payment_method=method
    payment=Payment.objects.create(order=order,amount=amount,method=method,confirmed_by=actor,idempotency_key=key,reason=reason)
    order.payment_status='paid'; order.actual_paid=amount; order.paid_at=timezone.now(); order.save()
    LoyaltyRedemption.objects.filter(order=order,active=True,consumed_at=None).update(consumed_at=timezone.now())
    # The phone-based program also covers orders placed before explicit discount choice existed.
    if loyalty_phone_customer(order.customer) and not order.is_test and LoyaltyPolicy.get().confirmed:
        LoyaltyEntry.objects.get_or_create(payment=payment,kind='purchase',defaults={'customer':order.customer,'order':order,'amount':amount})
        audit('loyalty_purchase',actor,order,after={'amount':str(amount)},customer=order.customer)
    after=snapshot(order)
    after.update(payment_id=payment.pk,payment_method=method)
    if tender is not None: after.update(cash_received=str(tender),change=str(tender-amount))
    audit('payment_confirmed',actor,order,reason,before,after)
    return order

@transaction.atomic
def reverse_payment(order,actor,reason,channel='web'):
    require_role(actor,{'owner','manager'})
    reason=bounded_text(reason,1000)
    if not reason: raise ValidationError('Причина возврата/отмены оплаты обязательна')
    order=lock_order(order.public_id)
    if order.payment_status!='paid': raise ValidationError('Нет подтверждённой оплаты')
    before=snapshot(order)
    payments=order.payments.filter(reversed_at=None)
    for p in payments:
        p.reversed_at=timezone.now(); p.reversal_reason=reason; p.save()
        entry=LoyaltyEntry.objects.filter(payment=p,kind='purchase').first()
        if entry:
            LoyaltyEntry.objects.get_or_create(payment=p,kind='reversal',defaults={'order':order,'customer':order.customer,'amount':-entry.amount})
            audit('loyalty_reversal',actor,order,reason,after={'amount':str(-entry.amount)},customer=order.customer)
    order.payment_status='refunded'; order.actual_paid=0; order.save()
    audit('payment_reversed',actor,order,reason,before,snapshot(order),channel)
    return order

@transaction.atomic
def accept_and_pay_order(order_id,actor,data,channel='web'):
    """Explicit cashier confirmation, atomically accepting a QR order and payment."""
    require_role(actor,{'owner','manager','cashier'})
    key=bounded_text(data.get('idempotency_key',''),100)
    if len(key)<8: raise ValidationError('Нужен ключ подтверждения оплаты')
    amount=money(data.get('amount'))
    if amount<=0: raise ValidationError('Оплата должна быть больше нуля')
    reason=bounded_text(data.get('reason',''),1000)
    order=Order.objects.select_for_update().get(public_id=order_id)
    if order.source!='web': raise ValidationError('Совместное подтверждение доступно только для QR-заказов')
    method=selected_payment_method(order,data.get('payment_method'))
    tender=None
    if data.get('cash_received') is not None:
        if method!='cash': raise ValidationError('Полученная наличная сумма доступна только для оплаты наличными')
        tender=money(data['cash_received'])
        if tender<amount: raise ValidationError('Полученная сумма меньше суммы оплаты')
    previous=Payment.objects.select_for_update().filter(idempotency_key=key).first()
    if previous:
        facts=payment_cash_facts(order)
        stored_tender=money(facts['cash_received']) if facts['cash_received'] is not None else None
        if (previous.order_id!=order.pk or previous.reversed_at is not None or
                order.payment_status!='paid' or order.actual_paid!=amount or
                previous.amount!=amount or previous.method!=method or order.payment_method!=method or
                previous.reason!=reason or stored_tender!=tender):
            raise ValidationError('Этот ключ уже использован для другого подтверждения оплаты')
        # A retry never reaccepts, resets readiness, or adds audit/payment records.
        return order
    if order.status!='new' or order.payment_status=='paid':
        raise ValidationError('Заказ уже обработан. Обновите очередь')
    accepted=act_on_order(order.public_id,actor,'accept',{'drink_eta':data.get('drink_eta',data.get('eta'))},channel=channel)
    return confirm_payment(accepted,actor,amount,reason,key,cash_received=tender,payment_method=method)

@transaction.atomic
def confirm_order_discount(order_id,actor,data,channel='web'):
    require_role(actor,{'owner','manager','cashier'})
    order=Order.objects.select_for_update().select_related('customer').get(public_id=order_id)
    if order.status in ('cancelled','rejected') or order.payment_status!='unpaid' or order.payments.exists():
        raise ValidationError('Скидку можно изменить только до оплаты / Жеңілдік тек төлемге дейін өзгертіледі')
    if order.discount_choice!='legacy':raise ValidationError('Выбор скидки уже сохранён клиентом. Кассир не подтверждает скидку повторно / Жеңілдік таңдауы сақталған')
    raw=data.get('discount_percent')
    if isinstance(raw,bool) or not isinstance(raw,(str,int)) or str(raw) not in ('0','5','7','10','12','15'):
        raise ValidationError('Выберите скидку 0, 5, 7, 10, 12 или 15%')
    percent=int(raw);reason=bounded_text(data.get('reason',''),1000)
    if not reason:raise ValidationError('Укажите основание скидки / Жеңілдік негізін көрсетіңіз')
    if data.get('identity_confirmed') is not True:raise ValidationError('Подтвердите проверку скидки с гостем / Жеңілдікті қонақпен тексеріңіз')
    if order.discount_percent==percent and order.events.filter(action='discount_confirmed',after__discount_percent=percent).exists():return order
    if data.get('version') is not None:
        if isinstance(data['version'],bool) or str(data['version'])!=str(order.version):
            raise ValidationError('Заказ изменился. Обновите очередь / Тапсырыс өзгерді')
    before=snapshot(order)
    if not Order.objects.filter(pk=order.pk,version=order.version).update(version=F('version')+1):
        raise ValidationError('Заказ изменился. Обновите очередь')
    order.version+=1;order.discount_percent=percent
    if LoyaltyPolicy.get().confirmed:
        Customer.objects.select_for_update().get(pk=order.customer_id)
        LoyaltyRedemption.objects.filter(order=order,consumed_at=None).update(active=False)
        if percent:
            reserve_loyalty(order)
        order.discount_source='loyalty' if percent else ''
    else:
        order.discount_source='manual' if percent else ''
    order.discount_amount=(order.subtotal*Decimal(percent)/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    order.total=order.subtotal-order.discount_amount
    order.save(update_fields=['discount_percent','discount_source','discount_amount','total','version','updated_at'])
    after=snapshot(order);after['discount_amount']=str(order.discount_amount);after['checked_with_guest']=True
    audit('discount_confirmed',actor,order,reason,before,after,channel)
    return order

def station_minutes(value):
    try:
        if isinstance(value,bool):raise ValueError()
        minutes=int(value)
        if str(minutes)!=str(value) or minutes not in ETA_CHOICES:raise ValueError()
    except (ValueError,TypeError):raise ValidationError('Выберите время 5–30 минут')
    return minutes

def preparation_minutes(value):
    try:
        minutes=int(value)
        if isinstance(value,bool) or str(minutes)!=str(value) or not 1<=minutes<=180:raise ValueError()
    except (TypeError,ValueError):raise ValidationError('Укажите целое число минут от 1 до 180')
    return minutes

def set_drink_duration(order,minutes,now):
    order.drink_eta_minutes=minutes
    started=order.drink_started_at
    # Legacy in-progress drinks already have an explicitly confirmed state.
    if not started and order.items.filter(kind='drink',status='preparing').exists():
        started=order.drink_started_at=now
    order.drink_eta_at=started+timedelta(minutes=minutes) if started else None

def set_station_eta(order,kind,minutes,now,start=True):
    setattr(order,kind+'_eta_minutes',minutes)
    setattr(order,kind+'_eta_at',now+timedelta(minutes=minutes))
    deadlines=[date for date in [order.food_eta_at,order.drink_eta_at] if date]
    order.eta_at=max(deadlines) if deadlines else None
    order.eta_minutes=max([value for value in [order.food_eta_minutes,order.drink_eta_minutes] if value is not None],default=None)
    order.delay_notified_at=None
    if kind=='food':order.items.filter(kind='food').exclude(status='ready').update(eta_at=order.food_eta_at,eta_minutes=minutes)
    if start:
        order.items.filter(kind=kind).exclude(status='ready').update(status='preparing')
        order.status='preparing'

@transaction.atomic
def act_on_order(order_id,actor,action,data=None,channel='web'):
    data=data or {}
    role=role_of(actor)
    if role=='kitchen':
        if action not in ['preparing','item_ready','item_preparing','food_eta']: raise PermissionDenied('Кухне доступны только время и статусы блюд')
    else: require_role(actor,{'owner','manager','cashier'})
    if action=='accept_and_pay': return accept_and_pay_order(order_id,actor,data,channel)
    if action=='discount': return confirm_order_discount(order_id,actor,data,channel)
    if action=='pay': return confirm_payment(Order.objects.get(public_id=order_id),actor,data.get('amount'),data.get('reason',''),data.get('idempotency_key',''),cash_received=data.get('cash_received'),payment_method=data.get('payment_method'))
    order=lock_order(order_id)
    if action in ['refund','reverse_payment']: return reverse_payment(order,actor,data.get('reason',''),channel)
    before=snapshot(order)
    reason=bounded_text(data.get('reason',''),1000)
    now=timezone.now()
    if role=='kitchen' and not kitchen_released(order): raise PermissionDenied('Заказ ещё не передан кухне')
    if action=='accept':
        if order.status!='new':raise ValidationError('Заказ уже обработан')
        order.status='accepted';order.accepted_at=now
        raw_eta=data.get('drink_eta',data.get('eta'))
        if raw_eta not in (None,''):
            minutes=preparation_minutes(raw_eta)
            if order.items.filter(kind='drink').exists():set_drink_duration(order,minutes,now)
    elif action=='drink_notice_seen':
        plan=drink_plan(order,list(order.items.all()),now)
        if not plan['event_token'] or data.get('event_token')!=plan['event_token']:raise ValidationError('Рекомендация изменилась. Обновите заказ')
        order.drink_notice_seen_token=plan['event_token']
    elif action in ['drink_eta','eta','drinks_start']:
        require_role(actor,{'owner','manager','cashier'})
        if order.status not in ['accepted','preparing']:raise ValidationError('Сначала примите заказ')
        drinks=order.items.filter(kind='drink').exclude(status='ready')
        if not drinks.exists():raise ValidationError('Нет незавершённых напитков')
        if action=='drinks_start' and order.drink_started_at:return order
        minutes=preparation_minutes(data['eta'] if data.get('eta') not in (None,'') else order.drink_eta_minutes)
        set_drink_duration(order,minutes,now)
        if action=='drinks_start':
            order.drink_started_at=now
            order.drink_food_eta_at_start=food_plan(order,list(order.items.all()))[2]
            order.drink_eta_at=now+timedelta(minutes=minutes)
            drinks.update(status='preparing');order.status='preparing'
    elif action=='food_eta':
        require_role(actor,{'owner','manager','kitchen'})
        if order.status not in ['accepted','preparing']:raise ValidationError('Время доступно после принятия и до готовности заказа')
        if not kitchen_released(order):raise ValidationError('Блюда ещё не переданы кухне')
        food=order.items.filter(kind='food').exclude(status='ready')
        if not food.exists():raise ValidationError('Нет незавершённых блюд')
        if order.is_delayed:order.was_delayed=True
        if 'items' in data:
            rows=data['items']
            if not isinstance(rows,list) or not rows:raise ValidationError('Укажите время хотя бы одного блюда')
            seen=set()
            for row in rows:
                if not isinstance(row,dict) or type(row.get('item_id')) is not int:raise ValidationError('Выберите блюдо')
                item_id=row['item_id']
                if item_id in seen or not food.filter(pk=item_id).exists():raise ValidationError('Позиция недоступна кухне')
                seen.add(item_id);minutes=preparation_minutes(row.get('eta'))
                food.filter(pk=item_id).update(eta_minutes=minutes,eta_at=now+timedelta(minutes=minutes),status='preparing')
            planned=list(food)
            order.food_eta_at=max((i.eta_at for i in planned if i.eta_at),default=None)
            order.food_eta_minutes=max((i.eta_minutes for i in planned if i.eta_minutes),default=None)
            order.status='preparing';order.delay_notified_at=None
        else:set_station_eta(order,'food',station_minutes(data.get('eta')),now)
    elif action in ['reject','cancel']:
        if not reason: raise ValidationError('Укажите причину')
        if order.payment_status=='paid': raise ValidationError('Сначала отмените оплату отдельным действием')
        if order.status in TERMINAL: raise ValidationError('Заказ уже завершён')
        if action=='reject' and order.status!='new': raise ValidationError('Отклонить можно только новый заказ')
        order.status='rejected' if action=='reject' else 'cancelled'
        LoyaltyRedemption.objects.filter(order=order,active=True,consumed_at=None).update(active=False)
    elif action=='correct':
        if not reason: raise ValidationError('Причина корректировки обязательна')
        if order.payment_status=='paid' or order.status not in ['new','accepted']: raise ValidationError('Корректировка доступна до приготовления и оплаты')
        lines=menu_lines(data.get('items'))
        order.drink_preference=validate_preference(lines,data.get('drink_preference',order.drink_preference),takeaway=order.source=='pos' and order.table_id is None)
        replace_lines(order,lines)
        order.comment=bounded_text(data.get('comment',order.comment),1000)
    elif action=='ready':
        require_role(actor,{'owner','manager','cashier'})
        if order.status not in ['accepted','preparing','ready']:raise ValidationError('Сначала примите заказ')
        if not order.items.exists() or order.items.exclude(status='ready').exists():raise ValidationError('Сначала подтвердите готовность всех блюд и напитков')
        if order.is_delayed:order.was_delayed=True
        order.status='ready';order.ready_at=order.ready_at or now
    elif action in ['preparing','item_preparing','item_ready','drinks_ready']:
        if order.status not in ['accepted','preparing']:raise ValidationError('Сначала примите заказ; готовый заказ изменять нельзя')
        if order.is_delayed:order.was_delayed=True
        items=order.items.all()
        if role=='kitchen':items=items.filter(kind='food')
        elif action=='preparing':items=items.filter(kind='drink')
        if action=='drinks_ready':items=items.filter(kind='drink')
        if action.startswith('item_'):
            try:item_id=int(data.get('item_id'))
            except (TypeError,ValueError):raise ValidationError('Выберите позицию')
            items=items.filter(pk=item_id)
            if not items.exists():raise PermissionDenied('Позиция недоступна этой станции')
            # Cashiers operate the bar; owners/managers may cover either station.
            if role=='cashier' and items.filter(kind='food').exists():raise PermissionDenied('Готовность блюд отмечает кухня')
        if items.filter(kind='food').exists() and not kitchen_released(order):raise ValidationError('Блюда ждут подтверждения оплаты')
        if not items.exists():raise ValidationError('Нет позиций для этого действия')
        items.exclude(status='ready').update(status='preparing' if action in ['preparing','item_preparing'] else 'ready')
        order.status='preparing'
    elif action=='serve':
        if order.status!='ready': raise ValidationError('Сначала подтвердите готовность')
        order.status='served'; order.served_at=now
    else: raise ValidationError('Неизвестное действие')
    if action in ['item_ready','item_preparing','preparing']:
        pending_food=list(order.items.filter(kind='food').exclude(status='ready'))
        known=[i.eta_at for i in pending_food if i.eta_at]
        if known:order.food_eta_at=max(known)
    deadlines=[value for value in (order.food_eta_at,order.drink_eta_at) if value]
    order.eta_at=max(deadlines,default=None)
    order.eta_minutes=max([value for value in (order.food_eta_minutes,order.drink_eta_minutes) if value],default=None)
    order.save()
    audit(action,actor,order,reason,before,snapshot(order),channel)
    return order

@transaction.atomic
def mark_delays():
    now=timezone.now()
    for order in Order.objects.filter(Q(eta_at__lt=now)|Q(food_eta_at__lt=now)|Q(drink_eta_at__lt=now),status__in=['accepted','preparing'],delay_notified_at=None):
        if not order.is_delayed:continue
        changed=Order.objects.filter(pk=order.pk,delay_notified_at=None).update(delay_notified_at=now,was_delayed=True)
        if changed: enqueue(order,'delayed')


def staff_payment_history(order):
    """Saved payment operations, including reversals; exposed only in staff data."""
    by_payment={}
    events=order._display_payment_events if hasattr(order,'_display_payment_events') else order.events.filter(action='payment_confirmed').order_by('-created_at','-pk')
    for event in events:
        ident=event.after.get('payment_id')
        if ident is not None and ident not in by_payment:by_payment[ident]=event.after
    result=[]
    payments=order._display_payments if hasattr(order,'_display_payments') else order.payments.all().order_by('-created_at','-pk')
    for payment in payments:
        facts=by_payment.get(payment.pk,{})
        result.append({'id':payment.pk,'created_at':payment.created_at.isoformat(),'amount':str(payment.amount),
                       'method':payment.method,'reason':payment.reason,
                       'cash_received':facts.get('cash_received') if payment.method=='cash' else None,
                       'change':facts.get('change') if payment.method=='cash' else None,
                       'reversed_at':payment.reversed_at.isoformat() if payment.reversed_at else None,
                       'reversal_reason':payment.reversal_reason})
    return result

def payment_cash_facts(order,history=None):
    facts={'cash_received':None,'change':None}
    if order.payment_status!='paid' or order.payment_method!='cash': return facts
    history=staff_payment_history(order) if history is None else history
    current=next((payment for payment in history if payment['reversed_at'] is None),None)
    if current and current['method']=='cash':
        return {'cash_received':current['cash_received'],'change':current['change']}
    return facts

def mascot_state(order,review_sent=None,now=None):
    now=now or timezone.now()
    if review_sent is None:review_sent=Review.objects.filter(order=order).exists()
    due=order.served_at+timedelta(minutes=15) if order.served_at else None
    state=None
    if not order.mascot_dismissed_at and not review_sent:
        if order.status in ('new','accepted','preparing','ready') and not order.guest_wish_at:state='preparing' if order.status=='preparing' else 'waiting'
        elif order.status=='served' and order.served_at:state='feedback' if now>=due else 'served'
    return {'state':state,'dismissed':bool(order.mascot_dismissed_at),'wish_sent':bool(order.guest_wish_at),'review_sent':review_sent,'feedback_due_at':due.isoformat() if due else None}

def order_data(order,include_customer=False):
    reviewed=order._display_reviewed if hasattr(order,'_display_reviewed') else Review.objects.filter(order=order).exists()
    items=order._display_items if hasattr(order,'_display_items') else list(order.items.select_related('menu_item').all())
    data={'id':order.pk,'public_id':str(order.public_id),'created_at':order.created_at.isoformat(),'number':order.number,'source':order.source,'fulfillment':'takeaway' if order.source=='pos' and order.table_id is None else 'dine_in','status':order.status,'status_label':order.get_status_display(),'payment_status':order.payment_status,'payment_status_label':order.get_payment_status_display(),'table':str(order.table or ''),'payment_method':order.payment_method,'drink_preference':order.drink_preference,'comment':order.comment,'subtotal':str(order.subtotal),'discount_source':order.discount_source,'residential_complex':order.residential_complex,'discount_choice':order.discount_choice,'discount_offer_percent':order.discount_offer_percent,'discount_percent':order.discount_percent,'discount_amount':str(order.discount_amount),'total':str(order.total),'actual_paid':str(order.actual_paid),'eta_minutes':order.eta_minutes,'eta_at':order.eta_at.isoformat() if order.eta_at else None,'is_delayed':order._display_is_delayed if hasattr(order,'_display_is_delayed') else order.is_delayed,'is_test':order.is_test,'served_at':order.served_at.isoformat() if order.served_at else None,'server_now':timezone.now().isoformat(),'mascot':mascot_state(order,reviewed),'can_review':order.status=='served' and not reviewed and not order.mascot_dismissed_at,'items':[{'id':i.id,'menu_item_id':i.menu_item_id,'image':i.menu_item.image if i.menu_item else '','name_ru':i.name_ru,'name_kz':i.name_kz,'kind':i.kind,'quantity':i.quantity,'comment':i.comment,'unit_price':str(i.unit_price),'line_total':str(i.line_total),'status':i.status} for i in items]}
    data.update({kind+'_eta_'+part:(getattr(order,kind+'_eta_'+part).isoformat() if part=='at' and getattr(order,kind+'_eta_'+part) else getattr(order,kind+'_eta_'+part)) for kind in ['food','drink'] for part in ['minutes','at']})
    food=[item for item in items if item.kind=='food'];drinks=[item for item in items if item.kind=='drink']
    data['food_ready']=bool(food) and all(item.status=='ready' for item in food)
    data['drinks_ready']=bool(drinks) and all(item.status=='ready' for item in drinks)
    for serialized,item in zip(data['items'],items):serialized['eta_at']=item.eta_at.isoformat() if item.eta_at else None
    if include_customer:data['drink_plan']=drink_plan(order,items)
    if include_customer:
        data['customer']={'name':order.customer.name,'phone':order.customer.phone}
        history=staff_payment_history(order)
        data['payment_history']=history
        if hasattr(order,'_display_loyalty'):
            policy,ledger,paid=order._display_loyalty
        else:
            policy=LoyaltyPolicy.get()
            ledger=max(Decimal('0'),order.customer.loyalty_total)
            paid=max(Decimal('0'),order.customer.orders.filter(payment_status='paid',is_test=False).exclude(status__in=['cancelled','rejected']).aggregate(n=Sum('actual_paid'))['n'] or Decimal('0'))
        basis=ledger if policy.confirmed else paid
        # Informational recommendation only: the cashier explicitly approves the rate.
        suggested=order._display_available_percent if hasattr(order,'_display_available_percent') else eligible_discount_percent(order.customer) if policy.confirmed else 0
        data['version']=order.version
        data['discount_review']={'available':order.discount_choice=='legacy' and order.payment_status=='unpaid' and not history and order.status not in ('cancelled','rejected'),'program_active':policy.confirmed,'accumulated':str(basis),'suggested_percent':suggested}
        data.update(payment_cash_facts(order,history))
    return data

# Phone-first authentication. Delivery success is required before reporting success.
def begin_phone_otp(session_key,phone):
    from .sms import deliver_code
    phone=phone_normalize(phone);now=timezone.now()
    if not session_key:raise ValidationError('Сессия недействительна')
    if OTPChallenge.objects.filter(phone=phone,created_at__gt=now-timedelta(seconds=45)).exists():raise ValidationError('Повторный код можно получить через 45 секунд')
    if OTPChallenge.objects.filter(Q(phone=phone)|Q(session_key=session_key),created_at__gt=now-timedelta(hours=1)).count()>=10:raise ValidationError('Лимит запросов кода: попробуйте позже')
    code=f'{secrets.randbelow(1000000):06d}'
    # Never return or log the plaintext code. Transport is the sole recipient.
    with transaction.atomic():
        OTPChallenge.objects.filter(phone=phone,session_key=session_key,consumed_at=None).update(consumed_at=now)
        challenge=OTPChallenge.objects.create(phone=phone,session_key=session_key,name='',consent=False,code_hash=make_password(code),expires_at=now+timedelta(minutes=5))
    try:deliver_code(phone,code)
    except Exception:
        OTPChallenge.objects.filter(pk=challenge.pk).update(consumed_at=timezone.now())
        raise
    return phone

def verify_phone_otp(session_key,phone,code):
    phone=phone_normalize(phone);now=timezone.now();valid=False
    with transaction.atomic():
        challenge=OTPChallenge.objects.select_for_update().filter(phone=phone,session_key=session_key,consumed_at=None).order_by('-created_at').first()
        if not challenge or challenge.expires_at<=now or challenge.attempts>=5:raise ValidationError('Код истёк или превышен лимит попыток')
        OTPChallenge.objects.filter(pk=challenge.pk).update(attempts=F('attempts')+1)
        valid=bool(re.fullmatch(r'\d{6}',str(code))) and check_password(str(code),challenge.code_hash)
        if valid:
            changed=OTPChallenge.objects.filter(pk=challenge.pk,consumed_at=None).update(consumed_at=now)
            if not changed:raise ValidationError('Код уже использован')
    if not valid:raise ValidationError('Неверный код / Код қате')
    existing=Customer.objects.filter(phone=phone).first()
    if existing:
        # Verification never overwrites a returning customer's name or consents.
        existing.phone_verified_at=now;existing.save(update_fields=['phone_verified_at'])
        audit('customer_phone_verified',customer=existing)
    return phone,existing
