import json
from django.test import TestCase,Client
from django.utils import timezone
from .models import Customer,Order

class GuestReceiptTests(TestCase):
 def setUp(self):
  self.customer=Customer.objects.create(name='Receipt QA',phone='+77000000031',consent_at=timezone.now(),is_test=False)
  self.order=Order.objects.create(customer=self.customer,idempotency_key='receipt-qa',payload_hash='qa',payment_method='cash',total=100,is_test=True)
  self.url=f'/orders/{self.order.public_id}/receipt/'
  session=self.client.session;session['claim_customer_id']=self.customer.pk;session['claim_order_ids']=[str(self.order.public_id)];session.save()
 def test_receipt_owned_and_private(self):
  response=self.client.get(self.url)
  self.assertEqual(response.status_code,200);self.assertContains(response,'Электронная квитанция');self.assertContains(response,'Сохранить в PDF');self.assertContains(response,'window.print()')
  self.assertNotContains(response,self.customer.phone);self.assertNotContains(response,'/admin/');self.assertEqual(response['Cache-Control'],'private, no-store')
 def test_same_phone_does_not_grant_receipt_access(self):
  other=Client();session=other.session;session['claim_customer_id']=self.customer.pk;session['claim_order_ids']=[];session.save()
  self.assertEqual(other.get(self.url).status_code,403);self.assertEqual(Client().get(self.url).status_code,403)
 def test_order_list_is_session_scoped(self):
  hidden=Order.objects.create(customer=self.customer,idempotency_key='hidden-qa',payload_hash='qa',payment_method='cash',total=200,is_test=True)
  response=self.client.get('/account/');self.assertEqual(response.status_code,200)
  self.assertEqual([o['public_id'] for o in response.context['orders']],[str(self.order.public_id)])
  self.assertNotIn(str(hidden.public_id),response.content.decode())
 def test_receipt_discounts_only_if_present(self):
  self.assertNotContains(self.client.get(self.url),'До скидки')
  self.order.discount_percent=5;self.order.discount_amount=5;self.order.subtotal=100;self.order.total=95;self.order.save()
  self.assertContains(self.client.get(self.url),'До скидки')
 def test_claim_sees_public_loyalty_not_personal_account(self):
  from .models import LoyaltyPolicy
  self.customer.phone_verified_at=timezone.now();self.customer.save()
  policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
  response=self.client.get('/account/')
  self.assertFalse(response.context['loyalty']['personal']['verified']);self.assertEqual(response.context['loyalty']['personal']['total'],0)
  self.assertContains(response,'Накопительная скидка');self.assertContains(response,'500000');self.assertNotContains(response,'Учтено в программе')
 def test_verified_loyalty_uses_ledger_and_configured_program(self):
  from django.contrib.auth.models import User
  from .models import LoyaltyPolicy,LoyaltyEntry,Payment
  self.customer.phone_verified_at=timezone.now();self.customer.save()
  policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
  cashier=User.objects.create_user('loyalty-ledger-qa')
  payment=Payment.objects.create(order=self.order,amount=75000,method='cash',confirmed_by=cashier,idempotency_key='ledger-qa')
  LoyaltyEntry.objects.create(customer=self.customer,order=self.order,payment=payment,amount=75000,kind='purchase')
  session=self.client.session;session.pop('claim_customer_id',None);session['customer_id']=self.customer.pk;session.save()
  result=self.client.get('/account/').context['loyalty']['personal']
  self.assertEqual(result['total'],75000);self.assertEqual(result['percent'],5);self.assertEqual(result['next_percent'],7);self.assertEqual(result['remaining'],25000);self.assertEqual(result['balance'],75000)
  self.assertEqual(self.client.get('/account/').context['loyalty']['orders_summary']['total'],100)
 def test_print_button_removed_from_guest_receipt(self):
  response=self.client.get(self.url)
  self.assertNotContains(response,'data-ru="Печать"');self.assertContains(response,'Сохранить в PDF')

 def test_browser_payments_are_separate_from_customer_progress(self):
  Order.objects.filter(pk=self.order.pk).update(payment_status='paid',actual_paid=12500,is_test=False)
  Order.objects.create(customer=self.customer,idempotency_key='private-paid',payload_hash='qa',payment_method='cash',payment_status='paid',actual_paid=90000,total=90000,is_test=False)
  result=self.client.get('/account/').context['loyalty']['personal']
  self.assertEqual(result['total'],12500);self.assertIsNone(result['remaining']);self.assertIsNone(result['next_percent']);self.assertIsNone(result['progress']);self.assertEqual(result['percent'],0)
  Order.objects.filter(pk=self.order.pk).update(payment_status='refunded',actual_paid=0)
  self.assertEqual(self.client.get('/account/').context['loyalty']['personal']['total'],0)

 def test_available_rate_does_not_use_browser_spend_for_next_level(self):
  from django.contrib.auth.models import User
  from .models import LoyaltyPolicy,LoyaltyEntry,Payment
  policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
  hidden=Order.objects.create(customer=self.customer,idempotency_key='ux01-private',payload_hash='qa',payment_method='cash',total=100000,payment_status='paid',actual_paid=100000,status='served',is_test=False)
  cashier=User.objects.create_user('ux01-cashier')
  payment=Payment.objects.create(order=hidden,amount=100000,method='cash',confirmed_by=cashier,idempotency_key='ux01-payment')
  LoyaltyEntry.objects.create(customer=self.customer,order=hidden,payment=payment,amount=100000,kind='purchase')
  Order.objects.filter(pk=self.order.pk).update(total=3350,is_test=False)
  response=self.client.get('/account/');loyalty=response.context['loyalty']
  self.assertEqual(loyalty['personal']['percent'],7)
  self.assertEqual(loyalty['personal']['next_percent'],10)
  self.assertIsNone(loyalty['personal']['balance'])
  self.assertIsNone(loyalty['personal']['remaining'])
  self.assertEqual(loyalty['orders_summary']['total'],3350)
  self.assertEqual(loyalty['orders_summary']['browser_paid'],0)
  Order.objects.filter(pk=self.order.pk).update(status='served',payment_status='paid',actual_paid=3350)
  updated=self.client.get('/account/').context['loyalty']
  self.assertEqual(updated['orders_summary']['count'],0)
  self.assertEqual(updated['orders_summary']['total'],0)
  self.assertEqual(updated['orders_summary']['browser_paid'],3350)
  self.assertEqual(updated['personal']['next_percent'],10)
  self.assertIsNone(updated['personal']['balance'])
  self.assertNotContains(response,'guest-loyalty-progress" max=')
  self.assertContains(response,'Сумма текущего заказа')
  self.assertNotIn(str(hidden.public_id),response.content.decode())
