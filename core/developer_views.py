import hmac
from datetime import timedelta
from django.contrib.auth import authenticate,login
from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.debug import sensitive_post_parameters
from .developer_access import developer_only,is_developer
from .monitoring import config,server_snapshot,watchdog_snapshot
from .models import Order,Payment


@sensitive_post_parameters('password')
def developer_login(request):
    if is_developer(request.user):return redirect('/developer/')
    error=''
    if request.method=='POST':
        user=authenticate(request,username=request.POST.get('username','').strip(),password=request.POST.get('password',''))
        if user and is_developer(user):login(request,user);return redirect('/developer/')
        error='Не удалось войти. Проверьте данные доступа.'
    response=render(request,'developer/login.html',{'error':error})
    response['Cache-Control']='private, no-store';response['X-Robots-Tag']='noindex, nofollow'
    return response


def business_snapshot():
    # Aggregate payment cash flow, not profit, with refunds on their actual date.
    identity=str(connection.settings_dict['NAME']);key='developer-business:'+identity
    cached=cache.get(key)
    if cached:return cached
    from .admin_portal import payment_stats
    today=timezone.localdate();result={}
    for label,start in [('today',today),('week',today-timedelta(days=6)),('month',today.replace(day=1))]:
        stats=payment_stats(start,today)
        result[label]={k:str(v) for k,v in stats.items()}
    orders=Order.objects.filter(is_test=False)
    result.update(active_orders=orders.filter(status__in=['new','accepted','preparing','ready']).count(),unpaid_orders=orders.filter(payment_status='unpaid').exclude(status__in=['cancelled','rejected']).count(),unpaid_total=str(orders.filter(payment_status='unpaid').exclude(status__in=['cancelled','rejected']).aggregate(amount=Sum('total'))['amount'] or 0))
    cache.set(key,result,15)
    return result


@developer_only
@require_GET
def developer_dashboard(request):
    return render(request,'developer/dashboard.html',{'monitor':snapshot()})


def snapshot():
    cfg=config()
    try:business=business_snapshot()
    except Exception:business={'available':False}
    return {'host':server_snapshot(),'business':business,'watchdog':watchdog_snapshot(),'telegram':{'configured':bool(cfg.get('bot_token') and cfg.get('chat_id')),'bot_username':cfg.get('bot_username','')},'local_only':getattr(__import__('django.conf',fromlist=['settings']).settings,'LOCAL_ONLY',True)}


@developer_only
@require_GET
def developer_snapshot(request):return JsonResponse(snapshot())


@require_GET
def internal_health(request):
    expected=config().get('health_token','');provided=request.headers.get('Authorization','')
    if not expected or not hmac.compare_digest(provided,'Bearer '+expected):return JsonResponse({'error':'Not found'},status=404)
    host=server_snapshot(fresh=True);response=JsonResponse({'ok':host['database']['ok'],'host':host},status=200 if host['database']['ok'] else 503)
    response['Cache-Control']='private, no-store'
    return response


@require_GET
def internal_bot_status(request):
    """Read-only aggregates for the local owner bot, with a separate credential."""
    expected=config().get('bot_api_token','')
    if not expected or not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+expected):
        return JsonResponse({'error':'Not found'},status=404)
    response=JsonResponse(snapshot())
    response['Cache-Control']='private, no-store'
    return response
