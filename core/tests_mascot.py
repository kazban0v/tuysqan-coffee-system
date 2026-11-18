import json
from datetime import timedelta
from django.test import TestCase,Client
from django.utils import timezone
from django.contrib.auth.models import User,Group
from .models import Customer,Order,Review,Table,MenuCategory,MenuItem
from . import services as s

class GriffinMascotTests(TestCase):
 def setUp(self):
  self.guest=Customer.objects.create(name='Mascot test',phone='+77000000021',is_test=True,consent_at=timezone.now(),phone_verified_at=timezone.now())
  self.table=Table.objects.create(name='Mascot test',is_test=True)
  self.order=Order.objects.create(customer=self.guest,table=self.table,idempotency_key='mascot-only',payload_hash='test',is_test=True,payment_method='cash',status='preparing')
  session=self.client.session;session['customer_id']=self.guest.pk;session.save()
  self.url=f'/api/orders/{self.order.public_id}/'
 def post(self,suffix,payload,client=None):return (client or self.client).post(self.url+suffix+'/',json.dumps(payload),content_type='application/json')
 def status(self,value,served_at=None):
  self.order.status=value;self.order.served_at=served_at;self.order.save(update_fields=['status','served_at']);return self.client.get(self.url).json()['order']
 def test_accepted_preparing_ready_have_current_state(self):
  self.assertEqual(self.status('accepted')['mascot']['state'],'waiting')
  self.assertEqual(self.status('preparing')['mascot']['state'],'preparing')
  self.assertEqual(self.status('ready')['mascot']['state'],'waiting')
 def test_server_served_timestamp_controls_fifteen_minutes(self):
  now=timezone.now();self.status('served',now-timedelta(minutes=14))
  before=s.mascot_state(self.order,now=now);self.assertEqual(before['state'],'served')
  after=s.mascot_state(self.order,now=now+timedelta(minutes=1));self.assertEqual(after['state'],'feedback')
  self.assertEqual(before['feedback_due_at'],(self.order.served_at+timedelta(minutes=15)).isoformat())
  self.assertEqual(self.client.get(self.url).json()['order']['served_at'],self.order.served_at.isoformat())
 def test_wish_does_not_require_or_create_rating(self):
  r=self.post('mascot',{'action':'wish','comment':'Тихая музыка'});self.assertEqual(r.status_code,201)
  self.order.refresh_from_db();self.assertEqual(self.order.guest_wish,'Тихая музыка');self.assertIsNotNone(self.order.guest_wish_at);self.assertFalse(Review.objects.exists())
  self.assertIsNone(self.client.get(self.url).json()['order']['mascot']['state'])
  duplicate=self.post('mascot',{'action':'wish','comment':'Другой текст'});self.assertFalse(duplicate.json()['created'])
  self.order.refresh_from_db();self.assertEqual(self.order.guest_wish,'Тихая музыка')
  self.assertEqual(self.status('served',timezone.now())['mascot']['state'],'served')
 def test_wish_validation_and_rating_before_served(self):
  for comment in ('',' ',['text'],'x'*1001):self.assertEqual(self.post('mascot',{'action':'wish','comment':comment}).status_code,400)
  self.assertEqual(self.post('review',{'rating':5}).status_code,400)
  self.status('cancelled');self.assertEqual(self.post('mascot',{'action':'wish','comment':'Test'}).status_code,400)
 def test_dismissal_survives_reload_and_status_changes(self):
  self.assertTrue(self.post('mascot',{'action':'dismiss'}).json()['created'])
  self.assertFalse(self.post('mascot',{'action':'dismiss'}).json()['created'])
  for status in ('preparing','ready','served'):
   payload=self.status(status,timezone.now()-timedelta(minutes=20) if status=='served' else None)
   self.assertTrue(payload['mascot']['dismissed']);self.assertIsNone(payload['mascot']['state']);self.assertFalse(payload['can_review'])
  self.assertEqual(self.client.get('/orders/'+str(self.order.public_id)+'/').status_code,200)
 def test_service_review_once_and_no_further_feedback(self):
  self.status('served',timezone.now())
  first=self.post('review',{'rating':5,'comment':'Отлично','kind':'service'});self.assertTrue(first.json()['created'])
  second=self.post('review',{'rating':1,'comment':'Overwrite','kind':'experience'});self.assertFalse(second.json()['created'])
  review=Review.objects.get(order=self.order);self.assertEqual(review.rating,5);self.assertEqual(review.kind,'service')
  payload=self.status('served',timezone.now()-timedelta(minutes=16));self.assertTrue(payload['mascot']['review_sent']);self.assertIsNone(payload['mascot']['state']);self.assertFalse(payload['can_review'])
 def test_feedback_validation_and_plain_text(self):
  self.status('served',timezone.now()-timedelta(minutes=16))
  for rating in (True,1.5,0,6,None,{},'05'):self.assertEqual(self.post('review',{'rating':rating}).status_code,400)
  self.assertEqual(self.post('review',{'rating':5,'comment':'x'*2001}).status_code,400)
  self.assertEqual(self.post('review',{'rating':5,'kind':'other'}).status_code,400)
  self.assertEqual(self.post('review',{'rating':4,'comment':'<script>alert(1)</script>','kind':'experience'}).status_code,200)
  self.assertEqual(Review.objects.get(order=self.order).comment,'<script>alert(1)</script>')
 def test_other_session_cannot_read_dismiss_or_submit(self):
  stranger=Client();self.assertEqual(stranger.get(self.url).status_code,403)
  for suffix,body in [('mascot',{'action':'dismiss'}),('mascot',{'action':'wish','comment':'Test'}),('review',{'rating':5})]:self.assertEqual(self.post(suffix,body,stranger).status_code,403)
  self.order.refresh_from_db();self.assertIsNone(self.order.mascot_dismissed_at);self.assertFalse(self.order.guest_wish)
 def test_unverified_claim_scope_still_checked(self):
  self.guest.is_test=False;self.guest.save()
  claim=Client();session=claim.session;session['claim_customer_id']=self.guest.pk;session['claim_order_ids']=[];session.save()
  self.assertEqual(claim.get(self.url).status_code,403)
  session=claim.session;session['claim_order_ids']=[str(self.order.public_id)];session.save()
  self.assertEqual(claim.get(self.url).status_code,200)
  self.assertEqual(self.post('mascot',{'action':'wish','comment':'Спасибо'},claim).status_code,201)
 def test_csrf_and_post_only(self):
  secure=Client(enforce_csrf_checks=True);session=secure.session;session['customer_id']=self.guest.pk;session.save()
  self.assertEqual(self.post('mascot',{'action':'dismiss'},secure).status_code,403)
  self.assertEqual(secure.get(self.url+'mascot/').status_code,405)
 def test_preview_protected_and_has_no_writes(self):
  self.assertEqual(Client().get('/admin/mascot-preview/').status_code,302)
  staff=User.objects.create_user('mascot-reviewer');staff.groups.add(Group.objects.create(name='cashier'));self.client.force_login(staff)
  before=Order.objects.count()
  for state in ('preparing','served','feedback'):
   r=self.client.get('/admin/mascot-preview/',{'state':state});self.assertContains(r,'mascot-preview-data');self.assertEqual(r.context['preview_order']['mascot']['state'],state)
  self.assertEqual(Order.objects.count(),before);self.assertFalse(Review.objects.exists())
 def test_real_serve_action_sets_timestamp_and_enables_mascot(self):
  staff=User.objects.create_user('mascot-cashier');staff.groups.add(Group.objects.create(name='cashier'))
  self.status('ready');s.act_on_order(self.order.public_id,staff,'serve');self.order.refresh_from_db()
  self.assertIsNotNone(self.order.served_at);self.assertEqual(s.mascot_state(self.order)['state'],'served')
 def test_status_window_keeps_feedback_slot_without_removed_hero(self):
  self.status('new')
  response=self.client.get('/orders/'+str(self.order.public_id)+'/')
  self.assertNotContains(response,'class="guest-status-mascot"')
  self.assertContains(response,'id="guest-status-mascot-slot"')
  self.assertNotContains(response,'/static/mascot/tuysqan-griffin.png')
  self.assertEqual(response.context['order']['mascot']['state'],'waiting')
 def test_feedback_due_uses_server_clock_after_no_page_requests(self):
  from unittest.mock import patch
  served=timezone.now();self.status('served',served)
  with patch('core.services.timezone.now',return_value=served+timedelta(minutes=16)):
   new_tab=Client();session=new_tab.session;session['customer_id']=self.guest.pk;session.save()
   payload=new_tab.get(self.url).json()['order']
  self.assertEqual(payload['mascot']['state'],'feedback')
  self.assertEqual(payload['served_at'],served.isoformat())

 def test_wish_available_immediately_without_rating_and_sent_once(self):
  for status in ('new','accepted','preparing','ready'):
   with self.subTest(status=status):
    Order.objects.filter(pk=self.order.pk).update(status=status,guest_wish='',guest_wish_at=None)
    response=self.post('mascot',{'action':'wish','comment':'Пожелание во время ожидания'})
    self.assertEqual(response.status_code,201,response.content)
    self.assertFalse(Review.objects.filter(order=self.order).exists())
    self.assertEqual(self.post('review',{'rating':5}).status_code,400)
    self.assertFalse(self.post('mascot',{'action':'wish','comment':'Повтор'}).json()['created'])
