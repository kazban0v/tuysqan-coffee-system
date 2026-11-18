import json
import uuid
from decimal import Decimal
from django.contrib.auth.models import User,Group
from django.test import TestCase,Client
from django.utils import timezone
from .models import Customer,Table,MenuCategory,MenuItem,Order,Payment
from . import services as s

class ReceiptsTests(TestCase):
 def setUp(self):
  self.cashier=User.objects.create_user('receipt-cashier')
  self.cashier.groups.add(Group.objects.create(name='cashier'))
  self.owner=User.objects.create_user('receipt-owner');self.owner.groups.add(Group.objects.create(name='owner'))
  self.kitchen=User.objects.create_user('receipt-kitchen');self.kitchen.groups.add(Group.objects.create(name='kitchen'))
  self.customer=Customer.objects.create(name='Guest',phone='+77770000888',consent_at=timezone.now(),phone_verified_at=timezone.now(),is_test=False)
  self.table=Table.objects.create(name='Стол 8',is_test=False)
  cat=MenuCategory.objects.create(slug='receipt-menu',name_ru='Меню',name_kz='Мәзір')
  self.item=MenuItem.objects.create(category=cat,slug='receipt-food',name_ru='Блюдо',name_kz='Тағам',price=1000,is_test=False)
  self.client.force_login(self.cashier)
 def make_order(self,method='cash'):
  order,_=s.create_order(self.customer,{'items':[{'id':self.item.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':method,'idempotency_key':str(uuid.uuid4())})
  return order
 def pay(self,order):
  s.act_on_order(order.public_id,self.cashier,'accept',{'eta':10})
  return s.act_on_order(order.public_id,self.cashier,'pay',{'amount':'1000','cash_received':'1500','idempotency_key':str(uuid.uuid4())})
 def test_roles_and_print_buttons(self):
  order=self.make_order()
  response=self.client.get('/admin/receipts/')
  self.assertEqual(response.status_code,200)
  self.assertContains(response,str(order.public_id))
  self.assertContains(response,f'/admin/orders/{order.public_id}/print/')
  anonymous=Client();self.assertEqual(anonymous.get('/admin/receipts/').status_code,302)
  kitchen=Client();kitchen.force_login(self.kitchen);self.assertEqual(kitchen.get('/admin/receipts/').status_code,403)
 def test_confirmed_total_excludes_tender_and_test_data(self):
  paid=self.pay(self.make_order());pending=self.make_order()
  test=self.make_order();test.is_test=True;test.save()
  response=self.client.get('/admin/receipts/')
  self.assertEqual(response.context['confirmed_total'],Decimal('1000'))
  self.assertEqual(response.context['counts']['all'],2)
  self.assertEqual(response.context['counts']['unpaid'],1)
  self.assertEqual(response.context['counts']['paid'],1)
  self.assertNotContains(response,str(test.public_id))
  only=self.client.get('/admin/receipts/',{'status':'paid'})
  self.assertEqual([row['order'].pk for row in only.context['rows']],[paid.pk])
 def test_filters_and_dates(self):
  order=self.make_order('kaspi');other=self.make_order()
  for query in [order.number,'Стол 8']:
   response=self.client.get('/admin/receipts/',{'q':query,'method':'kaspi','source':'web','period':'today'})
   self.assertEqual([r['order'].pk for r in response.context['rows']],[order.pk])
  self.assertEqual(self.client.get('/admin/receipts/',{'method':'unsupported'}).status_code,400)
  self.assertEqual(self.client.get('/admin/receipts/',{'start':'not-a-date'}).status_code,400)
  self.assertEqual(self.client.get('/admin/receipts/',{'start':'2026-12-01','end':'2026-01-01'}).status_code,400)
 def test_pagination_preserves_filters(self):
  for _ in range(23):self.make_order()
  response=self.client.get('/admin/receipts/',{'source':'web','method':'cash'})
  self.assertEqual(len(response.context['rows']),20)
  self.assertIn('source=web',response.context['next_url'])
  self.assertIn('method=cash',response.context['next_url'])
  self.assertIn('page=2',response.context['next_url'])
  second=self.client.get('/admin/receipts/',{'source':'web','method':'cash','page':2})
  self.assertEqual(len(second.context['rows']),3)
 def test_reversed_payment_history_is_printable_and_not_current_revenue(self):
  order=self.pay(self.make_order())
  s.reverse_payment(order,self.owner,'Ошибочная оплата')
  before=Payment.objects.count()
  response=self.client.get('/admin/receipts/',{'status':'refunded'})
  self.assertEqual(response.context['confirmed_total'],0)
  self.assertEqual(len(response.context['rows']),1)
  printout=self.client.get(f'/admin/orders/{order.public_id}/print/')
  self.assertContains(printout,'История оплат')
  self.assertContains(printout,'Ошибочная оплата')
  history=printout.context['order']['payment_history']
  self.assertEqual(history[0]['cash_received'],'1500.00')
  self.assertEqual(history[0]['change'],'500.00')
  self.assertEqual(Payment.objects.count(),before)
 def test_empty_and_escaped_search(self):
  response=self.client.get('/admin/receipts/',{'q':'<script>alert(1)</script>'})
  self.assertEqual(response.status_code,200)
  self.assertContains(response,'Продажи не найдены')
  self.assertNotContains(response,'<script>alert(1)</script>')

 def test_sale_detail_keeps_saved_discount_after_policy_changes(self):
  order=self.make_order()
  Order.objects.filter(pk=order.pk).update(subtotal=5080,discount_percent=5,discount_amount=254,total=4826)
  from .models import LoyaltyPolicy
  policy=LoyaltyPolicy.get();policy.confirmed=False;policy.save(update_fields=['confirmed'])
  response=self.client.get(f'/api/staff/orders/{order.public_id}/')
  self.assertEqual(response.status_code,200)
  detail=response.json()['order']
  self.assertEqual(detail['subtotal'],'5080.00')
  self.assertEqual(detail['discount_percent'],5)
  self.assertEqual(detail['discount_amount'],'254.00')
  self.assertEqual(detail['total'],'4826.00')
