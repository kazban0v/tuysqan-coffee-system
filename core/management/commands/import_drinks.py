"""Import owner-supplied photographed drinks. Existing edits preserved by default."""
import json
from decimal import Decimal,InvalidOperation
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from core.models import MenuCategory,MenuItem
class Command(BaseCommand):
 help='Import data/drinks-page-*.json; existing rows unchanged unless --refresh supplied'
 def add_arguments(self,parser):
  parser.add_argument('--refresh',action='store_true',help='Explicitly replace matching drink source rows from transcription')
  parser.add_argument('--source',action='append',help='JSON source path; defaults to both provided pages')
 @transaction.atomic
 def handle(self,*args,**options):
  root=Path(__file__).resolve().parents[3]
  paths=[Path(p) for p in options['source']] if options['source'] else sorted((root/'data').glob('drinks-page-*.json'))
  if not paths:raise CommandError('No drinks source JSON found')
  created=updated=skipped=unavailable=0;seen=set()
  for page_index,path in enumerate(paths):
   data=json.loads(path.read_text())
   for category_index,category in enumerate(data['categories']):
    slug=category.get('slug') or category['id']
    cat,_=MenuCategory.objects.get_or_create(slug=slug,defaults={'name_ru':category['name_ru'],'name_kz':category['name_kz'],'sort_order':200+page_index*10+category_index})
    for item in category['items']:
     ident=item['slug']
     if ident in seen:raise CommandError('Duplicate drink slug: '+ident)
     seen.add(ident)
     if item.get('kind','drink')!='drink':raise CommandError('Wrong station type: '+ident)
     price=item.get('price');available=price is not None and item.get('available',True)
     try:
      amount=Decimal(str(price)) if price is not None else Decimal('0')
      if not amount.is_finite() or amount<0 or amount!=amount.quantize(Decimal('.01')):raise ValueError()
     except (ValueError,InvalidOperation):raise CommandError('Invalid price: '+ident)
     volume=item.get('volume','')
     def title(key):
      name=item[key]
      return name if not volume or volume in name else name+' · '+volume
     source=item.get('source') or data.get('source') or path.name
     values={'category':cat,'name_ru':title('name_ru'),'name_kz':title('name_kz'),'description_ru':item.get('description_ru',''),'description_kz':item.get('description_kz',''),'kind':'drink','price':amount,'available':available,'source':source,'uncertainties':item.get('uncertainties',[]),'is_test':False,'data_confirmed':False,'image':''}
     existing=MenuItem.objects.filter(slug=ident).first()
     if existing:
      if existing.kind!='drink':raise CommandError('Slug conflicts with food item: '+ident)
      if options['refresh']:
       if existing.source!=source:raise CommandError('Existing item source differs: '+ident)
       for key,value in values.items():setattr(existing,key,value)
       existing.save();updated+=1
      else:skipped+=1
     else:MenuItem.objects.create(slug=ident,**values);created+=1
     unavailable+=not available
  self.stdout.write(f'Drinks: created={created}, updated={updated}, preserved={skipped}, source variants={len(seen)}, unavailable={unavailable}. Supplements remain data-only.')
