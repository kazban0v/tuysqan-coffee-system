import json
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.test import TestCase
from django.core.management import call_command
from io import StringIO
from .models import MenuCategory,MenuItem,Customer,Order,OrderItem
from django.utils import timezone

class PrintedMenuTests(TestCase):
 def test_retired_shakshuka_cannot_be_browsed_or_ordered(self):
  from importlib import import_module
  from django.apps import apps
  from django.db import connection
  from types import SimpleNamespace
  from django.core.exceptions import ValidationError
  from .services import menu_lines
  from .views import catalog
  cat=MenuCategory.objects.create(slug='breakfast',name_ru='Завтраки',name_kz='Таңғы ас')
  retired=MenuItem.objects.create(category=cat,slug='classic-shakshuka',name_ru='Классическая шакшука',price=3630,available=True)
  retained=MenuItem.objects.create(category=cat,slug='white-shakshuka',name_ru='Белая шакшука',price=2690,available=True)
  migration=import_module('core.migrations.0012_retire_classic_shakshuka')
  editor=SimpleNamespace(connection=connection)
  migration.retire_classic_shakshuka(apps,editor)
  migration.retire_classic_shakshuka(apps,editor)
  retired.refresh_from_db();retained.refresh_from_db()
  self.assertFalse(retired.available);self.assertTrue(retained.available)
  self.assertTrue(MenuItem.objects.filter(pk=retired.pk).exists())
  self.assertEqual([row['slug'] for row in catalog()],['white-shakshuka'])
  self.assertNotContains(self.client.get('/'),'Классическая шакшука')
  with self.assertRaises(ValidationError):menu_lines([{'id':retired.pk,'quantity':1}])
  for path in (settings.BASE_DIR/'data/menu').glob('menu-part-*.json'):
   source=json.loads(path.read_text())
   self.assertFalse(any(i['id']=='classic-shakshuka' for c in source['categories'] for i in c['items']))
  self.assertNotIn('Классическая шакшука',(settings.BASE_DIR/'static/landing/menu-data.js').read_text())

 def test_landing_and_qr_share_django_catalog_and_bootstrap_precedes_renderer(self):
  cat=MenuCategory.objects.create(slug='qa',name_ru='QA',name_kz='QA')
  p=MenuItem.objects.create(category=cat,slug='apple-oatmeal',name_ru='Овсянка',name_kz='Ботқа',price=1790,is_test=False)
  response=self.client.get('/');self.assertEqual(response.context['menu_presentation'][0]['price'],'1790.00')
  html=response.content.decode();self.assertLess(html.index('django-menu-source.js'),html.index('landing/app.js'))
  self.assertContains(response,'django-public-menu');self.assertNotIn('id',response.context['menu_presentation'][0])
 def test_transcription_known_prices_and_no_ambiguous_matcha(self):
  data=json.loads((settings.BASE_DIR/'data/menu/printed-2026-11-09.json').read_text())
  food={r['slug']:r for r in data['items']}
  self.assertEqual(len(food),66);self.assertEqual(len(data['drinks']),64)
  self.assertEqual(food['apple-oatmeal']['price'],1790);self.assertEqual(food['vegetable-frittata']['price'],2890)
  self.assertEqual([food[k]['price'] for k in ['caesar-chicken','caesar-salmon','caesar-shrimp']],[3190,3590,3290])
  self.assertEqual(food['chicken-burger']['status'],'conflict')
  self.assertFalse(any('matcha' in x['slug'] for x in data['drinks']))
