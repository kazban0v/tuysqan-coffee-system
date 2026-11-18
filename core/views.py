import json
import secrets
import statistics
from decimal import Decimal
from functools import wraps
from io import BytesIO
from urllib.parse import quote
import qrcode
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.core.paginator import Paginator
from django.db.models import Sum,Count,Q,Prefetch
from django.http import JsonResponse,HttpResponse,Http404
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_POST
from django.views.decorators.debug import sensitive_post_parameters
from django.utils import timezone
from django.utils.dateparse import parse_date,parse_datetime
from .models import *
from . import services as s
from .sms import SMSUnavailable
from .order_presentation import prepare_order_list

def customer(request): return Customer.objects.filter(pk=request.session.get('customer_id'),phone_verified_at__isnull=False).exclude(phone__startswith='guest-').first()
def claim_customer(request):
 claim_id=request.session.get('claim_customer_id')
 if not claim_id:return None
 claim=Customer.objects.filter(pk=claim_id,is_test=False).first()
 if claim is None:
  for key in ('claim_customer_id','claim_order_scope','claim_order_ids'):
   request.session.pop(key,None)
 return claim

def body(request):
 try:
  data=json.loads(request.body)
  if not isinstance(data,dict): raise ValueError()
  return data
 except (ValueError,UnicodeDecodeError): raise ValidationError('Некорректный JSON')
def api(fn):
 @wraps(fn)
 def wrapped(request,*args,**kwargs):
  try:return fn(request,*args,**kwargs)
  except SMSUnavailable as e:return JsonResponse({'error':str(e),'delivery_available':False},status=503)
  except ValidationError as e:
   payload={'error':' '.join(e.messages)}
   if getattr(e,'code',None) in ('offer_expired','offer_changed'):payload['code']=e.code
   return JsonResponse(payload,status=400)
  except PermissionDenied:return JsonResponse({'error':'Недостаточно прав / Рұқсат жоқ'},status=403)
  except (Order.DoesNotExist,MenuItem.DoesNotExist):return JsonResponse({'error':'Не найдено'},status=404)
  except IntegrityError:return JsonResponse({'error':'Повторная операция. Обновите страницу.'},status=409)
 return wrapped

def roles(*allowed):
 def decorator(fn):
  @wraps(fn)
  def wrapped(request,*a,**kw):
   if not request.user.is_authenticated:return redirect('/admin/login/')
   s.require_role(request.user,set(allowed));return fn(request,*a,**kw)
  return wrapped
 return decorator

FINAL_PHOTO_IDS=frozenset([1, 2, 6, 14, 15, 16, 26, 28, 30, 31, 32, 37, 47, 54, 56, 64, 66, 67, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163])

def catalog():
 return [{'id':i.pk,'slug':i.slug,'category_id':i.category_id,'category_slug':i.category.slug,'category_ru':i.category.name_ru,'category_kz':i.category.name_kz,'name_ru':i.name_ru,'name_kz':i.name_kz,'description_ru':i.description_ru,'description_kz':i.description_kz,'kind':i.kind,'price':str(i.price),'image':i.image,'photo_authoritative':i.pk in FINAL_PHOTO_IDS,'available':i.available,'is_test':i.is_test,'uncertainties':i.uncertainties} for i in MenuItem.objects.select_related('category').filter(available=True,is_test=False)]
def guest_orders_queryset(request):
 claim=claim_customer(request)
 if claim:return Order.objects.filter(customer=claim,public_id__in=request.session.get('claim_order_ids',[]))
 c=customer(request)
 return Order.objects.filter(customer=c) if c else Order.objects.none()

def table_context(request):
 token=request.session.get('table_token','')
 try: table=s.resolve_table(token) if token else None
 except ValidationError:table=None;token=''
 return {'table':table,'table_token':token}
def menu(request):
 if request.GET.get('view')=='menu' and 'table' not in request.GET:return redirect('/#menu')
 if 'table' in request.GET:
  try:s.resolve_table(request.GET['table'])
  except ValidationError:return HttpResponse('QR-ссылка недействительна / QR-сілтеме жарамсыз',status=400)
  return redirect('/table/'+quote(request.GET['table'],safe='')+'/')
 return render(request,'landing.html',{'ordering_enabled':False,'menu_presentation':[{**{k:v for k,v in item.items() if k not in ('id','available','is_test','uncertainties')},'photo_id':item['id']} for item in catalog()]})
