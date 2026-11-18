from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User,Group
from django.core.exceptions import PermissionDenied,ValidationError
from .models import Order,OrderItem,MenuCategory,MenuItem,Customer,AppSettings
from . import services as s
from .preparation import drink_plan

class DrinkCoordinationTests(TestCase):
 def setUp(self):
  self.now=timezone.now();self.cashier=self.actor('cashier');self.cook=self.actor('kitchen')
  self.customer=Customer.objects.create(phone='+77000005501',name='Coordination fixture',consent_at=self.now,is_test=False)
  c=MenuCategory.objects.create(slug='coord',name_ru='QA',name_kz='QA')
  self.food=MenuItem.objects.create(category=c,slug='food',name_ru='Блюдо',name_kz='Тағам',kind='food',price=100,is_test=False)
  self.drink=MenuItem.objects.create(category=c,slug='drink',name_ru='Напиток',name_kz='Сусын',kind='drink',price=50,is_test=False)
  AppSettings.get()
 def actor(self,role):
  u=User.objects.create_user('coord-'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);return u
 def order(self,food=2,drinks=3,preference='with_food'):
  o=Order.objects.create(customer=self.customer,status='accepted',payment_method='cash',drink_preference=preference,drink_eta_minutes=6,is_test=False,idempotency_key=str(Order.objects.count()))
  for product,n in [(self.food,food),(self.drink,drinks)]:
   for _ in range(n):OrderItem.objects.create(order=o,menu_item=product,kind=product.kind,name_ru=product.name_ru,name_kz=product.name_kz,unit_price=product.price,quantity=1)
  return o
 def act(self,o,actor,action,**data):
  with patch('django.utils.timezone.now',return_value=self.now):s.act_on_order(o.public_id,actor,action,data)
  o.refresh_from_db()
 def plan(self,o,now=None):return drink_plan(o,list(o.items.all()),now or self.now)
 def assign(self,o,minutes):
  ids=list(o.items.filter(kind='food').values_list('pk',flat=True))
  self.act(o,self.cook,'food_eta',items=[{'item_id':i,'eta':m} for i,m in zip(ids,minutes)])
 def test_latest_food_and_whole_group_duration_without_auto_start(self):
  o=self.order();self.assign(o,[15,25]);p=self.plan(o)
  self.assertEqual(p['recommended_start_at'],(self.now+timedelta(minutes=19)).isoformat())
  self.assertEqual(p['duration_minutes'],6);self.assertEqual(p['code'],'scheduled')
  self.assertFalse(p['started']);self.assertTrue(all(i.status=='pending' for i in o.drink_items))
 def test_unknown_kitchen_never_blocks_manual_start(self):
  o=self.order();self.assertEqual(self.plan(o)['code'],'waiting_kitchen')
  self.act(o,self.cashier,'drinks_start');self.assertEqual(self.plan(o)['code'],'preparing')
  self.assertTrue(all(i.status=='pending' for i in o.food_items));self.assertEqual(o.drink_eta_at,self.now+timedelta(minutes=6))
 def test_partial_food_plan_does_not_guess_missing_time(self):
  o=self.order();self.assign(o,[20]);p=self.plan(o)
  self.assertEqual(p['code'],'waiting_kitchen');self.assertEqual(p['missing_food_eta'],1);self.assertIsNone(p['recommended_start_at'])
 def test_overdue_plan_is_now_not_a_past_future_recommendation(self):
  o=self.order();self.assign(o,[15,25]);p=self.plan(o,self.now+timedelta(minutes=22))
  self.assertEqual(p['code'],'start_now');self.assertIsNone(p['recommended_start_at']);self.assertEqual(p['overdue_minutes'],3)
  self.assertFalse(p['started']);self.assertTrue(all(i.status=='pending' for i in o.drink_items))
 def test_early_food_ready_recommends_now_without_changing_bar(self):
  o=self.order();self.assign(o,[15,25])
  for item in o.food_items:self.act(o,self.cook,'item_ready',item_id=item.pk)
  self.assertEqual(self.plan(o)['code'],'food_ready');self.assertIsNone(self.plan(o)['recommended_start_at'])
  self.assertTrue(all(i.status=='pending' for i in o.drink_items));self.assertNotEqual(o.status,'ready');self.assertIsNone(o.served_at)
 def test_eta_changes_before_and_after_manual_start(self):
  o=self.order();self.assign(o,[15,25]);self.assign(o,[10,30]);self.assertEqual(self.plan(o)['food_target_at'],(self.now+timedelta(minutes=30)).isoformat())
  self.act(o,self.cashier,'drinks_start');started=o.drink_started_at;deadline=o.drink_eta_at
  self.assign(o,[20,40]);p=self.plan(o);self.assertEqual(p['code'],'kitchen_changed')
  self.assertEqual(o.drink_started_at,started);self.assertEqual(o.drink_eta_at,deadline)
 def test_notice_seen_is_server_persistent_and_new_eta_creates_new_event(self):
  o=self.order();self.assign(o,[1,2]);p=self.plan(o)
  self.assertEqual(p['code'],'start_now');self.assertTrue(p['unseen'])
  self.act(o,self.cashier,'drink_notice_seen',event_token=p['event_token'])
  reloaded=Order.objects.get(pk=o.pk);self.assertFalse(self.plan(reloaded)['unseen'])
  self.assign(o,[2,3]);self.assertTrue(self.plan(o)['unseen'])
  with self.assertRaises(ValidationError):self.act(o,self.cashier,'drink_notice_seen',event_token=p['event_token'])
  with self.assertRaises(PermissionDenied):self.act(o,self.cook,'drink_notice_seen',event_token=self.plan(o)['event_token'])
 def test_duration_only_edit_never_starts_bar(self):
  o=self.order();self.act(o,self.cashier,'drink_eta',eta=7)
  self.assertIsNone(o.drink_started_at);self.assertIsNone(o.drink_eta_at);self.assertEqual(o.status,'accepted')
 def test_independent_and_single_station_orders(self):
  for foods,drinks,pref,code in [(0,2,'','independent'),(2,0,'','inactive'),(2,2,'immediately','independent')]:
   with self.subTest(code=code):self.assertEqual(self.plan(self.order(foods,drinks,pref))['code'],code)
 def test_per_item_plan_atomic_validation_and_permissions(self):
  o=self.order();f=o.food_items.first();d=o.drink_items.first()
  with self.assertRaises(ValidationError):self.act(o,self.cook,'food_eta',items=[{'item_id':f.pk,'eta':5},{'item_id':d.pk,'eta':20}])
  f.refresh_from_db();self.assertIsNone(f.eta_at)
  with self.assertRaises(PermissionDenied):self.act(o,self.cashier,'food_eta',items=[{'item_id':f.pk,'eta':5}])
 def test_repeated_start_does_not_reset_actual_clock(self):
  o=self.order();self.act(o,self.cashier,'drinks_start');deadline=o.drink_eta_at;self.now+=timedelta(minutes=2)
  self.act(o,self.cashier,'drinks_start');self.assertEqual(o.drink_eta_at,deadline)
 def test_read_only_api_refresh_does_not_start_or_acknowledge(self):
  o=self.order();self.assign(o,[1,2]);self.client.force_login(self.cashier);before=o.version
  for _ in range(2):
   result=self.client.get(f'/api/staff/orders/{o.public_id}/').json()['order']
   self.assertEqual(result['drink_plan']['code'],'start_now');self.assertTrue(result['drink_plan']['unseen'])
  o.refresh_from_db();self.assertEqual(o.version,before);self.assertIsNone(o.drink_started_at);self.assertEqual(o.drink_notice_seen_token,'')

 def test_invalid_drink_duration_does_not_fall_back_to_previous_estimate(self):
  for value in (0,False,'1.5',181):
   o=self.order()
   with self.subTest(value=value),self.assertRaises(ValidationError):self.act(o,self.cashier,'drinks_start',eta=value)
   o.refresh_from_db();self.assertIsNone(o.drink_started_at)
