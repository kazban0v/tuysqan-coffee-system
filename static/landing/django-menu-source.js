/* Django is authoritative for prices, descriptions, variants and availability on both public surfaces. */
(()=>{
 const node=document.getElementById('django-order-catalog')||document.getElementById('django-public-menu');if(!node)return;
 const db=JSON.parse(node.textContent||'[]'),old=window.TUYSQAN_MENU?.items||[],cats=new Map();
 const norm=s=>String(s||'').normalize('NFKC').toLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]/gu,'');
 const aliases={'tuysqan-breakfast':'Завтрак Tuysqan','nutella-crepes':'Блины с нутеллой и ягодами','curd-waffles':'Вафли с творожным кремом','zucchini-soup':'Крем-суп из цукини','crispy-aubergine':'Хрустящие баклажаны','greek-salad':'Греческий салат','popcorn-shrimp':'Креветки «Динамит»','pesto-pasta':'Паста с соусом песто','chicken-mushroom-pizza':'Пицца с курицей и грибами','mexican-pizza':'Мексиканская пицца','kazy-pizza':'Пицца с казы','mexican-tortilla':'Мексиканская тортилья','yangnyeom-chicken':'Курица яннём','thai-beef':'Говядина по-тайски','chicken-souvlaki':'Куриный сувлаки'};
 const previous=d=>old.find(i=>i.slug===d.slug)||old.find(i=>norm(i.name.ru)===norm(aliases[d.slug]||d.name_ru));
 const categoryKeys=new Map();for(const d of db){const prior=previous(d);if(prior)categoryKeys.set(d.category_id,prior.category)}
 const items=db.map(d=>{
  const prior=previous(d);
  const category=categoryKeys.get(d.category_id)||d.category_slug;
  if(!cats.has(category))cats.set(category,{id:category,ru:d.category_ru,kk:d.category_kz});
  return {...(prior||{}),slug:d.slug,category,name:{ru:d.name_ru,kk:d.name_kz},description:{ru:d.description_ru,kk:d.description_kz},price:Number(d.price),djangoId:d.id??d.photo_id,...(d.photo_authoritative?{image:d.image?(d.image.startsWith('/')?d.image:'/static/'+d.image):'',catalogImageOnly:true}:!prior?{image:d.image||'',catalogImageOnly:true}:{})};
 });
 window.TUYSQAN_MENU={categories:[...cats.values()],items};
})();
