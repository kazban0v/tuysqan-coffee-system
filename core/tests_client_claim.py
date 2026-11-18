import json
from django.test import TestCase,Client
from django.utils import timezone
from django.contrib.auth.models import User,Group
from .models import Customer,Table,MenuCategory,MenuItem,Order,LoyaltyEntry,LoyaltyPolicy
from .services import create_order,act_on_order
class ClientClaimTests(TestCase):
 def setUp(self):
  self.table=Table.objects.create(name='Стол 8')
  cat=MenuCategory.objects.create(slug='food',name_ru='Блюда',name_kz='Тағамдар')
  self.food=MenuItem.objects.create(slug='food',category=cat,name_ru='Блюдо',name_kz='Тағам',price=1000)
  self.existing=Customer.objects.create(name='Private Name',phone='+77770000001',phone_verified_at=timezone.now(),consent_at=timezone.now(),is_test=False)
  self.client.get('/table/'+self.table.token()+'/')
 def post(self,path,data,client=None):return (client or self.client).post(path,json.dumps(data),content_type='application/json')
 def payload(self):return {'items':[{'id':self.food.pk,'quantity':1}],'table_token':self.table.token(),'payment_method':'cash','idempotency_key':'client-claim-order'}
 def test_existing_phone_reveals_no_identity_history_or_discount(self):
  old,_=create_order(self.existing,{**self.payload(),'idempotency_key':'prior-private-order'})
  r=self.post('/api/account/identify/',{'phone':'87770000001','consent':True,'name':'Forged'})
  self.assertEqual(r.status_code,200);self.assertNotIn('Private Name',r.content.decode())
  self.existing.refresh_from_db();self.assertEqual(self.existing.name,'Private Name')
  self.assertEqual(self.client.get('/api/orders/'+str(old.public_id)+'/').status_code,403)
  self.assertNotContains(self.client.get('/account/'),old.number)
  self.assertEqual(self.client.get('/checkout/').context['checkout_discount_percent'],0)
 def test_new_phone_requires_name_and_consent(self):
  d={'phone':'+77770000002','consent':True}
  self.assertTrue(self.post('/api/account/identify/',d).json()['needs_name'])
  self.assertFalse(Customer.objects.filter(phone=d['phone']).exists())
  self.assertEqual(self.post('/api/account/identify/',{**d,'name':'Guest','consent':False}).status_code,400)
  self.assertEqual(self.post('/api/account/identify/',{**d,'name':'Guest'}).status_code,200)
  c=Customer.objects.get(phone=d['phone']);self.assertIsNone(c.phone_verified_at)
 def test_claim_order_owned_by_session_and_paid_phone_purchase_accrues(self):
  self.post('/api/account/identify/',{'phone':self.existing.phone,'consent':True})
  r=self.post('/api/orders/',self.payload());self.assertEqual(r.status_code,201,r.content)
  o=Order.objects.get(public_id=r.json()['order']['public_id']);self.assertFalse(o.customer_identity_verified);self.assertEqual(o.discount_percent,0)
  self.assertEqual(self.post('/api/orders/',self.payload()).status_code,200)
  other=Client();other.get('/table/'+self.table.token()+'/');self.post('/api/account/identify/',{'phone':self.existing.phone,'consent':True},other)
  self.assertEqual(other.get('/api/orders/'+str(o.public_id)+'/').status_code,403)
  r2=self.post('/api/orders/',self.payload(),other);self.assertEqual(r2.status_code,201);self.assertNotEqual(r.json()['order']['public_id'],r2.json()['order']['public_id'])
  u=User.objects.create_user('cash');u.groups.add(Group.objects.create(name='cashier'))
  policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
  act_on_order(o.public_id,u,'accept',{'eta':10});act_on_order(o.public_id,u,'pay',{'amount':'1000'})
  self.assertEqual(LoyaltyEntry.objects.get(order=o).amount,1000)
 def test_landing_has_no_qr_shortcut_and_claim_requires_qr(self):
  r=self.client.get('/');self.assertNotContains(r,'?view=menu');self.assertNotContains(r,'order-bridge.js')
  self.assertRedirects(self.client.get('/?view=menu'),'/#menu',fetch_redirect_response=False)
  self.assertEqual(self.post('/api/account/identify/',{'phone':self.existing.phone,'consent':True},Client()).status_code,403)

 def stale_claim(self):
  session=self.client.session
  session['claim_customer_id']=99999999
  session['claim_order_scope']='expired-scope'
  session['claim_order_ids']=['old-order']
  session.save()
 def test_stale_guest_redirects_to_phone_and_preserves_table(self):
  self.stale_claim()
  self.assertRedirects(self.client.get('/checkout/'),'/account/login/',fetch_redirect_response=False)
  self.assertEqual(self.client.get('/account/login/').status_code,200)
  self.assertEqual(self.client.session['table_token'],self.table.token())
  self.assertNotIn('claim_customer_id',self.client.session)
  self.assertNotIn('claim_order_ids',self.client.session)
  self.assertEqual(self.post('/api/account/identify/',{'phone':self.existing.phone,'consent':True}).status_code,200)
  self.assertEqual(self.client.get('/checkout/').status_code,200)
  self.assertEqual(self.post('/api/orders/',self.payload()).status_code,201)
 def test_stale_guest_on_open_checkout_gets_recovery_not_permission_error(self):
  self.stale_claim()
  response=self.post('/api/orders/',self.payload())
  self.assertEqual(response.status_code,401)
  self.assertEqual(response.json()['redirect'],'/account/login/')
  self.assertNotIn('Недостаточно прав',response.json()['error'])
  self.assertEqual(Order.objects.count(),0)
  self.assertEqual(self.client.session['table_token'],self.table.token())
 def test_stale_guest_cannot_reuse_old_order_scope(self):
  self.stale_claim()
  self.assertRedirects(self.client.get('/account/'),'/account/login/',fetch_redirect_response=False)
  self.assertNotIn('claim_order_ids',self.client.session)

 def test_old_test_phone_can_complete_real_guest_profile_without_login_loop(self):
  old=Customer.objects.create(name='Old private test name',phone='+77770000003',phone_verified_at=timezone.now(),consent_at=timezone.now(),is_test=True)
  d={'phone':old.phone,'consent':True}
  first=self.post('/api/account/identify/',d)
  self.assertTrue(first.json()['needs_name'])
  self.assertNotIn(old.name,first.content.decode())
  old.refresh_from_db();self.assertTrue(old.is_test)
  self.assertEqual(self.post('/api/account/identify/',{**d,'name':'Real guest','consent':False}).status_code,400)
  completed=self.post('/api/account/identify/',{**d,'name':'Real guest'})
  self.assertEqual(completed.status_code,200)
  old.refresh_from_db();self.assertFalse(old.is_test);self.assertIsNone(old.phone_verified_at)
  self.assertEqual(old.name,'Real guest')
  self.assertRedirects(self.client.get('/account/login/'),'/checkout/',fetch_redirect_response=False)
  self.assertEqual(self.client.get('/checkout/').status_code,200)
  self.assertEqual(self.post('/api/orders/',self.payload()).status_code,201)
  order=Order.objects.get();self.assertFalse(order.customer_identity_verified);self.assertEqual(order.discount_percent,0)
