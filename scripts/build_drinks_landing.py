#!/usr/bin/env python3
"""Export drink SKUs from the owning Django DB to the public landing catalog.
Run from project root: .venv/bin/python scripts/build_drinks_landing.py
Prices, volumes and translations are imported from supplied source transcriptions.
Ambiguous prices are shown as pending; synthetic rows are excluded.
"""
import os
import sys
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from core.models import MenuItem
rows=MenuItem.objects.select_related('category').filter(kind='drink',is_test=False).order_by('category__sort_order','id')
categories={}
items=[]
for row in rows:
    c=row.category
    categories[c.slug]={'id':c.slug,'ru':c.name_ru,'kk':c.name_kz}
    items.append({'slug':row.slug,'category':c.slug,'kind':'drink','image':row.image,'name':{'ru':row.name_ru,'kk':row.name_kz},'description':{'ru':row.description_ru,'kk':row.description_kz},'price':float(row.price) if row.price>0 else None,'available':row.available and row.price>0})
payload=json.dumps({'categories':list(categories.values()),'items':items},ensure_ascii=False,separators=(',',':'))
output=ROOT/'static/landing/drinks-data.js'
output.write_text('/* Generated from supplied drink menu imported into Django. Regenerate with scripts/build_drinks_landing.py. */\n(()=>{const drinks='+payload+'; const menu=window.TUYSQAN_MENU;if(!menu)return;const knownCategories=new Set(menu.categories.map(c=>c.id));for(const c of drinks.categories)if(!knownCategories.has(c.id))menu.categories.push(c);const knownSlugs=new Set(menu.items.map(i=>i.slug).filter(Boolean));for(const item of drinks.items)if(!knownSlugs.has(item.slug))menu.items.push(item);})();\n')
print(f'Exported {len(items)} drink SKUs, {len(categories)} categories to {output}')
