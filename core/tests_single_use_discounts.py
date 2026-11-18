"""Financial policy regressions. Uses only Django's disposable test database."""
import uuid
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import IntegrityError,transaction
from django.utils import timezone
from . import tests_unified_loyalty as fixtures
from . import services as s
from .models import LoyaltyEntry,LoyaltyRedemption,Order

class SingleUseDiscountTests(TestCase):
 def setUp(self):fixtures.UnifiedLoyaltyTests.setUp(self)
 def qr(self,choice=True,**extra):
  offer=s.discount_offer(self.customer,context='unit-qr')
  return s.create_order(self.customer,{'idempotency_key':str(uuid.uuid4()),'items':[{'id':self.item.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':'cash','discount_choice':choice,'discount_offer_token':offer['token'],**extra},unverified_claim=True,discount_context='unit-qr')[0]
 def pos(self,**extra):
  offer=s.discount_offer(self.customer,context=f'pos:{self.cashier.pk}')
  return s.create_pos_order(self.cashier,{'idempotency_key':str(uuid.uuid4()),'items':[{'id':self.item.pk,'quantity':1}],'fulfillment':'takeaway','customer':{'phone':self.customer.phone,'consent':True},'payment_method':'cash','discount_choice':True,'discount_offer_token':offer['token'],'accept_order':True,**extra})[0]
 def test_level_reserves_and_second_order_cannot_apply_it(self):
  old=s.discount_offer(self.customer,context='unit-qr')
  o=self.qr();self.assertEqual(o.total,950);self.assertEqual(self.customer.discount_percent,0)
  self.assertEqual(LoyaltyRedemption.objects.filter(active=True).count(),1)
  with self.assertRaises(ValidationError):self.qr(discount_offer_token=old['token'])
  self.assertEqual(Order.objects.count(),2)
 def test_decline_never_reserves_or_erases_accumulation(self):
  o=self.qr(False);self.assertEqual(o.total,1000);self.assertEqual(self.customer.discount_percent,5)
  self.assertFalse(LoyaltyRedemption.objects.exists());self.assertEqual(self.customer.loyalty_total,50000)
 def test_cancel_unpaid_restores_level(self):
  o=self.qr();s.act_on_order(o.public_id,self.cashier,'reject',{'reason':'Guest changed mind'})
  self.assertEqual(self.customer.discount_percent,5);self.assertFalse(LoyaltyRedemption.objects.get(order=o).active)
  self.assertEqual(self.qr().discount_percent,5)
 def test_paid_consumes_and_refund_does_not_create_another_use(self):
  o=self.qr();s.act_on_order(o.public_id,self.cashier,'accept',{});s.confirm_payment(o,self.cashier,950)
  use=LoyaltyRedemption.objects.get(order=o);self.assertIsNotNone(use.consumed_at)
  self.assertEqual(self.customer.loyalty_total,50950);self.assertEqual(self.customer.discount_percent,0)
  s.reverse_payment(o,self.manager,'Refund test');self.assertEqual(self.customer.loyalty_total,50000)
  self.assertEqual(self.customer.discount_percent,0)
 def test_next_level_is_available_without_resetting_balance(self):
  self.qr();LoyaltyEntry.objects.filter(customer=self.customer).update(amount=100000)
  self.assertEqual(self.customer.discount_percent,7);self.assertEqual(self.qr().discount_percent,7)
  self.assertEqual(self.customer.loyalty_total,100000);self.assertEqual(self.customer.discount_percent,0)
 def test_each_earned_level_remains_a_separate_single_use(self):
  LoyaltyEntry.objects.filter(customer=self.customer).update(amount=150000)
  self.assertEqual([self.qr().discount_percent for _ in range(3)],[10,7,5])
  self.assertEqual(self.customer.discount_percent,0)
 def test_residential_repeatable_and_does_not_spend_loyalty(self):
  for community in ['vremena_goda','premiera','vremena_goda']:
   o=self.pos(discount_source='residential',residential_complex=community,residency_confirmed=True,discount_percent=99)
   self.assertEqual(o.discount_percent,10);self.assertEqual(o.total,900)
   self.assertEqual(o.residential_complex,community);self.assertEqual(o.discount_source,'residential')
   self.assertEqual(s.order_data(o,include_customer=True)['discount_source'],'residential')
  self.assertEqual(self.customer.discount_percent,5);self.assertFalse(LoyaltyRedemption.objects.exists())
 def test_residential_decline_keeps_regular_total(self):
  o=self.pos(discount_source='residential',residential_complex='premiera',residency_confirmed=True,discount_choice=False)
  self.assertEqual(o.total,1000);self.assertEqual(o.discount_choice,'declined');self.assertEqual(o.discount_offer_percent,10)
 def test_residential_requires_cashier_confirmation_and_valid_complex(self):
  for extra in [{'residency_confirmed':False,'residential_complex':'premiera'},{'residency_confirmed':True,'residential_complex':'other'}]:
   with self.assertRaises(ValidationError):self.pos(discount_source='residential',**extra)
  with self.assertRaises(PermissionDenied):self.qr(discount_source='residential',residential_complex='premiera',residency_confirmed=True)
 def test_cannot_stack_sources(self):
  with self.assertRaises(ValidationError):self.pos(discount_source='loyalty+residential')
  o=self.pos(discount_source='residential',residential_complex='premiera',residency_confirmed=True)
  self.assertEqual(o.discount_percent,10)
 def test_db_constraint_prevents_concurrent_duplicate_reservation(self):
  o=self.qr();other=self.qr(False)
  with self.assertRaises(IntegrityError),transaction.atomic():
   LoyaltyRedemption.objects.create(customer=self.customer,order=other,threshold=50000,percent=5)
  self.assertEqual(LoyaltyRedemption.objects.filter(active=True).count(),1)
 def test_exact_order_retry_does_not_spend_again(self):
  offer=s.discount_offer(self.customer,context=f'pos:{self.cashier.pk}')
  p={'idempotency_key':'one-retry-key','items':[{'id':self.item.pk,'quantity':1}],'fulfillment':'takeaway','customer':{'phone':self.customer.phone,'consent':True},'payment_method':'cash','discount_choice':True,'discount_offer_token':offer['token'],'accept_order':True}
  first,created=s.create_pos_order(self.cashier,p);second,created=s.create_pos_order(self.cashier,p)
  self.assertEqual(first.pk,second.pk);self.assertFalse(created);self.assertEqual(LoyaltyRedemption.objects.count(),1)
 def test_legacy_cashier_path_cannot_bypass_spent_level(self):
  self.qr();o=Order.objects.create(customer=self.customer,idempotency_key='legacy-new',payload_hash='x',payment_method='cash',subtotal=1000,total=1000,is_test=False)
  with self.assertRaises(ValidationError):s.confirm_order_discount(o.public_id,self.cashier,{'discount_percent':5,'reason':'test','identity_confirmed':True})
