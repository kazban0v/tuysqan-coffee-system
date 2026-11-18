"""Owner customer records and staff handling of guest feedback."""
import re
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import CharField, Count, F, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import services
from .models import AuditEvent, Customer, FeedbackHandling, LoyaltyEntry, LoyaltyPolicy, Order, Payment, Review
from .views import roles


def _page_context(section, ru, kz):
    return {'section':section, 'page_title':ru, 'page_title_kz':kz}


def _real_customers():
    # Walk-ins and synthetic accounts are not personal loyalty records.
    return Customer.objects.filter(is_test=False, phone__regex=r'^\+7\d{10}$')


def _customer_totals(query):
    payments = Payment.objects.filter(
        order__customer_id=OuterRef('pk'), order__is_test=False,
        order__payment_status='paid', reversed_at=None,
    ).exclude(order__status__in=['cancelled','rejected']).order_by().values('order__customer_id')
    ledger = LoyaltyEntry.objects.filter(customer_id=OuterRef('pk'), order__is_test=False).order_by().values('customer_id')
    return query.annotate(
        purchase_total=Coalesce(Subquery(payments.annotate(total=Sum('amount')).values('total')), Decimal('0')),
        purchase_count=Coalesce(Subquery(payments.annotate(total=Count('order_id', distinct=True)).values('total')), 0),
        last_paid_at=Subquery(payments.annotate(last=Max('created_at')).values('last')),
        loyalty_balance=Coalesce(Subquery(ledger.annotate(total=Sum('amount')).values('total')), Decimal('0')),
    )


def _loyalty_summary(customer, policy):
    total=max(Decimal('0'), customer.loyalty_balance)
    tiers=sorted(policy.tiers,key=lambda tier:Decimal(str(tier['threshold'])))
    customer.current_discount=max([0]+[int(tier['percent']) for tier in tiers if total>=Decimal(str(tier['threshold']))]) if policy.confirmed else 0
    upcoming=next((tier for tier in tiers if total<Decimal(str(tier['threshold']))), None)
    customer.next_percent=upcoming['percent'] if upcoming else None
    customer.remaining=max(Decimal('0'),Decimal(str(upcoming['threshold']))-total) if upcoming else Decimal('0')
    return customer


@roles('owner')
def clients(request):
    query=request.GET.get('q','').strip()[:120]
    customers=_real_customers()
    if query:
        match=Q(name__iregex=re.escape(query))
        digits=re.sub(r'\D','',query)
        if len(digits)==11 and digits.startswith('8'):digits='7'+digits[1:]
        if digits:match|=Q(phone__contains=digits)
        customers=customers.filter(match)
    sort=request.GET.get('sort','recent')
    sort_fields={'recent':'-created_at','spent':'-purchase_total','loyalty':'-loyalty_balance'}
    if sort not in sort_fields:sort='recent'
    page=Paginator(_customer_totals(customers).order_by(sort_fields[sort],'-pk'),25).get_page(request.GET.get('page'))
    policy=LoyaltyPolicy.get()
    for customer in page.object_list:_loyalty_summary(customer,policy)
    context=_page_context('clients','Клиенты','Клиенттер')
    context.update({'clients_page':page,'query':query,'sort':sort,'policy':policy,'total_clients':_real_customers().count()})
    return render(request,'admin_portal/clients.html',context)


@roles('owner')
def client_detail(request,pk):
    customer=get_object_or_404(_customer_totals(_real_customers()),pk=pk)
    policy=LoyaltyPolicy.get();_loyalty_summary(customer,policy)
    orders=customer.orders.filter(is_test=False).select_related('table').prefetch_related('items').order_by('-created_at','-pk')
    page=Paginator(orders,20).get_page(request.GET.get('page'))
    context=_page_context('clients','Карточка клиента','Клиент картасы')
    context.update({'client_record':customer,'orders_page':page,'policy':policy})
    return render(request,'admin_portal/client_detail.html',context)


FEEDBACK_VALUES=['entry_kind','order_pk','order_uuid','entry_created','customer_name','customer_phone','body','score','processing_status','processing_note','handled_name','handled_at','updated_name','processing_updated_at']


