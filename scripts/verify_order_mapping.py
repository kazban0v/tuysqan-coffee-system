"""Check every original landing entry maps to the reviewed Django dish, not by price."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from core.views import catalog
expected='apple-oatmeal apricot-rice talqan-berries vegetable-frittata tuysqan-breakfast stracciatella-shakshuka classic-shakshuka american-breakfast english-breakfast salmon-hashbrown avocado-scramble fitness-breakfast spinach-waffles irimshik-syrniki nutella-crepes classic-syrniki mini-pancakes curd-waffles mini-baursaks gazpacho lentil-soup zucchini-soup - - naryn pelmeni tom-yum - - - crispy-aubergine greek-salad green-salad burrata popcorn-shrimp warm-beef-salad tagliatelle-kazy alfredo pesto-pasta shrimp-pasta chicken-mushroom-pizza margherita mexican-pizza pepperoni kazy-pizza mexican-tortilla beef-burger chicken-burger chicken-club schnitzel beefsteak beef-stroganoff yangnyeom-chicken kung-pao beshbarmak thai-beef chicken-mushroom chicken-souvlaki'.split()
script="""
const fs=require('fs');const db=JSON.parse(fs.readFileSync(0,'utf8'));
global.window={};global.document={getElementById:()=>({textContent:JSON.stringify(db)}),addEventListener:()=>{}};global.localStorage={getItem:()=>null};
eval(fs.readFileSync('static/landing/menu-data.js','utf8'));eval(fs.readFileSync('static/landing/order-bridge.js','utf8'));
console.log(JSON.stringify({mapping:window.TUYSQAN_ORDER_MAPPING,prices:window.TUYSQAN_MENU.items.map(i=>i.price)}));
"""
data=json.loads(subprocess.run(['node','-e',script],input=json.dumps(catalog()),text=True,capture_output=True,check=True,cwd=ROOT).stdout)
assert len(data['mapping'])==len(expected)==58
by_id={i['id']:i for i in catalog()}
for index,(entry,slug) in enumerate(zip(data['mapping'],expected)):
 assert entry['slug']==(None if slug=='-' else slug),(index,entry,slug)
 if entry['id']:
  db=by_id[entry['id']];assert db['available'];assert float(db['price'])==data['prices'][index],entry
print(json.dumps({'landing_entries':58,'reviewed_mapped':53,'honestly_unavailable_grouped_variants':5,'all_mapped_prices':'Django authoritative'},ensure_ascii=False))