def table_menu(request,token):
 try:table=s.resolve_table(token)
 except ValidationError:return HttpResponse('QR-ссылка недействительна / QR-сілтеме жарамсыз',status=400)
 if table.is_test:raise Http404()
 request.session['table_token']=token
 return render(request,'landing.html',{'menu_data':catalog(),'ordering_enabled':True,'table':table,'table_token':token,'guest_active_order_count':guest_orders_queryset(request).filter(status__in=['new','accepted','preparing','ready']).count()})
def checkout(request):
 context=table_context(request)
 if not context['table'] or context['table'].is_test:return HttpResponse('Откройте меню по QR-коду столика / Үстелдің QR-кодын ашыңыз',status=403)
 claim=claim_customer(request)
 if not claim and not customer(request):return redirect('/account/login/')
 return render(request,'checkout_classic.html' if request.GET.get('design')=='classic' else 'checkout.html',{'menu_data':catalog(),'checkout_discount_percent':0 if claim else s.applicable_discount_percent(customer(request)),**context})
def checkout_table(request):raise Http404()
def customer_login(request):
 context=table_context(request)
 if not context['table'] or context['table'].is_test:return HttpResponse('Откройте QR-код столика',status=403)
 if claim_customer(request) or customer(request):return redirect('/checkout/')
 return render(request,'customer_auth.html',{**context,'sms_available':settings.SMS_BACKEND!='disabled'})
@require_POST
@api
def otp_request(request):
 if not request.session.session_key:request.session.create()
 phone=s.begin_phone_otp(request.session.session_key,body(request).get('phone'))
 return JsonResponse({'ok':True,'phone':phone,'expires_in':300})
@require_POST
@api
def otp_verify(request):
 d=body(request);phone,c=s.verify_phone_otp(request.session.session_key,d.get('phone'),d.get('code'))
 request.session.cycle_key()
 if c:
  request.session['customer_id']=c.pk
  request.session.pop('verified_phone_pending',None)
  return JsonResponse({'needs_profile':False,'name':c.name,'redirect':'/checkout/'})
 request.session.pop('customer_id',None)
 request.session['verified_phone_pending']={'phone':phone,'at':timezone.now().timestamp()}
 return JsonResponse({'needs_profile':True})
@require_POST
@api
def profile_complete(request):
 pending=request.session.get('verified_phone_pending')
 if not pending or timezone.now().timestamp()-pending['at']>600:raise PermissionDenied()
 d=body(request);name=s.bounded_text(d.get('name',''),120)
 if not name or d.get('consent') is not True:raise ValidationError('Имя и согласие на обработку данных обязательны')
 now=timezone.now();marketing=d.get('marketing') is True
 c,created=Customer.objects.get_or_create(phone=pending['phone'],defaults={'name':name,'phone_verified_at':now,'consent_at':now,'marketing_consent':marketing,'marketing_consent_at':now if marketing else None,'is_test':False})
 request.session['customer_id']=c.pk;request.session.pop('verified_phone_pending',None)
 s.audit('customer_profile_completed',customer=c,after={'created':created})
 return JsonResponse({'redirect':'/checkout/','name':c.name})
@require_POST
@api
def language(request):
 value=body(request).get('language')
 if value not in ('ru','kz'):raise ValidationError('Язык не поддерживается')
 request.session['language']=value;return JsonResponse({'ok':True})
@require_POST
@api
def identify_customer(request):
 context=table_context(request)
 if not context['table'] or context['table'].is_test:raise PermissionDenied()
 d=body(request);phone=s.phone_normalize(d.get('phone'))
 # Lookup reveals no stored name, balances or order history.
 c=Customer.objects.filter(phone=phone,is_test=False).first()
 if c is None:
  name=s.bounded_text(d.get('name',''),120)
  if not name:return JsonResponse({'needs_name':True})
  if d.get('consent') is not True:raise ValidationError('Необходимо согласие на обработку данных')
  with transaction.atomic():
   c,_=Customer.objects.select_for_update().get_or_create(phone=phone,defaults={'name':name,'consent_at':timezone.now(),'marketing_consent':d.get('marketing') is True,'is_test':False})
   if c.is_test:
    # A real guest may reuse a phone from an old local test profile.
    # This does not verify phone ownership or change historical test orders.
    c.name=name
    c.is_test=False
    c.phone_verified_at=None
    c.consent_at=timezone.now()
    c.marketing_consent=d.get('marketing') is True
    c.marketing_consent_at=timezone.now() if c.marketing_consent else None
    c.save(update_fields=['name','is_test','phone_verified_at','consent_at','marketing_consent','marketing_consent_at'])
 elif d.get('consent') is not True:
  raise ValidationError('Необходимо согласие на обработку данных')
 request.session.pop('customer_id',None)
 request.session.pop('verified_phone_pending',None)
 request.session['claim_customer_id']=c.pk
 request.session.setdefault('claim_order_scope',secrets.token_hex(8))
 return JsonResponse({'needs_name':False,'redirect':'/checkout/'})

