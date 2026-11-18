"""Guest landing -> checkout -> cashier -> kitchen workflow with verified phone authentication."""
import json
from urllib.parse import urlencode
from .test_helpers import authenticate_phone
from django.test import TestCase,Client
from django.contrib.auth.models import User,Group
from .models import MenuCategory,MenuItem,Table,Order,Payment,LoyaltyEntry
class GuestOrderingTests(TestCase):
 def setUp(self):
  category=MenuCategory.objects.create(slug='breakfast',name_ru='Завтраки',name_kz='Таңғы ас')
  self.food=MenuItem.objects.create(slug='test-food',category=category,name_ru='Блюдо из меню',name_kz='Мәзір тағамы',kind='food',price=1250)
  self.table=Table.objects.create(name='Стол 1',is_test=False)
  self.cashier=User.objects.create_user('test_cashier');self.cashier.groups.add(Group.objects.create(name='cashier'))
  self.kitchen=User.objects.create_user('test_kitchen');self.kitchen.groups.add(Group.objects.create(name='kitchen'))
 def post(self,client,url,payload):return client.post(url,json.dumps(payload),content_type='application/json')
 def test_public_landing_never_exposes_order_catalog_even_after_qr(self):
  self.client.get('/table/'+self.table.token()+'/')
  response=self.client.get('/')
  self.assertEqual(response.status_code,200)
  self.assertFalse(response.context['ordering_enabled'])
  self.assertNotIn('menu_data',response.context)
  self.assertNotContains(response,'order-bridge.js')
 def test_signed_table_opens_separate_order_menu(self):
  response=self.client.get('/table/'+self.table.token()+'/')
  self.assertEqual(response.status_code,200)
  self.assertTrue(response.context['ordering_enabled'])
  self.assertTemplateUsed(response,'landing.html')
  self.assertContains(response,'data-table-menu="true"')
  self.assertContains(response,'order-bridge.js')
  self.assertEqual(response.context['menu_data'][0]['id'],self.food.pk)
 def test_guest_checkout_to_cashier_kitchen_and_payment(self):
  self.assertEqual(self.client.get('/checkout/').status_code,403)
  self.assertEqual(self.client.get('/table/'+self.table.token()+'/').status_code,200)
  self.assertEqual(self.client.get('/checkout/').status_code,302)
  authenticate_phone(self.client)
  self.assertEqual(self.client.get('/checkout/').status_code,200)
  payload={'items':[{'id':self.food.pk,'quantity':2,'comment':'Без специй'}],'table_token':self.table.token(),'payment_method':'kaspi','idempotency_key':'guest-full-workflow-key'}
  first=self.post(self.client,'/api/orders/',payload);self.assertEqual(first.status_code,201,first.content)
  public_id=first.json()['order']['public_id']
  self.assertEqual(self.post(self.client,'/api/orders/',payload).status_code,200)
  self.assertEqual(Order.objects.count(),1)
  order=Order.objects.get();self.assertIsNotNone(order.customer.phone_verified_at);self.assertEqual(order.payment_status,'unpaid')
  self.assertEqual(Client().get(f'/api/orders/{public_id}/').status_code,403)
  cashier=Client();cashier.force_login(self.cashier)
  queue=cashier.get('/api/staff/orders/').json()['orders'];self.assertEqual(queue[0]['public_id'],public_id)
  action=f'/api/staff/orders/{public_id}/action/'
  self.assertEqual(self.post(cashier,action,{'action':'accept','eta':15}).status_code,200)
  kitchen=Client();kitchen.force_login(self.kitchen)
  kitchen_order=kitchen.get('/api/kitchen/').json()['orders'][0]
  self.assertEqual(kitchen_order['items'][0]['comment'],'Без специй');self.assertNotIn('customer',kitchen_order)
  self.assertEqual(self.post(kitchen,action,{'action':'item_ready','item_id':kitchen_order['items'][0]['id']}).status_code,200)
  self.assertEqual(self.post(cashier,action,{'action':'ready'}).status_code,200)
  self.assertEqual(self.post(cashier,action,{'action':'pay','amount':'2500','idempotency_key':'guest-payment-key'}).status_code,200)
  self.assertEqual(self.post(cashier,action,{'action':'serve'}).status_code,200)
  final=self.client.get(f'/api/orders/{public_id}/').json()['order'];self.assertEqual(final['status'],'served');self.assertEqual(final['payment_status'],'paid');self.assertEqual(Payment.objects.count(),1);self.assertEqual(LoyaltyEntry.objects.count(),0)
 def test_signed_gate_rejects_missing_invalid_inactive_and_test_tables(self):
  payload={'items':[{'id':self.food.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':'cash','idempotency_key':'no-context-order'}
  self.assertEqual(self.post(self.client,'/api/orders/',payload).status_code,403)
  self.assertEqual(Order.objects.count(),0)
  for token in [str(self.table.pk),self.table.token()+'bad']:
   self.assertEqual(self.client.get('/table/'+token+'/').status_code,400)
  test=Table.objects.create(name='Synthetic',is_test=True)
  self.assertEqual(self.client.get('/table/'+test.token()+'/').status_code,404)
  self.assertEqual(self.client.get('/checkout/table/?'+urlencode({'token':self.table.token()})).status_code,404)
  self.table.active=False;self.table.save()
  self.assertEqual(self.client.get('/table/'+self.table.token()+'/').status_code,400)
 def test_operational_order_is_not_test_and_client_cannot_spoof_flag(self):
  self.client.get('/table/'+self.table.token()+'/')
  authenticate_phone(self.client)
  payload={'items':[{'id':self.food.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':'cash','idempotency_key':'operational-order','is_test':True}
  response=self.post(self.client,'/api/orders/',payload)
  self.assertEqual(response.status_code,201,response.content)
  order=Order.objects.get();self.assertFalse(order.is_test);self.assertFalse(order.customer.is_test)
  self.assertEqual(order.payment_status,'unpaid')

class CheckoutDiscountTests(TestCase):
 setUp=GuestOrderingTests.setUp
 def test_discount_preview_matches_saved_order_and_guest_has_none(self):
  from unittest.mock import patch,PropertyMock
  from django.utils import timezone
  from .models import Customer
  from .services import create_order,applicable_discount_percent
  guest=Customer.objects.create(name='Guest',phone='guest-discount-check',consent_at=timezone.now(),is_test=False)
  self.assertEqual(applicable_discount_percent(guest),0)
  identified=Customer.objects.create(name='Customer',phone='+70000000099',consent_at=timezone.now(),phone_verified_at=timezone.now(),is_test=False)
  with patch.object(Customer,'discount_percent',new_callable=PropertyMock,return_value=5):
   session=self.client.session;session['customer_id']=identified.pk;session['table_token']=self.table.token();session.save()
   response=self.client.get('/checkout/')
   self.assertEqual(response.context['checkout_discount_percent'],0)
   self.assertNotContains(response,'Скидку и итог рассчитает сервер')
   self.assertNotContains(response,'без регистрации')
   order,_=create_order(identified,{'items':[{'id':self.food.pk,'quantity':2}],'table_token':self.table.token(),'payment_method':'cash','idempotency_key':'discount-checkout-order'})
   self.assertEqual(order.discount_percent,0)
   self.assertEqual(order.subtotal,2500)
   self.assertEqual(order.discount_amount,0)
   self.assertEqual(order.total,2500)
