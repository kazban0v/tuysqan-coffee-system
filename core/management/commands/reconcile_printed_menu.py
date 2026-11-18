"""Apply only reviewed printed-menu fields; never rewrite saved order lines."""
import json
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from core.models import MenuItem,MenuCategory

class Command(BaseCommand):
 help='Compare reviewed printed menu; use --apply to update catalog only.'
 def add_arguments(self,p):p.add_argument('--apply',action='store_true');p.add_argument('--report',default='artifacts/printed-menu-reconcile/comparison.json')
 def handle(self,*a,**options):
  source=json.loads((settings.BASE_DIR/'data/menu/printed-2026-11-09.json').read_text())
  aliases={'breakfast':'apple-oatmeal','sweet-breakfasts':'classic-syrniki','soups':'lentil-soup','salads':'caesar','pasta':'alfredo','hot':'beef-stroganoff','fastfood':'chicken-club','sides':'rice'}
  categories={k:MenuItem.objects.get(slug=v).category for k,v in aliases.items()}
  report=[]
  with transaction.atomic():
   for row in source['items']:
    item=MenuItem.objects.filter(slug=row['slug'],is_test=False).first()
    before={k:str(getattr(item,k)) for k in ('price','name_ru','name_kz','description_ru','description_kz')} if item else None
    fields={'price':Decimal(str(row['price'])).quantize(Decimal('0.01')),'description_ru':row.get('ru','') if row.get('status')!='conflict' else '', 'description_kz':row.get('kz','') if row.get('status')!='conflict' else ''}
    if row.get('name_ru'):fields['name_ru']=row['name_ru'];fields['name_kz']=row['name_kz']
    fields['source']=f"Печатное меню · фото {row['photo']} · предоставлено 2026-11-09"
    fields['data_confirmed']=row['status']!='conflict'
    fields['uncertainties']=[row['note_ru']] if row.get('status')=='conflict' else []
    changes={k:{'before':before.get(k) if before else None,'after':str(v)} for k,v in fields.items() if k in ('price','name_ru','name_kz','description_ru','description_kz') and (before is None or before.get(k)!=str(v))}
    report.append({'slug':row['slug'],'photo':row['photo'],'new':not bool(item),'changes':changes})
    if options['apply']:
     if item:
      for k,v in fields.items():setattr(item,k,v)
      item.save(update_fields=list(fields))
     else:
      cat=categories.get(row.get('category'))
      if not cat:
       names={'kids':('Детское меню','Балалар мәзірі'),'bread':('Хлеб','Нан')}
       if row.get('category') not in names:raise CommandError('Unknown category')
       ru,kz=names[row['category']];cat,_=MenuCategory.objects.get_or_create(slug=row['category'],defaults={'name_ru':ru,'name_kz':kz,'sort_order':8})
      MenuItem.objects.create(slug=row['slug'],category=cat,kind='food',available=True,is_test=False,**fields)
   # Grouped rows lack a single printed price: replaced by exact separately priced variants.
   if options['apply']:MenuItem.objects.filter(slug__in=['caesar','ramen','fries-wedges']).update(available=False)
   drink_report=[]
   for row in source['drinks']:
    item=MenuItem.objects.get(slug=row['slug'],is_test=False)
    drink_report.append({'slug':item.slug,'photo':row['photo'],'before':str(item.price),'printed':str(row['price']),'changed':item.price!=Decimal(str(row['price']))})
    if options['apply']:
     item.price=Decimal(str(row['price']));item.description_ru='';item.description_kz='';item.source=f"Печатное меню · фото {row['photo']} · 2026-11-09"
     item.save(update_fields=['price','description_ru','description_kz','source'])
   source_slugs={r['slug'] for r in source['items']}
   unconfirmed=list(MenuItem.objects.filter(kind='food',is_test=False).exclude(slug__in=source_slugs|{'caesar','ramen','fries-wedges'}).values('slug','name_ru','price','available'))
   result={'applied':options['apply'],'drinks':drink_report,'items':report,'unmatched_food_unchanged':unconfirmed,'unresolved':source['unresolved']}
   path=Path(options['report']);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
  self.stdout.write(f"Reviewed {len(report)} food variants; new {sum(r['new'] for r in report)}; price changes {sum('price' in r['changes'] and not r['new'] for r in report)}; apply={options['apply']}")