def discount_offer_context(request):
 return 'qr:'+str(request.session.session_key or '')+':'+str(request.session.get('table_token',''))

@api
def account_discount_offer(request):
 if request.method not in ('GET','POST'):return HttpResponse(status=405)
 context=table_context(request)
 if not context['table'] or context['table'].is_test:raise PermissionDenied()
 c=claim_customer(request) or customer(request)
 if not c:raise PermissionDenied()
 return JsonResponse({**s.discount_offer(c,context=discount_offer_context(request)),'exists':True,'needs_name':False},headers={'Cache-Control':'private, no-store'})

@require_POST
@api
def staff_discount_offer(request):
 s.require_role(request.user,{'owner','manager','cashier'})
 d=body(request);phone=s.phone_normalize(d.get('phone',''))
 c=Customer.objects.filter(phone=phone,is_test=False).first()
 return JsonResponse({**s.discount_offer(c,phone=phone,context=f'pos:{request.user.pk}'),'exists':c is not None,'needs_name':c is None},headers={'Cache-Control':'private, no-store'})

@require_POST
@api
def orders_create(request):
 d=body(request)
 context=table_context(request)
 if not context['table'] or context['table'].is_test:raise PermissionDenied()
 claim=claim_customer(request)
 c=claim or customer(request)
 if not c:
  return JsonResponse({'error':'Введите номер телефона ещё раз / Телефон нөміріңізді қайта енгізіңіз','redirect':'/account/login/'},status=401)
 if d.get('table_token')!=request.session.get('table_token'):raise ValidationError('QR-контекст изменился, откройте столик заново')
 if claim:
  key=s.bounded_text(d.get('idempotency_key',''),70)
  if len(key)<8:raise ValidationError('Нужен ключ повторной отправки')
  d['idempotency_key']='claim:'+request.session['claim_order_scope']+':'+key
 o,created=s.create_order(c,d,unverified_claim=bool(claim),discount_context=discount_offer_context(request))
 ids=request.session.get('claim_order_ids',[])
 if str(o.public_id) not in ids:request.session['claim_order_ids']=(ids+[str(o.public_id)])[-100:]
 return JsonResponse({'order':s.order_data(o),'redirect':f'/orders/{o.public_id}/','created':created},status=201 if created else 200)
def own_order(request,public_id):
 if claim_customer(request):
  if str(public_id) not in request.session.get('claim_order_ids',[]):raise PermissionDenied()
  return get_object_or_404(Order,public_id=public_id)
 c=customer(request)
 if not c:raise PermissionDenied()
 return get_object_or_404(Order,public_id=public_id,customer=c)
def order_page(request,public_id):
 o=own_order(request,public_id);s.mark_delays();return render(request,'order.html',{'order':s.order_data(o)})
@api
def order_api(request,public_id):
 o=own_order(request,public_id);s.mark_delays();return JsonResponse({'order':s.order_data(o)})
