"""Read-only preparation planning. No timer or GET changes operational statuses."""
import hashlib
import json
import math
from datetime import timedelta
from django.utils import timezone

def food_plan(order,items):
    food=[i for i in items if i.kind=='food'];unfinished=[i for i in food if i.status!='ready']
    known=[i.eta_at for i in unfinished if i.eta_at]
    # Orders created before per-item planning retain their explicit group ETA.
    legacy=bool(food and not any(i.eta_at for i in food) and order.food_eta_at)
    missing=0 if legacy else sum(not i.eta_at for i in unfinished)
    target=order.food_eta_at if legacy else max(known,default=None)
    return food,unfinished,target,missing

def drink_plan(order,items,now=None):
    now=now or timezone.now()
    food,unfinished,target,missing=food_plan(order,items)
    drinks=[i for i in items if i.kind=='drink']
    active=order.status in ('accepted','preparing','ready')
    started=bool(order.drink_started_at or any(i.status in ('preparing','ready') for i in drinks))
    together=bool(food and drinks and order.drink_preference=='with_food')
    code='inactive';recommended=None;late=0
    if active and drinks:
        if started:
            code='ready' if all(i.status=='ready' for i in drinks) else 'preparing'
            if together and unfinished and order.drink_started_at and target!=order.drink_food_eta_at_start:code='kitchen_changed'
        elif not together:code='independent'
        elif not unfinished:code='food_ready'
        elif missing or not target:code='waiting_kitchen'
        elif not order.drink_eta_minutes:code='waiting_duration'
        else:
            recommended=target-timedelta(minutes=order.drink_eta_minutes)
            code='scheduled' if recommended>now else 'start_now'
            late=max(0,math.floor((now-recommended).total_seconds()/60))
    attention=code in ('start_now','food_ready','kitchen_changed')
    token=hashlib.sha256(json.dumps([code,target.isoformat() if target else None,order.drink_eta_minutes,order.drink_started_at.isoformat() if order.drink_started_at else None],sort_keys=True).encode()).hexdigest() if attention else ''
    return {'code':code,'together':together,'started':started,'duration_minutes':order.drink_eta_minutes,'food_target_at':target.isoformat() if target and not missing else None,'missing_food_eta':missing,'recommended_start_at':recommended.isoformat() if code=='scheduled' else None,'overdue_minutes':late,'event_token':token,'unseen':bool(token and token!=order.drink_notice_seen_token)}
