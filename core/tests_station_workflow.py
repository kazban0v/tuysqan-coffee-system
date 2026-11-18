import uuid
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from . import services as s
from .models import AppSettings, Customer, MenuCategory, MenuItem, Order, OutboxMessage, Table
from .views import kitchen_data


class StationWorkflowTests(TestCase):
    def setUp(self):
        self.cashier=self.user('cashier');self.kitchen=self.user('kitchen');self.manager=self.user('manager')
        self.customer=Customer.objects.create(name='QA',phone='+77000000177',consent_at=timezone.now(),is_test=False)
        self.table=Table.objects.create(name='QA',is_test=False)
        category=MenuCategory.objects.create(slug='stations',name_ru='QA',name_kz='QA')
        self.food=MenuItem.objects.create(category=category,slug='station-food',name_ru='Food',name_kz='Food',kind='food',price=100,is_test=False)
        self.drink=MenuItem.objects.create(category=category,slug='station-drink',name_ru='Drink',name_kz='Drink',kind='drink',price=50,is_test=False)

    def user(self,role):
        user=User.objects.create_user('station-'+role);user.groups.add(Group.objects.get_or_create(name=role)[0]);return user

    def order(self,kinds=('food','drink')):
        payload={'idempotency_key':str(uuid.uuid4()),'table_token':self.table.token(),'payment_method':'cash','drink_preference':'with_food','items':[{'id':getattr(self,kind).pk,'quantity':1} for kind in kinds]}
        return s.create_order(self.customer,payload,unverified_claim=True)[0]

    def act(self,o,actor,action,**data):
        result=s.act_on_order(o.public_id,actor,action,data);o.refresh_from_db();return result

    def test_accept_food_without_eta_does_not_assign_kitchen_time(self):
        o=self.order(('food',));self.act(o,self.cashier,'accept')
        self.assertEqual(o.status,'accepted');self.assertIsNone(o.eta_at);self.assertIsNone(o.food_eta_at)
        with self.assertRaises(PermissionDenied):self.act(o,self.cashier,'food_eta',eta=20)
        self.act(o,self.kitchen,'food_eta',eta=20)
        self.assertEqual(o.food_eta_minutes,20);self.assertIsNone(o.drink_eta_at);self.assertEqual(o.status,'preparing')
        self.assertEqual(o.food_items.get().status,'preparing')

    def test_two_independent_deadlines_and_station_permissions(self):
        o=self.order();self.act(o,self.cashier,'accept',drink_eta=5)
        self.assertEqual(o.drink_eta_minutes,5);self.assertIsNone(o.food_eta_at)
        self.act(o,self.kitchen,'food_eta',eta=20);food_deadline=o.food_eta_at
        self.act(o,self.cashier,'drink_eta',eta=10)
        self.assertEqual(o.food_eta_at,food_deadline);self.assertEqual(o.drink_eta_minutes,10)
        with self.assertRaises(PermissionDenied):self.act(o,self.kitchen,'drink_eta',eta=15)
        with self.assertRaises(PermissionDenied):self.act(o,self.cashier,'item_ready',item_id=o.food_items.get().pk)
        data=s.order_data(o);self.assertEqual(data['food_eta_minutes'],20);self.assertEqual(data['drink_eta_minutes'],10)
        self.assertEqual(kitchen_data(o)['eta_at'],food_deadline.isoformat())

    def test_station_readiness_never_auto_marks_whole_order_ready(self):
        o=self.order();self.act(o,self.cashier,'accept')
        with self.assertRaises(ValidationError):self.act(o,self.cashier,'ready')
        self.act(o,self.kitchen,'item_ready',item_id=o.food_items.get().pk)
        self.assertEqual(o.status,'preparing');self.assertIsNone(o.ready_at)
        with self.assertRaises(ValidationError):self.act(o,self.cashier,'ready')
        self.act(o,self.cashier,'drinks_ready');self.assertEqual(o.status,'preparing');self.assertIsNone(o.ready_at)
        with self.assertRaises(PermissionDenied):self.act(o,self.kitchen,'ready')
        self.act(o,self.cashier,'ready');self.assertEqual(o.status,'ready');self.assertIsNotNone(o.ready_at)
        self.assertIsNone(o.served_at);self.act(o,self.cashier,'serve');self.assertEqual(o.status,'served')

    def test_drink_only_has_bar_time_and_explicit_ready(self):
        o=self.order(('drink',));self.act(o,self.cashier,'accept');self.act(o,self.cashier,'drink_eta',eta=5)
        self.assertIsNone(o.food_eta_at);self.assertEqual(o.drink_items.get().status,'pending')
        self.act(o,self.cashier,'drinks_start');self.assertEqual(o.drink_items.get().status,'preparing')
        self.act(o,self.cashier,'drinks_ready');self.assertEqual(o.status,'preparing')
        self.act(o,self.cashier,'ready');self.assertEqual(o.status,'ready')

    def test_eta_validation_and_finished_station_are_guarded(self):
        o=self.order();self.act(o,self.cashier,'accept')
        for value in [True,7,'20.0',None]:
            with self.subTest(value=value),self.assertRaises(ValidationError):self.act(o,self.kitchen,'food_eta',eta=value)
        self.act(o,self.kitchen,'item_ready',item_id=o.food_items.get().pk)
        with self.assertRaises(ValidationError):self.act(o,self.kitchen,'food_eta',eta=20)

    def test_delay_tracks_unfinished_stations_not_completed_food(self):
        o=self.order();self.act(o,self.cashier,'accept');self.act(o,self.kitchen,'food_eta',eta=5);self.act(o,self.cashier,'drink_eta',eta=20)
        Order.objects.filter(pk=o.pk).update(food_eta_at=timezone.now()-timedelta(minutes=1))
        o.refresh_from_db();self.assertTrue(o.is_delayed)
        s.mark_delays();o.refresh_from_db();self.assertTrue(o.was_delayed)
        self.act(o,self.kitchen,'item_ready',item_id=o.food_items.get().pk);self.assertFalse(o.is_delayed)

    def test_payment_release_still_blocks_kitchen_time(self):
        setting=AppSettings.get();setting.kitchen_release='payment';setting.save()
        o=self.order();self.act(o,self.cashier,'accept')
        with self.assertRaises(PermissionDenied):self.act(o,self.kitchen,'food_eta',eta=10)
        self.act(o,self.cashier,'drink_eta',eta=5)
        self.assertIsNone(o.food_eta_at)

    def test_pos_food_acceptance_requires_no_eta_and_retries(self):
        payload={'idempotency_key':'station-pos-'+str(uuid.uuid4()),'table_token':self.table.token(),'payment_method':'cash','items':[{'id':self.food.pk,'quantity':1}],'accept_order':True}
        o,created=s.create_pos_order(self.cashier,payload)
        self.assertTrue(created);self.assertEqual(o.status,'accepted');self.assertIsNone(o.food_eta_at)
        again,created=s.create_pos_order(self.cashier,payload);self.assertFalse(created);self.assertEqual(again.pk,o.pk)