def guest_loyalty_context(request):
 configured_policy=LoyaltyPolicy.get()
 tiers=[dict(tier) for tier in sorted(configured_policy.tiers,key=lambda tier:Decimal(str(tier['threshold'])))]
 claim=claim_customer(request);c=None if claim else customer(request)
 policy=LoyaltyPolicy.objects.filter(pk=1,confirmed=True).first()
 verified=bool(c and not c.is_test and policy)
 if verified:
  total=max(Decimal('0'),c.loyalty_total);percent=s.eligible_discount_percent(c)
 else:
  # Only payments on orders this session is allowed to see, never a phone lookup.
  visible=guest_orders_queryset(request).filter(payment_status='paid',is_test=False).exclude(status__in=['cancelled','rejected'])
  total=max(Decimal('0'),visible.aggregate(amount=Sum('actual_paid'))['amount'] or Decimal('0'))
  # The rate is public in the approved phone offer; private history remains session-scoped.
  percent=s.eligible_discount_percent(claim) if claim else 0
 # Session payments cannot stand in for the customer's full loyalty ledger.
 level_total=c.loyalty_total if verified else claim.loyalty_total if claim else Decimal('0')
 upcoming=next((t for t in tiers if Decimal(str(t['threshold']))>level_total),None) if policy else None
 remaining=None;progress=None
 if verified:
  previous=max([Decimal('0')]+[Decimal(str(t['threshold'])) for t in tiers if Decimal(str(t['threshold']))<=total])
  remaining=Decimal(str(upcoming['threshold']))-total if upcoming else Decimal('0')
  progress=min(100,int((total-previous)/(Decimal(str(upcoming['threshold']))-previous)*100)) if upcoming else 100
 active=guest_orders_queryset(request).exclude(status__in=['served','cancelled','rejected'])
 current=active.aggregate(amount=Sum('total'))['amount'] or Decimal('0')
 personal={'total':total,'balance':total if verified else None,'percent':percent,'verified':verified,'browser_scope':bool(claim),'next_percent':upcoming['percent'] if upcoming else None,'remaining':remaining,'progress':progress}
 uses={u.threshold:u for u in (c.loyalty_redemptions.filter(active=True) if verified else [])}
 for tier in tiers:
  use=uses.get(Decimal(str(tier['threshold'])))
  tier['used']=bool(use and use.consumed_at);tier['reserved']=bool(use and not use.consumed_at)
  tier['reached']=verified and total>=Decimal(str(tier['threshold']));tier['current']=tier['percent']==percent and percent>0
 return {'tiers':tiers,'personal':personal,'max_percent':tiers[-1]['percent'] if tiers else 0,'orders_summary':{'count':active.count(),'total':current,'browser_paid':total if claim else None}}

def account(request):
 if not claim_customer(request) and not customer(request):return redirect('/account/login/')
 orders=guest_orders_queryset(request).select_related('table','customer')[:100]
 return render(request,'account.html',{'orders':[s.order_data(o) for o in prepare_order_list(orders)],'loyalty':guest_loyalty_context(request),**table_context(request)})

def guest_receipt(request,public_id):
 o=own_order(request,public_id)
 response=render(request,'guest_receipt.html',{'receipt':s.order_data(o),'receipt_has_discount':o.discount_amount>0,'receipt_created_at':o.created_at,'receipt_paid_at':o.paid_at,'receipt_table_kz':str(o.table or '').replace('Стол ','Үстел ')})
 response['Cache-Control']='private, no-store'
 response['X-Robots-Tag']='noindex, nofollow'
 return response

@require_POST
@api
@transaction.atomic
def mascot_update(request,public_id):
 allowed=own_order(request,public_id)
 o=Order.objects.select_for_update().get(pk=allowed.pk)
 d=body(request);action=d.get('action')
 if action=='dismiss':
  created=not o.mascot_dismissed_at
  if created:
   o.mascot_dismissed_at=timezone.now();o.save(update_fields=['mascot_dismissed_at'])
  return JsonResponse({'ok':True,'created':created,'mascot':s.mascot_state(o)})
 if action!='wish':raise ValidationError('Неизвестное действие / Әрекет белгісіз')
 comment=s.bounded_text(d.get('comment',''),1000)
 if not comment:raise ValidationError('Напишите пожелание / Ұсынысыңызды жазыңыз')
 if o.guest_wish_at:return JsonResponse({'ok':True,'created':False,'mascot':s.mascot_state(o)})
 if o.status not in ('new','accepted','preparing','ready') or o.mascot_dismissed_at:raise ValidationError('Пожелание сейчас недоступно / Ұсыныс қазір қолжетімсіз')
 o.guest_wish=comment;o.guest_wish_at=timezone.now();o.save(update_fields=['guest_wish','guest_wish_at'])
 return JsonResponse({'ok':True,'created':True,'mascot':s.mascot_state(o)},status=201)

