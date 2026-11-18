from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Customer, Table, MenuCategory, MenuItem, Order, OrderItem, Payment, AuditEvent, LoyaltyEntry, LoyaltyPolicy
from .order_presentation import prepare_order_list
from .services import order_data


class OrderPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer=Customer.objects.create(name='Тест',phone='+77001000001',phone_verified_at=timezone.now(),consent_at=timezone.now(),is_test=False)
        cls.table=Table.objects.create(name='Стол 1',is_test=False)
        category=MenuCategory.objects.create(slug='batch',name_ru='Тест',name_kz='Тест')
        cls.item=MenuItem.objects.create(slug='batch',category=category,name_ru='Тест',name_kz='Тест',price=1000,kind='food',is_test=False)
        cls.user=User.objects.create(username='batch')
        cls.orders=[]
        policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
        for i in range(8):
            order=Order.objects.create(customer=cls.customer,table=cls.table,status='preparing',payment_status='paid',payment_method='cash',total=1000,subtotal=1000,actual_paid=1000,is_test=False,idempotency_key=str(uuid4()),payload_hash='test',food_eta_at=timezone.now()-timedelta(minutes=1))
            OrderItem.objects.create(order=order,menu_item=cls.item,name_ru='Тест',name_kz='Тест',kind='food',quantity=1,unit_price=1000,status='pending')
            payment=Payment.objects.create(order=order,amount=1000,method='cash',confirmed_by=cls.user,idempotency_key=str(uuid4()))
            AuditEvent.objects.create(order=order,action='payment_confirmed',after={'payment_id':payment.pk,'cash_received':'1500.00','change':'500.00'})
            LoyaltyEntry.objects.create(order=order,customer=cls.customer,payment=payment,amount=1000,kind='purchase')
            cls.orders.append(order)

    def query(self):
        return Order.objects.select_related('customer','table')

    def test_batch_preserves_financial_facts_and_late_status(self):
        now=timezone.now()
        with patch('core.services.timezone.now',return_value=now):
            original=[order_data(order,True) for order in self.query()]
            prepared=prepare_order_list(self.query(),True)
            with self.assertNumQueries(0):
                result=[order_data(order,True) for order in prepared]
        self.assertEqual(original,result)
        self.assertTrue(result[0]['is_delayed'])
        self.assertEqual(result[0]['payment_history'][0]['cash_received'],'1500.00')
        self.assertEqual(Decimal(result[0]['discount_review']['accumulated']),Decimal('8000'))

    def test_new_request_sees_payment_reversal_and_new_item_readiness(self):
        prepare_order_list(self.query(),True)
        OrderItem.objects.all().update(status='ready')
        LoyaltyEntry.objects.create(customer=self.customer,order=self.orders[0],payment=self.orders[0].payments.first(),amount=-1000,kind='reversal')
        order=prepare_order_list(self.query().filter(pk=self.orders[0].pk),True)[0]
        result=order_data(order,True)
        self.assertFalse(result['is_delayed'])
        self.assertTrue(result['food_ready'])
        self.assertEqual(Decimal(result['discount_review']['accumulated']),Decimal('7000'))

    def test_query_count_does_not_grow_with_order_count(self):
        with self.assertNumQueries(9):
            one=prepare_order_list(self.query()[:1],True)
            [order_data(order,True) for order in one]
        with self.assertNumQueries(9):
            many=prepare_order_list(self.query(),True)
            [order_data(order,True) for order in many]
