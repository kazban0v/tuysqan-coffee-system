from django.test import TestCase,Client
from django.contrib.auth.models import User,Group
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import *
from . import services as s
class FlowTests(TestCase):
 def setUp(self):
  self.c=Customer.objects.create(name='Test',phone='+70000000001',consent_at=timezone.now(),phone_verified_at=timezone.now())
  self.table=Table.objects.create(name='Test')
  cat=MenuCategory.objects.create(slug='x',name_ru='x',name_kz='x')
  self.food=MenuItem.objects.create(slug='food',category=cat,name_ru='Food',name_kz='Food',price=100,kind='food')
  self.drink=MenuItem.objects.create(slug='drink',category=cat,name_ru='Drink',name_kz='Drink',price=50,kind='drink')
  self.cash=User.objects.create_user('cash');self.cash.groups.add(Group.objects.create(name='cashier'))
  self.kitchen=User.objects.create_user('kitchen');self.kitchen.groups.add(Group.objects.create(name='kitchen'))
 def payload(self):return {'idempotency_key':'unique-key','items':[{'id':self.food.pk,'quantity':2},{'id':self.drink.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':'kaspi','drink_preference':'with_food'}
 def test_mixed_full_flow(self):
  o,created=s.create_order(self.c,self.payload());self.assertTrue(created);self.assertEqual(o.total,250);self.assertEqual(o.payment_status,'unpaid')
  again,created=s.create_order(self.c,self.payload());self.assertFalse(created);self.assertEqual(again.pk,o.pk);self.assertEqual(OutboxMessage.objects.count(),1)
  s.act_on_order(o.public_id,self.cash,'accept',{'eta':10});s.act_on_order(o.public_id,self.kitchen,'item_ready',{'item_id':o.food_items.get().pk});o.refresh_from_db();self.assertNotEqual(o.status,'ready')
  s.act_on_order(o.public_id,self.cash,'drinks_ready');o.refresh_from_db();self.assertEqual(o.status,'preparing');s.act_on_order(o.public_id,self.cash,'ready');o.refresh_from_db();self.assertEqual(o.status,'ready');self.assertEqual(o.payment_status,'unpaid')
  s.confirm_payment(o,self.cash,250);s.confirm_payment(o,self.cash,250);self.assertEqual(Payment.objects.count(),1);self.assertEqual(LoyaltyEntry.objects.count(),0)
  s.act_on_order(o.public_id,self.cash,'serve');o.refresh_from_db();self.assertEqual(o.status,'served')
 def test_mixed_preference_required(self):
  p=self.payload();p.pop('drink_preference')
  with self.assertRaises(ValidationError):s.create_order(self.c,p)
 def test_no_auto_ready_on_eta(self):
  o,_=s.create_order(self.c,self.payload());s.act_on_order(o.public_id,self.cash,'accept',{'eta':5});Order.objects.filter(pk=o.pk).update(drink_eta_at=timezone.now()-timezone.timedelta(minutes=1));s.mark_delays();o.refresh_from_db();self.assertEqual(o.status,'accepted');self.assertTrue(o.was_delayed)
 def test_payment_gate_food(self):
  setting=AppSettings.get();setting.kitchen_release='payment';setting.save();o,_=s.create_order(self.c,self.payload());s.act_on_order(o.public_id,self.cash,'accept',{'eta':5})
  with self.assertRaises(ValidationError):s.act_on_order(o.public_id,self.cash,'ready')