@require_POST
@api
@transaction.atomic
def review_create(request,public_id):
 allowed=own_order(request,public_id);o=Order.objects.select_for_update().get(pk=allowed.pk);d=body(request)
 if o.status!='served':raise ValidationError('Отзыв доступен после выдачи / Пікір тапсырыс ұсынылғаннан кейін қолжетімді')
 rating=d.get('rating')
 if isinstance(rating,bool) or not isinstance(rating,(int,str)) or str(rating) not in ('1','2','3','4','5'):raise ValidationError('Оценка от 1 до 5 / Баға 1-ден 5-ке дейін')
 kind=d.get('kind','experience')
 if kind not in ('service','experience'):raise ValidationError('Неверный вид отзыва')
 comment=s.bounded_text(d.get('comment',''),2000)
 r,created=Review.objects.get_or_create(order=o,defaults={'customer':o.customer,'rating':int(rating),'comment':comment,'kind':kind})
 return JsonResponse({'ok':True,'created':created})
@sensitive_post_parameters('password')
def staff_login(request):
 error=''
 if request.method=='POST':
  user=authenticate(request,username=request.POST.get('username'),password=request.POST.get('password'))
  if user and s.role_of(user):
   from .developer_access import is_developer
   login(request,user)
   return redirect('/developer/' if is_developer(user) else '/admin/kitchen/' if s.role_of(user)=='kitchen' else '/admin/' if s.role_of(user)=='owner' else '/admin/cashier/')
  error='Неверные данные / Деректер қате'
 return render(request,'staff_login.html',{'error':error})
@require_POST
def staff_logout(request):logout(request);return redirect('/')
@roles('owner','manager','cashier')
def cashier(request):
 s.mark_delays();return render(request,'cashier_classic.html' if request.GET.get('design')=='classic' else 'cashier.html',{'kitchen_release':AppSettings.get().kitchen_release,'orders':[s.order_data(o,True) for o in prepare_order_list(Order.objects.filter(is_test=False).select_related('customer','table')[:100],True)],'menu_data':catalog(),'tables':Table.objects.filter(active=True,is_test=False)})
@api
def staff_orders(request):
 s.require_role(request.user,{'owner','manager','cashier'});s.mark_delays();return JsonResponse({'kitchen_release':AppSettings.get().kitchen_release,'orders':[s.order_data(o,True) for o in prepare_order_list(Order.objects.filter(is_test=False).select_related('customer','table')[:100],True)]})
@require_POST
@api
def staff_action(request,public_id):
 d=body(request);o=s.act_on_order(public_id,request.user,d.get('action'),d,channel='telegram_stub' if d.get('channel')=='telegram_stub' else 'web')
 return JsonResponse({'ok':True,'order':kitchen_data(o) if s.role_of(request.user)=='kitchen' else s.order_data(o,True)})
def kitchen_data(o):
 food=o._kitchen_food if hasattr(o,'_kitchen_food') else list(o.items.filter(kind='food'))
 return {'public_id':str(o.public_id),'number':o.number,'table':str(o.table or ('С собой' if o.source=='pos' else '')),'status':o.status,'is_delayed':bool(o.food_eta_at and o.food_eta_at<timezone.now() and any(item.status!='ready' for item in food)),'eta_at':o.food_eta_at.isoformat() if o.food_eta_at else None,'food_eta_at':o.food_eta_at.isoformat() if o.food_eta_at else None,'food_eta_minutes':o.food_eta_minutes,'created_at':o.created_at.isoformat(),'comment':o.comment,'items':[{'id':i.pk,'name_ru':i.name_ru,'name_kz':i.name_kz,'quantity':i.quantity,'comment':i.comment,'status':i.status,'kind':'food','eta_at':i.eta_at.isoformat() if i.eta_at else None,'eta_minutes':i.eta_minutes} for i in food]}
