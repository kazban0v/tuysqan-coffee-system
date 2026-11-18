import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase,Client,override_settings
from django.utils import timezone
from .models import Customer,OTPChallenge,Table
from .sms import MemoryBackend,SMSUnavailable
from .test_helpers import authenticate_phone

class PhoneAuthenticationTests(TestCase):
 def setUp(self):
  MemoryBackend.outbox.clear()
  self.table=Table.objects.create(name='Стол 1',is_test=False)
  self.client.get('/table/'+self.table.token()+'/')
 def post(self,url,data,client=None):return (client or self.client).post(url,json.dumps(data),content_type='application/json')
 def request_code(self,phone='+70000000901'):
  response=self.post('/api/otp/request/',{'phone':phone});self.assertEqual(response.status_code,200,response.content)
  code=MemoryBackend.outbox[-1]['code'];self.assertNotIn(code,response.content.decode());self.assertNotIn('code',response.json())
  return code
 @override_settings(SMS_BACKEND='disabled')
 def test_disabled_provider_truthfully_fails_without_customer_or_visible_code(self):
  response=self.post('/api/otp/request/',{'phone':'+70000000901'})
  self.assertEqual(response.status_code,503);self.assertFalse(response.json()['delivery_available'])
  self.assertEqual(MemoryBackend.outbox,[]);self.assertEqual(Customer.objects.count(),0)
  self.assertFalse(OTPChallenge.objects.filter(consumed_at=None).exists())
  self.assertNotIn('demo_code',response.json())
 @override_settings(SMS_BACKEND='memory',SMS_TEST_TRANSPORT_ALLOWED=True)
 def test_new_phone_needs_profile_only_after_verification(self):
  code=self.request_code()
  self.assertEqual(Customer.objects.count(),0)
  self.assertEqual(self.post('/api/account/complete/',{'name':'Premature','consent':True}).status_code,403)
  response=self.post('/api/otp/verify/',{'phone':'+70000000901','code':code})
  self.assertTrue(response.json()['needs_profile']);self.assertEqual(Customer.objects.count(),0)
  self.assertEqual(self.post('/api/account/complete/',{'name':'Customer','consent':False}).status_code,400)
  response=self.post('/api/account/complete/',{'name':'Customer','consent':True,'marketing':False})
  self.assertEqual(response.status_code,200);customer=Customer.objects.get();self.assertEqual(customer.name,'Customer');self.assertFalse(customer.is_test);self.assertIsNotNone(customer.phone_verified_at)
  self.assertEqual(self.client.session['table_token'],self.table.token())
  self.assertEqual(self.client.get('/checkout/').status_code,200)
 @override_settings(SMS_BACKEND='memory',SMS_TEST_TRANSPORT_ALLOWED=True)
 def test_returning_phone_loads_name_without_overwriting_profile(self):
  original=Customer.objects.create(name='Original name',phone='+70000000901',consent_at=timezone.now(),marketing_consent=True,is_test=False)
  consent=original.consent_at;code=self.request_code('8 000 000 09 01')
  response=self.post('/api/otp/verify/',{'phone':'+70000000901','code':code,'name':'Attacker','marketing':False})
  self.assertFalse(response.json()['needs_profile']);self.assertEqual(response.json()['name'],'Original name')
  original.refresh_from_db();self.assertEqual(original.name,'Original name');self.assertEqual(original.consent_at,consent);self.assertTrue(original.marketing_consent)
  self.assertEqual(self.client.session['customer_id'],original.pk)
 @override_settings(SMS_BACKEND='memory',SMS_TEST_TRANSPORT_ALLOWED=True)
 def test_wrong_session_attempt_limit_expiry_replay_and_resend(self):
  code=self.request_code();other=Client()
  self.assertEqual(self.post('/api/otp/verify/',{'phone':'+70000000901','code':code},other).status_code,400)
  self.assertEqual(self.post('/api/otp/request/',{'phone':'+70000000901'}).status_code,400)
  wrong='999999' if code!='999999' else '000000'
  for _ in range(5):self.assertEqual(self.post('/api/otp/verify/',{'phone':'+70000000901','code':wrong}).status_code,400)
  self.assertEqual(OTPChallenge.objects.get().attempts,5)
  self.assertEqual(self.post('/api/otp/verify/',{'phone':'+70000000901','code':code}).status_code,400)
  code=self.request_code('+70000000902');OTPChallenge.objects.filter(phone='+70000000902').update(expires_at=timezone.now()-timedelta(seconds=1))
  self.assertEqual(self.post('/api/otp/verify/',{'phone':'+70000000902','code':code}).status_code,400)
  code=self.request_code('+70000000903')
  self.assertEqual(self.post('/api/otp/verify/',{'phone':'+70000000903','code':code}).status_code,200)
  self.assertEqual(self.post('/api/otp/verify/',{'phone':'+70000000903','code':code}).status_code,400)
 @override_settings(SMS_BACKEND='memory',SMS_TEST_TRANSPORT_ALLOWED=True)
 def test_transport_failure_invalidates_code_without_ghost_profile(self):
  with patch('core.sms.MemoryBackend.send_code',side_effect=SMSUnavailable('Provider unavailable')):
   response=self.post('/api/otp/request/',{'phone':'+70000000901'})
  self.assertEqual(response.status_code,503);self.assertEqual(Customer.objects.count(),0);self.assertFalse(OTPChallenge.objects.filter(consumed_at=None).exists())
 @override_settings(SMS_BACKEND='memory',SMS_TEST_TRANSPORT_ALLOWED=False)
 def test_memory_transport_forbidden_without_explicit_test_override(self):
  self.assertEqual(self.post('/api/otp/request/',{'phone':'+70000000901'}).status_code,503)
 def test_legacy_anonymous_session_cannot_checkout_or_create(self):
  customer=Customer.objects.create(name='Old anonymous',phone='guest-old',consent_at=timezone.now(),is_test=False)
  session=self.client.session;session['customer_id']=customer.pk;session.save()
  self.assertRedirects(self.client.get('/checkout/'),'/account/login/')
  response=self.post('/api/orders/',{})
  self.assertEqual(response.status_code,401)
  self.assertEqual(response.json()['redirect'],'/account/login/')
 def test_csrf_enforced_for_phone_endpoints(self):
  strict=Client(enforce_csrf_checks=True)
  for path in ['/api/otp/request/','/api/otp/verify/','/api/account/complete/']:
   self.assertEqual(self.post(path,{},strict).status_code,403)
