"""Test-only phone authentication through the actual HTTP endpoints."""
import json
from django.test import override_settings
from .sms import MemoryBackend

def authenticate_phone(client,phone='+70000000901',name='Test customer'):
 with override_settings(SMS_BACKEND='memory',SMS_TEST_TRANSPORT_ALLOWED=True):
  response=client.post('/api/otp/request/',json.dumps({'phone':phone}),content_type='application/json')
  assert response.status_code==200,response.content
  code=MemoryBackend.outbox[-1]['code']
  response=client.post('/api/otp/verify/',json.dumps({'phone':phone,'code':code}),content_type='application/json')
  assert response.status_code==200,response.content
  if response.json()['needs_profile']:
   response=client.post('/api/account/complete/',json.dumps({'name':name,'consent':True}),content_type='application/json')
   assert response.status_code==200,response.content
