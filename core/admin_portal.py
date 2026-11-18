"""Local owner/manager workspace. Operational order changes stay in services."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import uuid
import re

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum, Q, Exists, OuterRef, F
from django.db.models.functions import TruncDate
from django.http import HttpResponseBadRequest, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify

from .models import Order, OrderItem, Payment, MenuItem, MenuCategory, Table, AppSettings, LoyaltyPolicy, AuditEvent
from . import services as service
from .views import roles


def page(request, template, section, title, kz, **context):
    return render(request,'admin_portal/'+template+'.html',dict(section=section,page_title=title,page_title_kz=kz,**context))


def posted_id(request,name):
    value=request.POST.get(name,'')
    if not value.isdigit():raise Http404()
    return int(value)


def dates(request, days=7):
    today=timezone.localdate()
    try:
        start=parse_date(request.GET.get('start','')) if request.GET.get('start') else today-timedelta(days=days-1)
        end=parse_date(request.GET.get('end','')) if request.GET.get('end') else today
        if not start or not end or start>end:raise ValueError()
    except (ValueError,TypeError):raise forms.ValidationError('Укажите корректный диапазон дат / Күндер аралығын дұрыс көрсетіңіз')
    return start,end


def order_query():
    food=OrderItem.objects.filter(order_id=OuterRef('pk'),kind='food').exclude(status='ready')
    drinks=OrderItem.objects.filter(order_id=OuterRef('pk'),kind='drink').exclude(status='ready')
    return Order.objects.filter(is_test=False).select_related('customer','table').annotate(food_open=Exists(food),drink_open=Exists(drinks))


def delayed_query(query):
    now=timezone.now()
    return query.filter(status__in=['accepted','preparing']).filter(
        Q(food_eta_at__lt=now,food_open=True)|Q(drink_eta_at__lt=now,drink_open=True)|
        (Q(food_eta_at__isnull=True,drink_eta_at__isnull=True,eta_at__lt=now)&(Q(food_open=True)|Q(drink_open=True))))


def payment_stats(start,end):
    payments=Payment.objects.filter(order__is_test=False)
    received=payments.filter(created_at__date__range=(start,end))
    refunded=payments.filter(reversed_at__date__range=(start,end))
    gross=received.aggregate(n=Sum('amount'))['n'] or Decimal('0')
    returns=refunded.aggregate(n=Sum('amount'))['n'] or Decimal('0')
    count=received.count()
    return dict(gross=gross,refunds=returns,net=gross-returns,paid_count=count,average=gross/count if count else Decimal('0'))


@roles('owner','manager')
def overview(request):
    if request.GET.get('start') or request.GET.get('end'):
        try:dates(request)
        except forms.ValidationError as error:return HttpResponseBadRequest(error.messages[0])
        return redirect('/admin/analytics/?'+request.GET.urlencode())
    today=timezone.localdate();query=order_query()
    stats=payment_stats(today,today)
    stats.update(active=query.filter(status__in=['new','accepted','preparing','ready']).count(),unpaid=query.filter(payment_status='unpaid').exclude(status__in=['cancelled','rejected']).count(),delayed=delayed_query(query).count())
    attention=attention_groups(query,5)
    return page(request,'overview','overview','Обзор кофейни','Кофеханаға шолу',stats=stats,today=today,recent=query[:6],attention=attention)


@roles('owner','manager')
def orders(request):
    query=order_query().prefetch_related('items')
    term=request.GET.get('q','').strip()[:120];status=request.GET.get('status','');source=request.GET.get('source','')
    if term:
        match=Q(customer__name__iregex=re.escape(term))|Q(customer__phone__icontains=term)|Q(table__name__iregex=re.escape(term))
        digits=re.sub(r'\D','',term)
        if len(digits)==11 and digits.startswith('8'):digits='7'+digits[1:]
        if digits and not re.fullmatch(r'#?T\d+',term.upper()):match|=Q(customer__phone__contains=digits)
        number=term.upper().lstrip('#T')
        if number.isdigit():match|=Q(pk=int(number))
        query=query.filter(match)
    if status in dict(Order.STATUSES):query=query.filter(status=status)
    if source in ['web','pos']:query=query.filter(source=source)
    start=request.GET.get('start','');end=request.GET.get('end','')
    if start or end:
        try:
            first,last=dates(request,days=3650)
        except forms.ValidationError as error:return HttpResponseBadRequest(error.messages[0])
        query=query.filter(created_at__date__range=(first,last))
    return page(request,'orders','orders','Заказы','Тапсырыстар',order_page=Paginator(query,25).get_page(request.GET.get('page')),statuses=Order.STATUSES,filters=dict(q=term,status=status,source=source,start=start,end=end),querystring=request.GET.urlencode())


@roles('owner','manager')
def order_detail(request,public_id):
    order=get_object_or_404(order_query().prefetch_related('items__menu_item'),public_id=public_id)
    data=service.order_data(order,True)
    return page(request,'order_detail','orders','Заказ '+order.number,'Тапсырыс '+order.number,order=order,order_info=data,events=order.events.select_related('actor')[:30],payments=order.payments.select_related('confirmed_by').all())


def attention_groups(query,minutes):
    return [
        dict(key='waiting',title='Долго не принят',kz='Ұзақ уақыт қабылданбаған',count=query.filter(status='new',created_at__lt=timezone.now()-timedelta(minutes=minutes)).count()),
        dict(key='delayed',title='Задержка приготовления',kz='Дайындау кешігуде',count=delayed_query(query).count()),
        dict(key='unpaid',title='Подан, но не оплачен',kz='Ұсынылған, бірақ төленбеген',count=query.filter(status='served',payment_status='unpaid').count()),
    ]


@roles('owner','manager')
def attention(request):
    try:minutes=max(1,min(120,int(request.GET.get('minutes','5'))))
    except ValueError:minutes=5
    query=order_query();groups=attention_groups(query,minutes);kind=request.GET.get('kind','waiting')
    if kind=='delayed':query=delayed_query(query)
    elif kind=='unpaid':query=query.filter(status='served',payment_status='unpaid')
    else:kind='waiting';query=query.filter(status='new',created_at__lt=timezone.now()-timedelta(minutes=minutes))
    return page(request,'attention','attention','Контроль ошибок','Мәселелерді бақылау',groups=groups,kind=kind,minutes=minutes,order_page=Paginator(query,25).get_page(request.GET.get('page')))


@roles('owner','manager')
def analytics(request):
    try:start,end=dates(request)
    except forms.ValidationError as error:return HttpResponseBadRequest(error.messages[0])
    stats=payment_stats(start,end)
    query=order_query().filter(created_at__date__range=(start,end))
    paid=order_query().filter(payment_status='paid',paid_at__date__range=(start,end)).exclude(status__in=['cancelled','rejected'])
    stats['orders']=query.count();stats['delayed']=query.filter(Q(was_delayed=True)|Q(pk__in=delayed_query(query).values('pk'))).count()
    timings=list(query.filter(accepted_at__isnull=False,ready_at__isnull=False).values_list('accepted_at','ready_at'))
    stats['minutes']=round(sum((end_at-start_at).total_seconds()/60 for start_at,end_at in timings)/len(timings),1) if timings else None
    stats['repeat_guests']=paid.values('customer_id').annotate(n=Count('id')).filter(n__gte=2).count()
    receipts=Payment.objects.filter(order__is_test=False,created_at__date__range=(start,end))
    daily=receipts.annotate(day=TruncDate('created_at')).values('day').annotate(total=Sum('amount'),count=Count('id')).order_by('day')
    methods=receipts.values('method').annotate(total=Sum('amount'),count=Count('id')).order_by('-total')
    # line_total is a Python property, so aggregate quantity × immutable unit-price snapshots.
    popular=OrderItem.objects.filter(order__in=paid).values('name_ru','name_kz','kind').annotate(sales=Sum(F('quantity')*F('unit_price')),quantity=Sum('quantity')).order_by('-quantity')[:12]
    return page(request,'analytics','analytics','Аналитика','Талдау',stats=stats,start=start,end=end,daily=daily,methods=methods,popular=popular)


ACTION_LABELS={'drinks_start':'Начал приготовление напитков','drink_notice_seen':'Просмотрел рекомендацию напитков','accept':'Принял заказ','accept_and_pay':'Принял заказ и оплату','payment_confirmed':'Подтвердил оплату','payment_reversed':'Отменил оплату','ready':'Подтвердил готовность заказа','serve':'Отметил подачу','food_eta':'Назначил время блюд','drink_eta':'Назначил время напитков','item_ready':'Отметил готовность позиции','discount_confirmed':'Изменил скидку','review_updated':'Обработал отзыв','feedback_updated':'Обработал обращение','menu_item_updated':'Изменил позицию меню','menu_item_created':'Добавил позицию меню','menu_availability':'Изменил стоп-лист','category_updated':'Изменил категорию','category_created':'Добавил категорию','employee_created':'Создал сотрудника','employee_blocked':'Заблокировал сотрудника','employee_unblocked':'Разблокировал сотрудника','loyalty_policy_updated':'Изменил программу скидок','settings_kitchen_release':'Изменил передачу на кухню','table_updated':'Изменил столик'}
ACTION_LABELS.update({'order_created':'Создал заказ','loyalty_purchase':'Начислил накопления','loyalty_reversal':'Отменил начисление','loyalty_reconciled':'Восстановил накопления','customer_phone_verified':'Подтвердил телефон','customer_profile_completed':'Заполнил профиль','preparing':'Начал приготовление','item_preparing':'Начал готовить позицию','drinks_ready':'Отметил готовность напитков','cancel':'Отменил заказ','reject':'Отклонил заказ','correct':'Изменил состав заказа','eta':'Изменил время напитков'})


@roles('owner')
def audit(request):
    query=AuditEvent.objects.select_related('actor','order','customer')
    term=request.GET.get('q','').strip()[:120];action=request.GET.get('action','')
    if term:query=query.filter(Q(actor__username__icontains=term)|Q(reason__icontains=term)|Q(action__icontains=term))
    if action:query=query.filter(action=action)
    if request.GET.get('start') or request.GET.get('end'):
        try:start,end=dates(request,3650)
        except forms.ValidationError as error:return HttpResponseBadRequest(error.messages[0])
        query=query.filter(created_at__date__range=(start,end))
    event_page=Paginator(query,30).get_page(request.GET.get('page'))
    from .audit_presentation import present_events
    present_events(event_page)
    return page(request,'audit','audit','Журнал действий','Әрекеттер журналы',event_page=event_page,actions=sorted(ACTION_LABELS.items()),filters=dict(q=term,action=action,start=request.GET.get('start',''),end=request.GET.get('end','')))


class TranslatedSelect(forms.Select):
    labels={'food':('Блюдо','Тағам'),'drink':('Напиток','Сусын'),'acceptance':('После принятия','Қабылдағаннан кейін'),'payment':('После оплаты','Төлемнен кейін')}
    def create_option(self,name,value,label,selected,index,subindex=None,attrs=None):
        option=super().create_option(name,value,label,selected,index,subindex,attrs)
        instance=getattr(value,'instance',None)
        pair=(instance.name_ru,instance.name_kz) if instance else self.labels.get(str(value))
        if pair:option['attrs'].update({'data-ru':pair[0],'data-kz':pair[1]})
        return option


class MenuForm(forms.ModelForm):
    photo=forms.ImageField(required=False,label='Фотография / Фото')
    class Meta:
        model=MenuItem
        fields=['name_ru','name_kz','description_ru','description_kz','category','kind','price','available']
        widgets={'description_ru':forms.Textarea(attrs={'rows':3}),'description_kz':forms.Textarea(attrs={'rows':3}),'category':TranslatedSelect(),'kind':TranslatedSelect()}
    def clean_photo(self):
        photo=self.cleaned_data.get('photo')
        if photo and (photo.size>5*1024*1024 or photo.image.format not in ('JPEG','PNG','WEBP') or photo.image.width*photo.image.height>20000000):raise forms.ValidationError('JPEG, PNG или WebP до 5 МБ и 20 мегапикселей')
        return photo


class CategoryForm(forms.ModelForm):
    class Meta:model=MenuCategory;fields=['name_ru','name_kz','sort_order']


def menu_snapshot(item):return {field:str(getattr(item,field)) for field in ['id','name_ru','name_kz','price','category_id','kind','available','image']}


@roles('owner')
def menu(request):
    selected=MenuItem.objects.filter(pk=request.GET.get('edit')).first() if request.GET.get('edit','').isdigit() else None
    if selected:selected.image_url=selected.image if selected.image.startswith('/') else '/static/'+selected.image if selected.image else ''
    form=MenuForm(instance=selected);category_form=CategoryForm();error=''
    if request.method=='POST':
        action=request.POST.get('action','save')
        if action=='category':
            category=get_object_or_404(MenuCategory,pk=posted_id(request,'category_id')) if request.POST.get('category_id') else None
            category_form=CategoryForm(request.POST,instance=category)
            if category_form.is_valid():
                with transaction.atomic():
                    obj=category_form.save(commit=False)
                    if not obj.pk:obj.slug='category-'+uuid.uuid4().hex[:12]
                    obj.save();service.audit('category_updated' if category else 'category_created',request.user,after={'id':obj.pk,'name_ru':obj.name_ru,'name_kz':obj.name_kz,'sort_order':obj.sort_order})
                messages.success(request,'Категория сохранена / Санат сақталды');return redirect('/admin/menu/')
        elif action=='toggle':
            with transaction.atomic():
                obj=get_object_or_404(MenuItem.objects.select_for_update(),pk=posted_id(request,'item_id'))
                before=menu_snapshot(obj);obj.available=not obj.available;obj.save(update_fields=['available']);service.audit('menu_availability',request.user,before=before,after=menu_snapshot(obj))
            return redirect('/admin/menu/')
        elif action=='save':
            selected=get_object_or_404(MenuItem,pk=posted_id(request,'item_id')) if request.POST.get('item_id') else None
            before=menu_snapshot(selected) if selected else {};form=MenuForm(request.POST,request.FILES,instance=selected)
            if form.is_valid():
                image_path=None
                try:
                    with transaction.atomic():
                        obj=form.save(commit=False)
                        if not obj.pk:obj.slug='item-'+uuid.uuid4().hex[:12]
                        if form.cleaned_data.get('photo'):
                            from PIL import Image,ImageOps
                            folder=Path(getattr(settings,'MENU_UPLOAD_DIR',settings.BASE_DIR/'static'/'uploads'/'menu'));folder.mkdir(parents=True,exist_ok=True)
                            image_path=folder/(uuid.uuid4().hex+'.webp')
                            image=ImageOps.exif_transpose(Image.open(form.cleaned_data['photo']));image.thumbnail((1200,1200));image.save(image_path,'WEBP',quality=84)
                            obj.image='uploads/menu/'+image_path.name
                        obj.save();service.audit('menu_item_updated' if selected else 'menu_item_created',request.user,before=before,after=menu_snapshot(obj))
                    messages.success(request,'Позиция сохранена / Мәзір позициясы сақталды');return redirect('/admin/menu/')
                except (OSError,ValueError):
                    if image_path:image_path.unlink(missing_ok=True)
                    form.add_error('photo','Не удалось сохранить изображение / Фото сақталмады')
    query=MenuItem.objects.select_related('category').filter(is_test=False)
    menu_counts=query.aggregate(total=Count('pk'),active=Count('pk',filter=Q(available=True)),inactive=Count('pk',filter=Q(available=False)))
    term=request.GET.get('q','').strip()[:120]
    if term:query=query.filter(Q(name_ru__iregex=re.escape(term))|Q(name_kz__iregex=re.escape(term)))
    category=request.GET.get('category','');availability=request.GET.get('availability','available')
    if availability not in ('','available','stopped'):availability='available'
    if category.isdigit():query=query.filter(category_id=category)
    if availability in ['available','stopped']:query=query.filter(available=availability=='available')
    item_page=Paginator(query,20).get_page(request.GET.get('page'))
    for item in item_page:item.image_url=item.image if item.image.startswith('/') else '/static/'+item.image if item.image else ''
    return page(request,'menu','menu','Меню и стоп-лист','Мәзір және стоп-парақ',item_page=item_page,menu_counts=menu_counts,form=form,selected=selected,category_form=category_form,categories=MenuCategory.objects.all(),filters=dict(q=term,category=category,availability=availability))


class ReleaseForm(forms.Form):
    kitchen_release=forms.ChoiceField(choices=[('acceptance','После принятия / Қабылдағаннан кейін'),('payment','После оплаты / Төлемнен кейін')],widget=TranslatedSelect())


class PolicyForm(forms.Form):
    confirmed=forms.BooleanField(required=False,label='Программа включена / Бағдарлама қосулы')
    def __init__(self,*args,policy,**kwargs):
        super().__init__(*args,**kwargs)
        for index,tier in enumerate(policy.tiers,1):
            self.fields['threshold_'+str(index)]=forms.IntegerField(min_value=1,initial=tier['threshold'])
            self.fields['percent_'+str(index)]=forms.IntegerField(min_value=1,max_value=100,initial=tier['percent'])
    def clean(self):
        cleaned=super().clean();tiers=[]
        for index in range(1,(len(self.fields)-1)//2+1):
            threshold=cleaned.get('threshold_'+str(index));percent=cleaned.get('percent_'+str(index))
            if threshold is not None and percent is not None:tiers.append({'threshold':threshold,'percent':percent})
        if any(b['threshold']<=a['threshold'] or b['percent']<=a['percent'] for a,b in zip(tiers,tiers[1:])):raise forms.ValidationError('Пороги и проценты должны возрастать / Шектер мен пайыздар өсуі керек')
        cleaned['tiers']=tiers;return cleaned


@roles('owner')
def settings_page(request):
    current=AppSettings.get();policy=LoyaltyPolicy.get()
    release_form=ReleaseForm(initial={'kitchen_release':current.kitchen_release})
    policy_form=PolicyForm(policy=policy,initial={'confirmed':policy.confirmed})
    table_error=''
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='release':
            release_form=ReleaseForm(request.POST)
            if release_form.is_valid():
                before=current.kitchen_release;current.kitchen_release=release_form.cleaned_data['kitchen_release'];current.save(update_fields=['kitchen_release']);service.audit('settings_kitchen_release',request.user,before={'value':before},after={'value':current.kitchen_release});return redirect('/admin/settings/')
        elif action=='policy':
            policy_form=PolicyForm(request.POST,policy=policy)
            if policy_form.is_valid():
                before={'tiers':policy.tiers,'confirmed':policy.confirmed};policy.tiers=policy_form.cleaned_data['tiers'];policy.confirmed=policy_form.cleaned_data['confirmed'];policy.save(update_fields=['tiers','confirmed']);service.audit('loyalty_policy_updated',request.user,before=before,after={'tiers':policy.tiers,'confirmed':policy.confirmed});return redirect('/admin/settings/')
        elif action=='table':
            table=get_object_or_404(Table,pk=posted_id(request,'table_id'),is_test=False)
            name=request.POST.get('name','').strip()
            if not name or len(name)>80:table_error='Название столика: от 1 до 80 символов / Үстел атауы: 1–80 таңба'
            else:
                before={'name':table.name,'active':table.active};table.name=name;table.active=request.POST.get('active')=='on';table.save(update_fields=['name','active']);service.audit('table_updated',request.user,before=before,after={'id':table.pk,'name':table.name,'active':table.active});return redirect('/admin/settings/')
    tiers=[(policy_form['threshold_'+str(i)],policy_form['percent_'+str(i)]) for i in range(1,len(policy.tiers)+1)]
    return page(request,'settings','settings','Настройки','Баптаулар',release_form=release_form,policy_form=policy_form,tier_fields=tiers,tables=Table.objects.filter(is_test=False),table_error=table_error,policy=policy)