@roles('owner','manager','kitchen')
def kitchen(request):s.mark_delays();return render(request,'kitchen.html',{'orders':[kitchen_data(o) for o in s.kitchen_queue().filter(is_test=False).select_related('table').prefetch_related(Prefetch('items',queryset=OrderItem.objects.filter(kind='food'),to_attr='_kitchen_food'))]})
@api
def kitchen_api(request):s.require_role(request.user,{'owner','manager','kitchen'});s.mark_delays();return JsonResponse({'orders':[kitchen_data(o) for o in s.kitchen_queue().filter(is_test=False).select_related('table').prefetch_related(Prefetch('items',queryset=OrderItem.objects.filter(kind='food'),to_attr='_kitchen_food'))]})
def analytics(request):
 q=Order.objects.filter(is_test=False);start=request.GET.get('start');end=request.GET.get('end')
 if start:q=q.filter(created_at__date__gte=parse_date(start))
 if end:q=q.filter(created_at__date__lte=parse_date(end))
 real=q.filter(is_test=False,payment_status='paid').exclude(status__in=['cancelled','rejected'])
 durations=[o.preparation_minutes for o in q if o.preparation_minutes is not None]
 delayed=q.filter(Q(was_delayed=True)|Q(status__in=['accepted','preparing'],eta_at__lt=timezone.now())).count()
 return {'count':q.count(),'new':q.filter(status='new').count(),'active':q.filter(status__in=['accepted','preparing']).count(),'ready':q.filter(status='ready').count(),'delayed':delayed,'delayed_share':round(100*delayed/q.count(),1) if q.count() else 0,'confirmed_payments':str(real.aggregate(n=Sum('actual_paid'))['n'] or 0),'demo_payments':str(q.filter(is_test=True,payment_status='paid').aggregate(n=Sum('actual_paid'))['n'] or 0),'average_minutes':round(statistics.mean(durations),1) if durations else None,'median_minutes':statistics.median(durations) if durations else None,'new_customers':Customer.objects.filter(is_test=False).count(),'new_reviews':Review.objects.filter(status='new').count(),'by_method':list(real.values('payment_method').annotate(total=Sum('actual_paid'))),'by_date':list(real.values('paid_at__date').annotate(total=Sum('actual_paid'))),'popular':list(OrderItem.objects.filter(order__in=real).values('name_ru','name_kz').annotate(quantity=Sum('quantity')).order_by('-quantity')[:20]),'repeat_guests':Customer.objects.annotate(n=Count('orders',filter=Q(orders__in=real))).filter(n__gte=2).count(),'tiers':[{'percent':p,'count':sum(c.discount_percent==p for c in Customer.objects.filter(is_test=False))} for p in [0,5,7,10,12,15]]}
@roles('owner','manager')
def dashboard(request):
 for key in ['start','end']:
  value=request.GET.get(key)
  if value:
   try: valid=parse_date(value)
   except ValueError: valid=None
   if not valid:return HttpResponse('Некорректная дата / Күн қате',status=400)
 return render(request,'dashboard.html',{'stats':analytics(request),'orders':[s.order_data(o,True) for o in Order.objects.all()[:20]]})
@roles('owner')
def customers(request):return render(request,'customers.html',{'customers':Customer.objects.filter(is_test=False)})
@roles('owner','manager')
def reviews(request):
 q=Review.objects.select_related('order','customer')
 if request.GET.get('low'):q=q.filter(rating__lte=2)
 if request.method=='POST':
  r=get_object_or_404(Review,pk=request.POST.get('id'));status=request.POST.get('status')
  if status not in ['new','viewed','handled']:raise ValidationError('Неверный статус')
  r.status=status;r.staff_note=s.bounded_text(request.POST.get('staff_note',''),2000);r.save();s.audit('review_updated',request.user,order=r.order,after={'status':status})
 return render(request,'reviews.html',{'reviews':q,'wishes':Order.objects.filter(guest_wish_at__isnull=False).order_by('-guest_wish_at')[:100]})
@roles('owner')
def settings_page(request):
 setting=AppSettings.get();policy=LoyaltyPolicy.get()
 if request.method=='POST':
  value=request.POST.get('kitchen_release')
  if value in ['acceptance','payment']:
   before=setting.kitchen_release;setting.kitchen_release=value;setting.save();s.audit('settings_kitchen_release',request.user,before={'value':before},after={'value':value})
 return render(request,'settings.html',{'settings':setting,'policy':policy,'tables':Table.objects.filter(is_test=False),'menu_items':MenuItem.objects.select_related('category').all(),'staff_users':__import__('django.contrib.auth',fromlist=['get_user_model']).get_user_model().objects.filter(groups__name__in=s.ROLES,is_active=True).distinct()})
