"""Owner-photo transcription import, preservation and station routing."""
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from django.test import TestCase
from django.contrib.auth.models import Group,User
from django.utils import timezone
from .models import MenuItem,Customer,Table,Order,MenuCategory
from . import services
class DrinksImportTests(TestCase):
 def import_menu(self):call_command('import_drinks',stdout=StringIO())
 def test_each_volume_is_a_drink_sku_and_ambiguous_matcha_not_orderable(self):
  self.import_menu()
  drinks=MenuItem.objects.filter(kind='drink')
  self.assertEqual(drinks.count(),68);self.assertEqual(drinks.filter(available=True).count(),64)
  coffee=drinks.filter(category__slug='drinks-coffee');self.assertEqual(coffee.count(),11)
  espresso=drinks.get(slug='drink-espresso-02');self.assertEqual(espresso.price,890);self.assertIn('0.2 л',espresso.name_ru);self.assertTrue(espresso.uncertainties)
  self.assertEqual(drinks.filter(category__slug='drinks-matcha',available=False).count(),4)
  self.assertFalse(drinks.filter(slug__icontains='syrup').exists())
  self.assertEqual(drinks.filter(slug='drink-latte-03').get().price,1490)
  self.assertEqual(drinks.filter(slug='drink-latte-04').get().price,1590)
 def test_reimport_preserves_owner_edits_and_explicit_refresh_is_required(self):
  self.import_menu();item=MenuItem.objects.get(slug='drink-espresso-02');item.name_ru='Owner corrected name';item.price=999;item.available=False;item.save()
  self.import_menu();item.refresh_from_db();self.assertEqual(item.name_ru,'Owner corrected name');self.assertEqual(item.price,999);self.assertFalse(item.available)
  self.assertEqual(MenuItem.objects.count(),68)
  call_command('import_drinks',refresh=True,stdout=StringIO());item.refresh_from_db();self.assertEqual(item.price,890);self.assertTrue(item.available)
 def test_imported_drinks_are_never_sent_to_kitchen(self):
  self.import_menu();cashier=User.objects.create_user('cash');cashier.groups.add(Group.objects.create(name='cashier'))
  customer=Customer.objects.create(name='Synthetic test',phone='+70000000001',consent_at=timezone.now(),phone_verified_at=timezone.now(),is_test=True)
  table=Table.objects.create(name='Fixture',is_test=True)
  item=MenuItem.objects.get(slug='drink-latte-03')
  payload={'items':[{'id':item.pk,'quantity':1}],'table_token':table.token(),'payment_method':'cash','idempotency_key':'imported-drink-order'}
  order,_=services.create_order(customer,payload)
  services.act_on_order(order.public_id,cashier,'accept',{'eta':5})
  self.assertEqual(order.items.get().kind,'drink');self.assertFalse(services.kitchen_queue().filter(pk=order.pk).exists())
  food_category=MenuCategory.objects.create(slug='fixture-food',name_ru='Food',name_kz='Food')
  food=MenuItem.objects.create(slug='fixture-food',category=food_category,name_ru='Food',name_kz='Food',kind='food',price=100)
  payload.update(idempotency_key='mixed-imported-drinks',items=[{'id':item.pk,'quantity':1},{'id':food.pk,'quantity':1}],drink_preference='with_food')
  mixed,_=services.create_order(customer,payload);services.act_on_order(mixed.public_id,cashier,'accept',{'eta':5})
  self.assertTrue(services.kitchen_queue().filter(pk=mixed.pk).exists());self.assertEqual(mixed.food_items.count(),1);self.assertEqual(mixed.drink_items.count(),1)
