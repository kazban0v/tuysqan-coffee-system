"""Idempotent operational local setup. Preserves financial history and existing passwords."""
import json,secrets,os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User,Group
from core.models import MenuCategory,MenuItem,Table,AppSettings,LoyaltyPolicy
class Command(BaseCommand):
 help='Initialize local staff and tables without external services or fixture reseeding'
 def handle(self,*a,**kw):
  root=Path(__file__).resolve().parents[3]
  if not MenuItem.objects.exists():
   for sort,part in enumerate(sorted((root/'data/menu').glob('menu-part-*.json'))):
    for j,c in enumerate(json.loads(part.read_text())['categories']):
     category,_=MenuCategory.objects.get_or_create(slug=c['id'],defaults={'name_ru':c['name']['ru'],'name_kz':c['name']['kz'],'sort_order':sort*10+j})
     for item in c['items']:
      MenuItem.objects.get_or_create(slug=item['id'],defaults={'category':category,'name_ru':item['name']['ru'],'name_kz':item['name']['kz'],'description_ru':item['description']['ru'],'description_kz':item['description']['kz'],'kind':'food','price':item['price'] or 0,'available':item['price'] is not None,'is_test':False,'data_confirmed':False,'source':item['source'],'uncertainties':item['uncertainties'],'image':'/static/menu/'+item['id']+'.jpg' if (root/'static/menu'/f"{item['id']}.jpg").exists() else ''})
  credential_file=root/'.local-credentials.json'
  credentials=json.loads(credential_file.read_text()) if credential_file.exists() else {}
  for username,role in [('administrator','owner'),('cashier','cashier'),('kitchen','kitchen')]:
   group,_=Group.objects.get_or_create(name=role)
   user,created=User.objects.get_or_create(username=username,defaults={'is_staff':role=='owner','is_superuser':role=='owner','is_active':True})
   if created:
    password=secrets.token_urlsafe(20);user.set_password(password);user.save();credentials[username]=password
   user.groups.add(group)
  if credentials:
   credential_file.write_text(json.dumps(credentials,ensure_ascii=False,indent=2)+'\n');credential_file.chmod(0o600)
  User.objects.filter(username__startswith='demo_').update(is_active=False)
  MenuItem.objects.filter(is_test=True).update(available=False)
  Table.objects.filter(is_test=True).update(active=False)
  for n in range(1,9):Table.objects.get_or_create(name=f'Стол {n}',is_test=False,defaults={'active':True})
  AppSettings.get();LoyaltyPolicy.get()
  self.stdout.write('Local staff and tables initialized. Existing passwords and financial history preserved.')