@roles('owner')
def audit_page(request):return render(request,'audit.html',{'events':AuditEvent.objects.select_related('actor','order')[:200]})
@roles('owner','manager','cashier')
def telegram(request):return render(request,'telegram.html',{'notifications':OutboxMessage.objects.select_related('order')[:100]})
@roles('owner')
def qr(request,table_id):
 table=get_object_or_404(Table,pk=table_id);url=request.build_absolute_uri('/table/'+quote(table.token(),safe='')+'/');buf=BytesIO();qrcode.make(url).save(buf,format='PNG');return HttpResponse(buf.getvalue(),content_type='image/png')
@require_POST
@api
def pos_create(request):
 s.require_role(request.user,{'owner','manager','cashier'});d=body(request)
 o,created=s.create_pos_order(request.user,d)
 return JsonResponse({'order':s.order_data(o,True),'created':created,'print_url':f'/admin/orders/{o.public_id}/print/'},status=201 if created else 200)



@api
def pos_status(request):
 s.require_role(request.user,{'owner','manager','cashier'})
 key=s.bounded_text(request.GET.get('key',''),70)
 if len(key)<8: raise ValidationError('Нужен ключ сохранения заказа')
 o=Order.objects.select_related('customer','table').filter(source='pos',is_test=False,idempotency_key=f'pos:{request.user.pk}:{key}').first()
 if o is None: return JsonResponse({'error':'Заказ не найден'},status=404)
 return JsonResponse({'order':s.order_data(o,True),'print_url':f'/admin/orders/{o.public_id}/print/'})

@api
def staff_order_detail(request,public_id):
 s.require_role(request.user,{'owner','manager','cashier'})
 o=get_object_or_404(Order.objects.select_related('customer','table'),public_id=public_id,is_test=False)
 return JsonResponse({'order':s.order_data(o,True),'kitchen_release':AppSettings.get().kitchen_release})

@roles('owner','manager','cashier')
def order_print(request,public_id):
 o=get_object_or_404(Order.objects.select_related('customer','table'),public_id=public_id,is_test=False)
 labels={'new':('Новый','Жаңа'),'accepted':('Принят','Қабылданды'),'preparing':('Готовится','Дайындалуда'),'ready':('Готов','Дайын'),'served':('Выдан','Берілді'),'cancelled':('Отменён','Бас тартылды'),'rejected':('Отклонён','Қабылдамады'),'unpaid':('Не оплачен','Төленбеген'),'paid':('Оплачен','Төленген'),'refunded':('Оплата отменена','Төлем қайтарылды')}
 index=1 if request.session.get('language')=='kz' else 0
 data=s.order_data(o,True)
 for payment in data.get('payment_history',[]):
  payment['created_at_display']=parse_datetime(payment['created_at'])
  payment['reversed_at_display']=parse_datetime(payment['reversed_at']) if payment['reversed_at'] else None
 return render(request,'order_print.html',{'order':data,'payment_history_reversed':any(p['reversed_at'] for p in data.get('payment_history',[])),'order_created_at':o.created_at,'print_status':labels[o.status][index],'print_payment_status':labels[o.payment_status][index],'print_table':str(o.table or '').replace('Стол ','Үстел ') if index else str(o.table or '')})

@roles('owner','manager','cashier')
def pos_page(request):
 from .menu_compositions import pos_composition
 items=catalog()
 for item in items:item['composition']=pos_composition(item)
 return render(request,'pos.html',{'menu_data':items,'tables':Table.objects.filter(active=True,is_test=False)})

def admin_portal(request):
 role=s.role_of(request.user)
 if not role:return redirect('/admin/login/')
 if role=='kitchen':return redirect('/admin/kitchen/')
 if role=='cashier':return redirect('/admin/cashier/')
 from .admin_portal import overview
 return overview(request)