def _feedback_query(kind, query='', status='all'):
    if kind=='review':
        rows=Review.objects.filter(order__is_test=False,customer__is_test=False).annotate(
            entry_kind=Value('review',output_field=CharField()),order_pk=F('order_id'),order_uuid=F('order__public_id'),
            entry_created=F('created_at'),customer_name=F('customer__name'),customer_phone=F('customer__phone'),
            body=F('comment'),score=F('rating'),
        )
        fallback_status=F('status');fallback_note=F('staff_note')
    else:
        rows=Order.objects.filter(is_test=False,customer__is_test=False,guest_wish_at__isnull=False).exclude(guest_wish='').annotate(
            entry_kind=Value('wish',output_field=CharField()),order_pk=F('pk'),order_uuid=F('public_id'),
            entry_created=F('guest_wish_at'),customer_name=F('customer__name'),customer_phone=F('customer__phone'),
            body=F('guest_wish'),score=Value(None,output_field=IntegerField()),
        )
        fallback_status=Value('new');fallback_note=Value('')
    handling=FeedbackHandling.objects.filter(order_id=OuterRef('order_pk'),kind=kind)
    rows=rows.annotate(
        processing_status=Coalesce(Subquery(handling.values('status')[:1]),fallback_status,output_field=CharField()),
        processing_note=Coalesce(Subquery(handling.values('note')[:1]),fallback_note,output_field=CharField()),
        handled_name=Subquery(handling.values('handled_by__username')[:1]),
        handled_at=Subquery(handling.values('handled_at')[:1]),
        updated_name=Subquery(handling.values('updated_by__username')[:1]),
        processing_updated_at=Subquery(handling.values('updated_at')[:1]),
    )
    if status!='all':rows=rows.filter(processing_status=status)
    if query:
        match=Q(customer_name__iregex=re.escape(query))|Q(customer_phone__icontains=query)|Q(body__iregex=re.escape(query))
        digits=re.sub(r'\D','',query)
        if len(digits)==11 and digits.startswith('8'):digits='7'+digits[1:]
        if digits:match|=Q(customer_phone__contains=digits)
        rows=rows.filter(match)
    return rows.order_by().values(*FEEDBACK_VALUES)


@transaction.atomic
def _update_feedback(request):
    kind=request.POST.get('kind')
    status=request.POST.get('status')
    if kind not in ['review','wish'] or status not in ['new','viewed','handled']:
        raise ValidationError('Выберите вид обращения и статус обработки / Өтініш түрі мен өңдеу күйін таңдаңыз')
    try:order_pk=int(request.POST.get('order_id',''))
    except (TypeError,ValueError):raise ValidationError('Некорректный заказ / Тапсырыс қате')
    order=get_object_or_404(Order.objects.select_for_update(),pk=order_pk,is_test=False,customer__is_test=False)
    review=None
    if kind=='review':review=get_object_or_404(Review.objects.select_for_update(),order=order)
    elif not order.guest_wish_at or not order.guest_wish:raise Http404()
    note=services.bounded_text(request.POST.get('note',''),2000)
    record=FeedbackHandling.objects.select_for_update().filter(order=order,kind=kind).first()
    before={'status':record.status if record else review.status if review else 'new','note':record.note if record else review.staff_note if review else ''}
    if record is None:record=FeedbackHandling(order=order,kind=kind,updated_by=request.user)
    record.status=status;record.note=note;record.updated_by=request.user
    if status=='handled':record.handled_by=request.user;record.handled_at=timezone.now()
    record.save()
    if review:
        review.status=status;review.staff_note=note;review.save(update_fields=['status','staff_note'])
    services.audit('feedback_updated',request.user,order=order,before=before,
        after={'kind':kind,'review_id':review.pk if review else None,'status':status,'note':note,'handler_id':request.user.pk})


@roles('owner','manager')
@require_http_methods(['GET','POST'])
def feedback(request):
    error=''
    if request.method=='POST':
        try:_update_feedback(request)
        except ValidationError as exc:error=' '.join(exc.messages)
        else:
            messages.success(request,'Обращение обновлено / Өтініш жаңартылды')
            return redirect(request.get_full_path())
    kind=request.GET.get('kind','all');status=request.GET.get('status','all');query=request.GET.get('q','').strip()[:120]
    if kind not in ['all','review','wish']:kind='all'
    if status not in ['all','new','viewed','handled']:status='all'
    review_rows=_feedback_query('review',query,status);wish_rows=_feedback_query('wish',query,status)
    rows=review_rows if kind=='review' else wish_rows if kind=='wish' else review_rows.union(wish_rows,all=True)
    page=Paginator(rows.order_by('-entry_created','-order_pk','entry_kind'),20).get_page(request.GET.get('page'))
    for row in page.object_list:row['order_number']=f"T{row['order_pk']:04d}"
    context=_page_context('feedback','Отзывы и пожелания','Пікірлер мен ұсыныстар')
    context.update({'feedback_page':page,'kind':kind,'status':status,'query':query,'form_error':error})
    return render(request,'admin_portal/feedback.html',context,status=400 if error else 200)
