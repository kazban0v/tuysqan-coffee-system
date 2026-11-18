import json
import time
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase,Client
from django.utils import timezone
from django.core.exceptions import ValidationError,PermissionDenied
from django.contrib.auth.models import User,Group
from .models import Customer,Table,MenuCategory,MenuItem,Order,Payment,LoyaltyEntry,LoyaltyPolicy
from . import services as s

class UnifiedLoyaltyTests(TestCase):
 def setUp(self):
  policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
  self.customer=Customer.objects.create(phone='+77000000051',name='Private stored name',consent_at=timezone.now(),is_test=False)
  self.other=Customer.objects.create(phone='+77000000052',name='Other',consent_at=timezone.now(),is_test=False)
  self.table=Table.objects.create(name='Стол QA',is_test=False)
  category=MenuCategory.objects.create(slug='loyalty-qa',name_ru='QA',name_kz='QA')
  self.item=MenuItem.objects.create(category=category,slug='loyalty-qa',name_ru='QA meal',name_kz='QA meal',kind='food',price=1000,is_test=False)
  self.cashier=User.objects.create_user('loyalty-cashier');self.cashier.groups.add(Group.objects.create(name='cashier'))
  self.manager=User.objects.create_user('loyalty-manager');self.manager.groups.add(Group.objects.create(name='manager'))
  self.kitchen=User.objects.create_user('loyalty-kitchen');self.kitchen.groups.add(Group.objects.create(name='kitchen'))
  self.seed_order=Order.objects.create(customer=self.customer,table=self.table,idempotency_key='seed-ledger',payload_hash='seed',payment_method='cash',status='served',payment_status='paid',subtotal=50000,total=50000,actual_paid=50000,is_test=False)
  payment=Payment.objects.create(order=self.seed_order,amount=50000,method='cash',confirmed_by=self.cashier,idempotency_key='seed-payment')
  LoyaltyEntry.objects.create(customer=self.customer,order=self.seed_order,payment=payment,amount=50000,kind='purchase')
  self.client.get('/table/'+self.table.token()+'/')
  session=self.client.session;session['claim_customer_id']=self.customer.pk;session['claim_order_scope']='loyalty-qa-scope';session['claim_order_ids']=[];session.save()
 def payload(self,**extra):return {'idempotency_key':'new-order-qa','items':[{'id':self.item.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':'cash',**extra}
 def offer(self,client=None):return (client or self.client).get('/api/account/discount-offer/').json()
 def post(self,payload,client=None):return (client or self.client).post('/api/orders/',json.dumps(payload),content_type='application/json')
 def create_qr(self,choice=True,**extra):
  quote=self.offer();response=self.post(self.payload(discount_choice=choice,discount_offer_token=quote['token'],**extra));self.assertEqual(response.status_code,201,response.content);return Order.objects.get(public_id=response.json()['order']['public_id'])
 def test_public_offer_has_only_rate_token_and_existence_no_private_profile(self):
  quote=self.offer();self.assertEqual(set(quote),{'percent','token','exists','needs_name'});self.assertEqual(quote['percent'],5)
  self.assertNotIn(self.customer.name,json.dumps(quote));self.assertNotIn('50000',json.dumps(quote))
  self.assertEqual(Client().get('/api/account/discount-offer/').status_code,403)
  self.assertEqual(self.client.get(f'/api/orders/{self.seed_order.public_id}/').status_code,403)
 def test_qr_apply_is_server_calculated_and_choice_persisted(self):
  order=self.create_qr(discount_percent=99,total='1')
  self.assertEqual(order.discount_percent,5);self.assertEqual(order.discount_amount,50);self.assertEqual(order.total,950)
  self.assertEqual(order.discount_choice,'applied');self.assertEqual(order.discount_offer_percent,5);self.assertTrue(order.loyalty_eligible);self.assertFalse(order.customer_identity_verified)
  self.customer.refresh_from_db();self.assertIsNone(self.customer.phone_verified_at)
  payload=self.client.get(f'/api/orders/{order.public_id}/').json()['order'];self.assertEqual(payload['discount_choice'],'applied');self.assertNotIn('discount_review',payload)
 def test_qr_decline_persists_normal_price_and_retry_ignores_token_expiry(self):
  quote=self.offer();payload=self.payload(discount_choice=False,discount_offer_token=quote['token'])
  first=self.post(payload);self.assertEqual(first.status_code,201)
  order=Order.objects.get(public_id=first.json()['order']['public_id']);self.assertEqual(order.total,1000);self.assertEqual(order.discount_percent,0);self.assertEqual(order.discount_choice,'declined')
  payload['discount_offer_token']='expired-or-lost-token-on-retry';retry=self.post(payload);self.assertEqual(retry.status_code,200);self.assertEqual(Order.objects.count(),2)
  payload['discount_choice']=True;self.assertEqual(self.post(payload).status_code,400)
 def test_forged_expired_or_context_changed_quotes_rejected_without_orders(self):
  quote=self.offer()
  bad=self.post(self.payload(discount_choice=True,discount_offer_token='forged'));self.assertEqual(bad.json()['code'],'offer_changed')
  with patch('django.core.signing.time.time',return_value=time.time()-1000):old=self.offer()
  expired=self.post(self.payload(discount_choice=True,discount_offer_token=old['token']));self.assertEqual(expired.json()['code'],'offer_expired')
  other_browser=Client();other_browser.get('/table/'+self.table.token()+'/');session=other_browser.session;session['claim_customer_id']=self.customer.pk;session['claim_order_scope']='another';session.save()
  mismatch=self.post(self.payload(discount_choice=True,discount_offer_token=quote['token']),other_browser);self.assertEqual(mismatch.json()['code'],'offer_changed')
  self.assertEqual(Order.objects.count(),1)
 def test_quote_changes_when_tier_changes_and_token_cannot_choose_client_rate(self):
  quote=self.offer();LoyaltyEntry.objects.filter(customer=self.customer).update(amount=120000)
  response=self.post(self.payload(discount_choice=True,discount_offer_token=quote['token']));self.assertEqual(response.status_code,400);self.assertEqual(response.json()['code'],'offer_changed')
  self.assertEqual(self.offer()['percent'],7)
 def test_pay_accrues_once_for_claimed_phone_declining_or_applying_and_refund_reverses(self):
  order=self.create_qr(choice=False);self.assertEqual(self.customer.loyalty_total,50000)
  order=s.act_on_order(order.public_id,self.cashier,'accept',{'eta':10});s.confirm_payment(order,self.cashier,1000);s.confirm_payment(order,self.cashier,1000)
  self.assertEqual(LoyaltyEntry.objects.filter(order=order,kind='purchase').count(),1);self.assertEqual(self.customer.loyalty_total,51000)
  s.reverse_payment(order,self.manager,'QA return');self.assertEqual(self.customer.loyalty_total,50000)
  self.assertEqual(LoyaltyEntry.objects.filter(order=order,kind='reversal').count(),1)
 def test_legacy_claim_payment_now_accrues_without_repricing_order(self):
  response=self.post(self.payload());self.assertEqual(response.status_code,201)
  order=Order.objects.get(public_id=response.json()['order']['public_id']);self.assertFalse(order.loyalty_eligible);self.assertEqual(order.discount_choice,'legacy');self.assertEqual(order.discount_percent,0)
  s.act_on_order(order.public_id,self.cashier,'accept',{'eta':5});s.confirm_payment(order,self.cashier,1000);self.assertEqual(LoyaltyEntry.objects.get(order=order).amount,1000)
 def test_reconcile_old_confirmed_payments_is_idempotent_and_reversible(self):
  from django.core.management import call_command
  from io import StringIO
  LoyaltyEntry.objects.filter(order=self.seed_order).delete()
  self.assertEqual(self.offer()['percent'],0)
  call_command('reconcile_loyalty',phone=self.customer.phone,stdout=StringIO())
  self.assertEqual(self.customer.loyalty_total,0)
  call_command('reconcile_loyalty',phone=self.customer.phone,apply=True,stdout=StringIO())
  call_command('reconcile_loyalty',phone=self.customer.phone,apply=True,stdout=StringIO())
  self.assertEqual(self.customer.loyalty_total,50000)
  self.assertEqual(self.offer()['percent'],5)
  s.reverse_payment(self.seed_order,self.manager,'Return restored payment')
  call_command('reconcile_loyalty',phone=self.customer.phone,apply=True,stdout=StringIO())
  self.assertEqual(self.customer.loyalty_total,0)
 def test_reconcile_ignores_missing_or_inconsistent_payment_evidence(self):
  from django.core.management import call_command
  from io import StringIO
  LoyaltyEntry.objects.filter(order=self.seed_order).delete()
  self.seed_order.actual_paid=51000;self.seed_order.save()
  call_command('reconcile_loyalty',phone=self.customer.phone,apply=True,stdout=StringIO())
  self.assertEqual(self.customer.loyalty_total,0)
 def test_claim_account_uses_same_available_rate_without_revealing_hidden_orders(self):
  response=self.client.get('/account/')
  self.assertEqual(response.status_code,200)
  self.assertEqual(response.context['loyalty']['personal']['percent'],5)
  self.assertEqual(response.context['loyalty']['personal']['total'],0)
 def test_staff_lookup_is_authorized_read_only_and_new_name_requested(self):
  self.assertEqual(Client().post('/api/staff/discount-offer/',{'phone':self.customer.phone},content_type='application/json').status_code,403)
  self.client.force_login(self.cashier);before=Customer.objects.count()
  response=self.client.post('/api/staff/discount-offer/',{'phone':self.customer.phone},content_type='application/json');self.assertEqual(response.json()['percent'],5);self.assertTrue(response.json()['exists']);self.assertFalse(response.json()['needs_name'])
  unknown=self.client.post('/api/staff/discount-offer/',{'phone':'+77000000053'},content_type='application/json');self.assertTrue(unknown.json()['needs_name']);self.assertEqual(unknown.json()['percent'],0);self.assertEqual(Customer.objects.count(),before)
  self.client.force_login(self.kitchen);self.assertEqual(self.client.post('/api/staff/discount-offer/',{'phone':self.customer.phone},content_type='application/json').status_code,403)
 def test_pos_named_phone_apply_and_decline_work_in_hall_and_takeaway(self):
  for index,(mode,choice) in enumerate([('dine_in',True),('takeaway',False)]):
   quote=s.discount_offer(self.customer,context=f'pos:{self.cashier.pk}')
   payload=self.payload(idempotency_key='pos-unified-'+str(index),fulfillment=mode,customer={'phone':self.customer.phone,'consent':True},discount_choice=choice,discount_offer_token=quote['token'],accept_order=True,eta=10)
   order,created=s.create_pos_order(self.cashier,payload);self.assertTrue(created);self.assertEqual(order.source,'pos');self.assertEqual(order.total,950 if choice else 1000);self.assertEqual(order.discount_choice,'applied' if choice else 'declined' if quote['percent'] else 'not_available')
   repeat,created=s.create_pos_order(self.cashier,{**payload,'discount_offer_token':'stale'});self.assertFalse(created);self.assertEqual(repeat.pk,order.pk)
   with self.assertRaises(ValidationError):s.create_pos_order(self.cashier,{**payload,'discount_choice':not choice})
   s.confirm_payment(order,self.cashier,order.total);self.assertEqual(LoyaltyEntry.objects.filter(order=order).count(),1)
   self.customer.refresh_from_db();self.assertIsNone(self.customer.phone_verified_at);self.assertEqual(self.customer.name,'Private stored name')
 def test_new_pos_phone_needs_name_and_zero_offer_choice_safe(self):
  phone='+77000000053';quote=s.discount_offer(phone=phone,context=f'pos:{self.cashier.pk}')
  payload=self.payload(idempotency_key='pos-newphone',fulfillment='takeaway',customer={'phone':phone,'consent':True},discount_choice=False,discount_offer_token=quote['token'])
  with self.assertRaises(ValidationError):s.create_pos_order(self.cashier,payload)
  order,_=s.create_pos_order(self.cashier,{**payload,'customer':{'phone':phone,'name':'New guest','consent':True}});self.assertEqual(order.discount_choice,'not_available');self.assertTrue(order.loyalty_eligible);self.assertIsNone(order.customer.phone_verified_at)
 def test_walkin_and_test_orders_never_accrue_and_manual_override_cannot_change_choice(self):
  order,_=s.create_pos_order(self.cashier,self.payload(idempotency_key='pos-walkin-new',fulfillment='takeaway',discount_choice=False,accept_order=True))
  s.confirm_payment(order,self.cashier,1000);self.assertFalse(order.loyalty_eligible);self.assertFalse(LoyaltyEntry.objects.filter(order=order).exists())
  claimed=self.create_qr()
  with self.assertRaises(ValidationError):s.act_on_order(claimed.public_id,self.cashier,'discount',{'discount_percent':0,'identity_confirmed':True,'reason':'override'})
  Order.objects.filter(pk=claimed.pk).update(is_test=True,status='accepted');s.confirm_payment(claimed,self.cashier,950);self.assertFalse(LoyaltyEntry.objects.filter(order=claimed).exists())
 def test_inactive_policy_has_no_offer_and_no_accrual(self):
  LoyaltyPolicy.objects.update(confirmed=False);self.assertEqual(self.offer()['percent'],0)
  order=self.create_qr(choice=False);self.assertEqual(order.discount_percent,0);s.act_on_order(order.public_id,self.cashier,'accept',{'eta':5});s.confirm_payment(order,self.cashier,1000);self.assertFalse(LoyaltyEntry.objects.filter(order=order).exists())