@roles('owner','manager','cashier')
def receipts(request):
 query=request.GET.get('q','').strip()[:120]
 source=request.GET.get('source','all')
 method=request.GET.get('method','all')
 status=request.GET.get('status','all')
 period=request.GET.get('period','all')
 if source not in ('all','web','pos') or method not in ('all','cash','kaspi','halyk') or status not in ('all','paid','unpaid','refunded','cancelled') or period not in ('all','today','yesterday'):
  return HttpResponse('Некорректный фильтр / Сүзгі қате',status=400)
 q=Order.objects.filter(is_test=False).select_related('table','customer')
 if query:
  condition=Q(table__name__icontains=query)|Q(customer__name__icontains=query)|Q(customer__phone__icontains=query)
  digits=query.upper().lstrip('#').lstrip('T')
  if digits.isdigit() and len(digits)<15:condition|=Q(pk=int(digits))
  q=q.filter(condition)
 if source!='all':q=q.filter(source=source)
 if method!='all':q=q.filter(payment_method=method)
 start_text=request.GET.get('start','');end_text=request.GET.get('end','')
 try:
  start=parse_date(start_text) if start_text else None
  end=parse_date(end_text) if end_text else None
 except ValueError:return HttpResponse('Некорректная дата / Күн қате',status=400)
 if (start_text and start is None) or (end_text and end is None) or (start and end and start>end):return HttpResponse('Проверьте даты / Күндерді тексеріңіз',status=400)
 if start or end:
  if start:q=q.filter(created_at__date__gte=start)
  if end:q=q.filter(created_at__date__lte=end)
 elif period in ('today','yesterday'):
  from datetime import timedelta
  day=timezone.localdate()-timedelta(days=1 if period=='yesterday' else 0)
  q=q.filter(created_at__date=day)
 paid=q.filter(payment_status='paid').exclude(status__in=['cancelled','rejected'])
 unpaid=q.filter(payment_status='unpaid').exclude(status__in=['cancelled','rejected'])
 counts={'all':q.count(),'paid':paid.count(),'unpaid':unpaid.count(),'refunded':q.filter(payment_status='refunded').count(),'cancelled':q.filter(status__in=['cancelled','rejected']).count()}
 confirmed=paid.aggregate(total=Sum('actual_paid'))['total'] or Decimal('0')
 if status=='paid':q=paid
 elif status=='unpaid':q=unpaid
 elif status=='refunded':q=q.filter(payment_status='refunded')
 elif status=='cancelled':q=q.filter(status__in=['cancelled','rejected'])
 page=Paginator(q.order_by('-created_at','-pk'),20).get_page(request.GET.get('page'))
 rows=[]
 for order in page.object_list:
  takeaway=order.source=='pos' and order.table_id is None
  rows.append({'order':order,'place_ru':'С собой' if takeaway else str(order.table or 'Касса'),'place_kz':'Өзімен алып кету' if takeaway else str(order.table or 'Касса').replace('Стол ','Үстел ')})
 def link(**changes):
  params=request.GET.copy();params.pop('page',None)
  for key,value in changes.items():
   if value is None:params.pop(key,None)
   else:params[key]=str(value)
  return '?'+params.urlencode()
 tabs=[{'key':key,'ru':ru,'kz':kz,'count':counts[key],'url':link(status=key)} for key,ru,kz in [('all','Все','Барлығы'),('paid','Оплачены','Төленген'),('unpaid','Ожидают оплаты','Төлем күтілуде'),('refunded','Оплата отменена','Төлем қайтарылды'),('cancelled','Заказы отменены','Бас тартылған')]]
 presets=[{'key':key,'ru':ru,'kz':kz,'url':link(period=key,start=None,end=None)} for key,ru,kz in [('all','Весь период','Барлық кезең'),('today','Сегодня','Бүгін'),('yesterday','Вчера','Кеше')]]
 context={'rows':rows,'page_obj':page,'counts':counts,'confirmed_total':confirmed,'tabs':tabs,'presets':presets,'query':query,'source_filter':source,'method_filter':method,'status_filter':status,'period_filter':period,'start':start_text,'end':end_text,'filters_active':bool(source!='all' or method!='all' or start or end),'previous_url':link(page=page.previous_page_number()) if page.has_previous() else '', 'next_url':link(page=page.next_page_number()) if page.has_next() else ''}
 return render(request,'receipts.html',context)

@roles('owner','manager','cashier')
def mascot_preview(request):
 state=request.GET.get('state','preparing')
 if state not in ('preparing','served','feedback'):raise Http404()
 preview={'public_id':'preview','status':'preparing' if state=='preparing' else 'served','mascot':{'state':state,'dismissed':False,'wish_sent':False,'review_sent':False,'feedback_due_at':None},'preview':True}
 return render(request,'mascot_preview.html',{'preview_order':preview,'preview_label':{'preparing':'Готовим заказ','served':'Приятного аппетита','feedback':'Приглашение к отзыву'}[state]})
