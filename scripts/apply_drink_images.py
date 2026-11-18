"""Link generated serving illustrations to matching drinks; preserve prices and availability."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from core.models import MenuItem
mapping={
'hot-coffee':['drink-espresso-02','drink-flat-white-02','drink-americano-03','drink-americano-04','drink-latte-03','drink-latte-04','drink-cappuccino-03','drink-cappuccino-04','drink-raf-03','drink-raf-04','drink-mochaccino-03','drink-tary-raf-04','drink-talqan-latte-04','drink-nut-mokko-04'],
'hot-chocolate':['drink-cocoa-03','drink-cocoa-04','drink-hot-chocolate-03','drink-hot-chocolate-04'],
'iced-latte':['drink-ice-latte-04','drink-ice-cappuccino-04'],
'iced-americano':['drink-ice-americano-04'],
'bumble-coffee':['drink-bumble-coffee-04'],
'author-tea':['tashkent-tea-03l','moroccan-tea-03l','ginger-tea-03l'],
'iced-matcha-green':['drink-ice-matcha-green'],
'berry-lemonade':['berry-lemonade-04l'],
}
report=[]
for asset,slugs in mapping.items():
 path=ROOT/'static/drinks-generated'/f'{asset}.webp'
 if not path.exists():raise RuntimeError(f'Missing image: {path}')
 for slug in slugs:
  row=MenuItem.objects.get(slug=slug,kind='drink',is_test=False)
  row.image=f'/static/drinks-generated/{asset}.webp';row.save(update_fields=['image'])
  report.append({'slug':slug,'image':row.image,'origin':'generated-from-user-cup-references'})
(ROOT/'docs/drink-image-links.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(f'Linked {len(report)} drink variants. All tables share the same menu.')
