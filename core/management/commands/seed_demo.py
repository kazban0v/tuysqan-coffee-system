import json
from pathlib import Path
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User,Group
from django.utils import timezone
from core.models import *
from core.services import create_order
class Command(BaseCommand):
 help='Create local synthetic accounts and import supplied menu; no network.'
 def handle(self,*a,**kw):
  root=Path(__file__).resolve().parents[3]
  source=root/'data/menu'
  for role in ['owner','manager','cashier','kitchen']:
   group,_=Group.objects.get_or_create(name=role);u,created=User.objects.get_or_create(username='demo_'+role,defaults={'is_staff':role=='owner','is_superuser':role=='owner'})
   if created:u.set_password('Tuysqan-local-2026!');u.save()
   u.groups.add(group)
  for n in range(1,4):Table.objects.get_or_create(name=f'Тестовый стол {n}')
  for sort,p in enumerate(sorted(source.glob('menu-part-*.json'))):
   for j,c in enumerate(json.loads(p.read_text())['categories']):
    cat,_=MenuCategory.objects.update_or_create(slug=c['id'],defaults={'name_ru':c['name']['ru'],'name_kz':c['name']['kz'],'sort_order':sort*10+j})
    for i in c['items']:
     MenuItem.objects.update_or_create(slug=i['id'],defaults={'category':cat,'name_ru':i['name']['ru'],'name_kz':i['name']['kz'],'description_ru':i['description']['ru'],'description_kz':i['description']['kz'],'price':i['price'] or 0,'available':i['price'] is not None,'kind':'food','source':i['source'],'uncertainties':i['uncertainties'],'image':'/static/menu/'+i['id']+'.jpg' if (root/'static/menu'/f"{i['id']}.jpg").exists() else ''})
  cat,_=MenuCategory.objects.get_or_create(slug='test-drinks',defaults={'name_ru':'Тестовые позиции — не меню кофейни','name_kz':'Сынақ позициялар — кофехана мәзірі емес','sort_order':100})
  MenuItem.objects.get_or_create(slug='test-drink',defaults={'category':cat,'name_ru':'ТЕСТОВЫЙ напиток — не меню Tuysqan','name_kz':'СЫНАҚ сусын — Tuysqan мәзірі емес','kind':'drink','price':100,'is_test':True})
  c,_=Customer.objects.get_or_create(phone='+70000000000',defaults={'name':'Синтетический гость кассы','phone_verified_at':timezone.now(),'consent_at':timezone.now()})
  AppSettings.get();LoyaltyPolicy.get()
  self.stdout.write('Demo seeded. Users demo_owner / demo_manager / demo_cashier / demo_kitchen; local password: Tuysqan-local-2026!')
