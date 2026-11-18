"""Idempotently attach provided illustration URLs only; never change menu/prices/availability."""
import hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import transaction
from core.models import MenuItem
ASSETS=ROOT/'static/menu-upload-2026-11-06'
MAPPING={
'soups/lentil_cream_soup.webp':'lentil-soup','soups/pelmeni.webp':'pelmeni','soups/tom_yum_salmon_shrimp.webp':'tom-yum',
'pasta/tagliatelle_kazy_kurt.webp':'tagliatelle-kazy','pasta/shrimp_pasta.webp':'shrimp-pasta','pasta/alfredo.webp':'alfredo',
'kids_and_pizza/margherita_pizza.webp':'margherita','kids_and_pizza/kazy_pizza.webp':'kazy-pizza','kids_and_pizza/pepperoni_pizza.webp':'pepperoni','kids_and_pizza/chicken_mushroom_pizza.webp':'chicken-mushroom-pizza','kids_and_pizza/mexican_pizza.webp':'mexican-pizza',
'hot_dishes/chicken_mushroom_sauce.webp':'chicken-mushroom','hot_dishes/chicken_schnitzel.webp':'schnitzel','hot_dishes/beef_stroganoff.webp':'beef-stroganoff','hot_dishes/thai_style_beef.webp':'thai-beef','hot_dishes/yangnyeom_chicken.webp':'yangnyeom-chicken',
'sweet_breakfast/mini_baursaki_ice_cream.webp':'mini-baursaks','sweet_breakfast/syrniki_irimshik.webp':'irimshik-syrniki','sweet_breakfast/classic_syrniki.webp':'classic-syrniki','sweet_breakfast/mini_pancakes_ice_cream.webp':'mini-pancakes','sweet_breakfast/cottage_cheese_waffles.webp':'curd-waffles','sweet_breakfast/nutella_berry_pancakes.webp':'nutella-crepes',
'breakfast/oatmeal_apple_caramel.webp':'apple-oatmeal','breakfast/rice_porridge_apricot.webp':'apricot-rice','breakfast/fitness_breakfast.webp':'fitness-breakfast','breakfast/vegetable_frittata.webp':'vegetable-frittata','breakfast/english_breakfast.webp':'english-breakfast','breakfast/tuysqan_breakfast.webp':'tuysqan-breakfast','breakfast/american_breakfast.webp':'american-breakfast','breakfast/hashbrown_salmon.webp':'salmon-hashbrown','breakfast/shakshuka_stracciatella.webp':'stracciatella-shakshuka','breakfast/avocado_scramble.webp':'avocado-scramble',
'fastfood/chicken_club_sandwich.webp':'chicken-club','fastfood/beef_burger_fries.webp':'beef-burger','sides/chicken_nuggets.webp':'chicken-nuggets',
}
# Specific visual variants may be shown on the old public landing, but the grouped
# DB item must not silently inherit a chicken-only image for all variants.
PUBLIC_ONLY={'soups/chicken_ramen.webp':'Рамен с курицей','salads/caesar_chicken.webp':'Салат «Цезарь» с курицей'}
ALIASES={'irimshik-syrniki':'Сырники из иримшика','tuysqan-breakfast':'Завтрак Tuysqan','nutella-crepes':'Блины с нутеллой и ягодами','curd-waffles':'Вафли с творожным кремом','chicken-mushroom-pizza':'Пицца с курицей и грибами','mexican-pizza':'Мексиканская пицца','kazy-pizza':'Пицца с казы','yangnyeom-chicken':'Курица яннём','thai-beef':'Говядина по-тайски','tom-yum':'Том-ям с креветками и лососем','mini-pancakes':'Мини-панкейки с мороженым'}
def main():
 before={i.pk:(i.name_ru,i.name_kz,i.price,i.available,i.kind) for i in MenuItem.objects.all()};public={};manifest=[];updated=0
 with transaction.atomic():
  for file in sorted(ASSETS.rglob('*.webp')):
   rel=file.relative_to(ASSETS).as_posix();url='/static/menu-upload-2026-11-06/'+rel;slug=MAPPING.get(rel);item=MenuItem.objects.filter(slug=slug).first() if slug else None
   if slug and not item:raise RuntimeError('Missing existing dish: '+slug)
   if item:
    if item.image!=url:MenuItem.objects.filter(pk=item.pk).update(image=url);updated+=1
    public[item.name_ru]=url
    if slug in ALIASES:public[ALIASES[slug]]=url
    status='matched_existing_dish';reason='Reviewed exact dish association; image only.'
   elif rel in PUBLIC_ONLY:
    public[PUBLIC_ONLY[rel]]=url;status='public_specific_variant_only';reason='DB groups variants; not attached to grouped item and not made sellable.'
   else:
    status='unmatched_unpriced_drink' if rel.startswith('drinks/') else 'unmatched_requires_confirmation'
    reason='No confirmed existing dish/price match. Retained file only; no menu item created.'
   manifest.append({'file':rel,'url':url,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bytes':file.stat().st_size,'slug':slug,'status':status,'reason':reason,'origin':'provided_AI_processed_illustration'})
  assert before=={i.pk:(i.name_ru,i.name_kz,i.price,i.available,i.kind) for i in MenuItem.objects.all()}
 (ROOT/'docs/menu-upload-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 (ROOT/'static/landing/menu-upload-images.js').write_text('window.TUYSQAN_UPLOADED_IMAGES = '+json.dumps(public,ensure_ascii=False,indent=2)+';\n')
 print(json.dumps({'files':len(manifest),'db_matched':len(MAPPING),'public_only':len(PUBLIC_ONLY),'unmatched':len(manifest)-len(MAPPING)-len(PUBLIC_ONLY),'changed_image_fields':updated,'menu_names_prices_availability':'unchanged'},ensure_ascii=False))
if __name__=='__main__':main()
