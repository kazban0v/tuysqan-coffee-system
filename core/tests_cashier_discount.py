from decimal import Decimal
from django.test import TestCase,Client
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.utils import timezone
from .models import Customer,Order,Payment,AuditEvent
from . import services as s

class CashierDiscountTests(TestCase):
 def setUp(self):
  self.guest=Customer.objects.create(name='QA discount',phone='+77000000041',consent_at=timezone.now(),is_test=False)
  self.order=Order.objects.create(customer=self.guest,idempotency_key='discount-qa',payload_hash='qa',payment_method='cash',subtotal=1000,total=1000,is_test=False)
  self.cashier=User.objects.create_user('discount-cashier');self.cashier.groups.add(Group.objects.create(name='cashier'))
  self.kitchen=User.objects.create_user('discount-kitchen');self.kitchen.groups.add(Group.objects.create(name='kitchen'))
 def payload(self,percent=5):return {'discount_percent':percent,'identity_confirmed':True,'reason':'Проверено с гостем','version':self.order.version}
 def apply(self,payload=None):return s.act_on_order(self.order.public_id,self.cashier,'discount',payload or self.payload())
 def test_confirm_recalculates_and_guest_receipt_shows_saved_discount(self):
  self.apply();self.order.refresh_from_db()
  self.assertEqual(self.order.discount_percent,5);self.assertEqual(self.order.discount_amount,50);self.assertEqual(self.order.total,950)
  event=AuditEvent.objects.get(order=self.order,action='discount_confirmed');self.assertEqual(event.actor,self.cashier);self.assertEqual(event.reason,'Проверено с гостем')
  session=self.client.session;session['claim_customer_id']=self.guest.pk;session['claim_order_ids']=[str(self.order.public_id)];session.save()
  payload=self.client.get(f'/api/orders/{self.order.public_id}/').json()['order']
  self.assertEqual(payload['total'],'950.00');self.assertNotIn('discount_review',payload)
  self.assertContains(self.client.get(f'/orders/{self.order.public_id}/receipt/'),'До скидки')
  self.guest.refresh_from_db();self.assertIsNone(self.guest.phone_verified_at);self.assertFalse(self.order.customer_identity_verified)
 def test_requires_role_confirmation_reason_and_valid_rate(self):
  with self.assertRaises(PermissionDenied):s.act_on_order(self.order.public_id,self.kitchen,'discount',self.payload())
  for extra in ({'identity_confirmed':False},{'reason':''},{'discount_percent':100},{'discount_percent':True},{'discount_percent':5.5}):
   with self.subTest(extra=extra),self.assertRaises(ValidationError):self.apply({**self.payload(),**extra})
  self.order.refresh_from_db();self.assertEqual(self.order.total,1000)
 def test_retry_is_read_only_and_zero_can_remove_discount(self):
  self.apply();self.order.refresh_from_db();version=self.order.version
  self.apply(self.payload());self.order.refresh_from_db();self.assertEqual(self.order.version,version);self.assertEqual(self.order.events.filter(action='discount_confirmed').count(),1)
  self.apply(self.payload(0));self.order.refresh_from_db();self.assertEqual(self.order.total,1000);self.assertEqual(self.order.discount_amount,0)
 def test_paid_and_cancelled_orders_are_immutable(self):
  for status,payment_status in [('cancelled','unpaid'),('rejected','unpaid'),('served','paid')]:
   Order.objects.filter(pk=self.order.pk).update(status=status,payment_status=payment_status)
   with self.assertRaises(ValidationError):self.apply()
  Order.objects.filter(pk=self.order.pk).update(status='accepted',payment_status='unpaid')
  Payment.objects.create(order=self.order,amount=1000,method='cash',confirmed_by=self.cashier,idempotency_key='old-payment',reversed_at=timezone.now())
  with self.assertRaises(ValidationError):self.apply()
 def test_stale_version_and_rounding(self):
  with self.assertRaises(ValidationError):self.apply({**self.payload(),'version':99})
  Order.objects.filter(pk=self.order.pk).update(subtotal=Decimal('100.10'),total=Decimal('100.10'))
  self.apply(self.payload(7));self.order.refresh_from_db();self.assertEqual(self.order.discount_amount,Decimal('7.01'));self.assertEqual(self.order.total,Decimal('93.09'))
 def test_staff_api_and_payment_use_new_total(self):
  self.client.force_login(self.cashier)
  response=self.client.post(f'/api/staff/orders/{self.order.public_id}/action/',{'action':'discount',**self.payload()},content_type='application/json')
  self.assertEqual(response.status_code,200);self.assertEqual(response.json()['order']['total'],'950.00')
  Order.objects.filter(pk=self.order.pk).update(status='accepted');self.order.refresh_from_db();s.confirm_payment(self.order,self.cashier,950,cash_received=1000)
  self.order.refresh_from_db();self.assertEqual(self.order.actual_paid,950);self.assertEqual(s.payment_cash_facts(self.order)['change'],'50.00')
