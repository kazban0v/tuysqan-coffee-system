import importlib.util,json,tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User,Group
from django.test import TestCase,Client,RequestFactory,override_settings
from django.core.cache import cache
from django.utils import timezone
from .models import DeveloperAccess,Customer,Order,Payment,AuditEvent
from .developer_views import business_snapshot
from .monitoring import record_request,recent_events

class PrivateDeveloperTests(TestCase):
 def setUp(self):
  cache.clear();self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
  self.override=override_settings(MONITOR_CONFIG_PATH=Path(self.folder.name)/'config.json',MONITOR_STATE_DIR=Path(self.folder.name)/'state')
  self.override.enable();self.addCleanup(self.override.disable)
  self.dev=self.actor('private-developer','owner');DeveloperAccess.objects.create(user=self.dev)
  self.owner=self.actor('ordinary-owner','owner');self.cashier=self.actor('ordinary-cashier','cashier');self.cook=self.actor('ordinary-cook','kitchen')
  self.superuser=User.objects.create_superuser('ordinary-superuser',password='Fixture-Only!2026')
 def actor(self,name,role):
  user=User.objects.create_user(name,password='Fixture-Only!2026');user.groups.add(Group.objects.get_or_create(name=role)[0]);return user
 def test_other_roles_including_superuser_cannot_read_dashboard_or_api(self):
  for user in [self.owner,self.cashier,self.cook,self.superuser]:
   self.client.force_login(user)
   for url in ['/developer/','/developer/api/status/']:
    with self.subTest(user=user.username,url=url):self.assertEqual(self.client.get(url).status_code,403)
  self.client.logout();self.assertEqual(self.client.get('/developer/').status_code,302)
 def test_developer_can_read_private_snapshot_without_secret_fields(self):
  Path(settings.MONITOR_CONFIG_PATH).write_text(json.dumps({'bot_token':'do-not-leak-token','chat_id':'12345','health_token':'do-not-leak-health'}))
  self.client.force_login(self.dev)
  response=self.client.get('/developer/api/status/')
  self.assertEqual(response.status_code,200);self.assertEqual(response['Cache-Control'],'private, no-store')
  self.assertNotIn('do-not-leak',response.content.decode());self.assertNotIn('12345',response.content.decode())
  self.assertTrue(response.json()['telegram']['configured'])
  self.assertEqual(self.client.get('/developer/').status_code,200)
 def test_private_account_hidden_from_staff_and_django_user_admin(self):
  self.client.force_login(self.owner);response=self.client.get('/admin/employees/')
  self.assertNotContains(response,self.dev.username)
  self.assertNotIn(self.dev.pk,[u.pk for u in response.context['employee_page'].object_list])
  denied=self.client.post('/admin/employees/',{'action':'toggle','employee_id':self.dev.pk,'active':'0'})
  self.assertIn(denied.status_code,[403,404]);self.dev.refresh_from_db();self.assertTrue(self.dev.is_active)
  self.client.force_login(self.superuser)
  self.assertNotContains(self.client.get('/admin/manage/auth/user/'),self.dev.username)
  self.assertIn(self.client.get(f'/admin/manage/auth/user/{self.dev.pk}/change/').status_code,[302,404])
  self.assertEqual(self.client.get(f'/admin/manage/auth/user/{self.dev.pk}/password/').status_code,404)
 def test_owner_cannot_enter_developer_login_even_with_valid_credentials(self):
  response=self.client.post('/developer/login/',{'username':self.owner.username,'password':'Fixture-Only!2026'})
  self.assertContains(response,'Не удалось войти');self.assertNotIn('_auth_user_id',self.client.session)
  good=self.client.post('/developer/login/',{'username':self.dev.username,'password':'Fixture-Only!2026'})
  self.assertRedirects(good,'/developer/')
 def test_csrf_not_exempt_and_inactive_developer_is_denied(self):
  self.assertEqual(Client(enforce_csrf_checks=True).post('/developer/login/',{'username':'a','password':'b'}).status_code,403)
  self.dev.is_active=False;self.dev.save(update_fields=['is_active'])
  self.assertContains(self.client.post('/developer/login/',{'username':self.dev.username,'password':'Fixture-Only!2026'}),'Не удалось войти')
 def test_health_requires_separate_secret_even_for_other_staff(self):
  Path(settings.MONITOR_CONFIG_PATH).write_text(json.dumps({'health_token':'fixture-health-only'}))
  self.assertEqual(self.client.get('/internal/monitor-health/').status_code,404)
  self.assertEqual(self.client.get('/internal/monitor-health/',HTTP_AUTHORIZATION='Bearer wrong').status_code,404)
  good=self.client.get('/internal/monitor-health/',HTTP_AUTHORIZATION='Bearer fixture-health-only')
  self.assertEqual(good.status_code,200);self.assertTrue(good.json()['ok'])
 def test_database_failure_is_reported_without_raw_exception(self):
  from django.db import OperationalError
  Path(settings.MONITOR_CONFIG_PATH).write_text(json.dumps({'health_token':'fixture-health-only'}))
  with patch('core.monitoring.connection.cursor',side_effect=OperationalError('secret-dsn')):
   response=self.client.get('/internal/monitor-health/',HTTP_AUTHORIZATION='Bearer fixture-health-only')
  self.assertEqual(response.status_code,503);self.assertNotContains(response,'secret-dsn',status_code=503)
 def test_developer_has_operational_access(self):
  self.client.force_login(self.dev)
  for url in ['/admin/','/admin/cashier/','/admin/kitchen/','/admin/receipts/','/admin/employees/']:
   with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
 def test_revenue_is_paid_cash_flow_with_refunds_not_unpaid_or_test_orders(self):
  c=Customer.objects.create(phone='+77000007777',consent_at=timezone.now(),is_test=False)
  for key,amount,reversed_at,is_test in [('paid',1000,None,False),('returned',200,timezone.now(),False),('synthetic',9999,None,True)]:
   order=Order.objects.create(customer=c,payment_method='cash',is_test=is_test,idempotency_key=key,total=amount)
   Payment.objects.create(order=order,amount=amount,method='cash',confirmed_by=self.cashier,idempotency_key=key,reversed_at=reversed_at)
  Order.objects.create(customer=c,payment_method='cash',is_test=False,idempotency_key='unpaid',total=5000)
  self.assertEqual(Decimal(business_snapshot()['today']['net']),Decimal('1000.00'))
 def test_private_login_is_masked_in_operational_journal(self):
  AuditEvent.objects.create(actor=self.dev,action='drinks_start')
  self.client.force_login(self.owner);response=self.client.get('/admin/audit/')
  self.assertNotContains(response,self.dev.username);self.assertContains(response,'Служебный аккаунт')
 def test_monitoring_does_not_store_query_body_token_or_phone(self):
  request=RequestFactory().post('/account/login/?secret=private-token',{'phone':'+77000009999','password':'private-password'})
  request.resolver_match=type('Match',(),{'route':'account/login/'})()
  record_request(request,500,.1);rows=recent_events()
  text=json.dumps(rows);self.assertIn('account/login/',text)
  for secret in ['private-token','private-password','77000009999']:self.assertNotIn(secret,text)

class WatchdogStateTests(TestCase):
 @classmethod
 def setUpClass(cls):
  super().setUpClass();spec=importlib.util.spec_from_file_location('private_watchdog',settings.BASE_DIR/'scripts/watch_monitor.py');cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)
 def test_failure_is_debounced_and_delivered_incident_not_repeated(self):
  f=self.module.evaluate;metrics={'cpu':1,'memory':1,'disk':1};failed={'reachable':False}
  state,events=f({}, {},failed,metrics);self.assertFalse(events)
  state,events=f({},state,failed,metrics);self.assertEqual(len(events),1)
  state['active_incidents']['application']['delivered']=True
  state,events=f({},state,failed,metrics);self.assertFalse(events)
  state,events=f({},state,{'reachable':True,'database_ok':True},metrics);self.assertEqual(events[0]['kind'],'recovery')
  state,events=f({},state,{'reachable':True,'database_ok':True},metrics);self.assertEqual(events[0]['kind'],'recovery','Undelivered recovery must be retried')
 def test_database_failures_and_resource_thresholds(self):
  state,events=self.module.evaluate({}, {},{'reachable':True,'database_ok':False},{'cpu':95,'memory':95,'disk':95})
  state,events=self.module.evaluate({},state,{'reachable':True,'database_ok':False},{'cpu':95,'memory':95,'disk':95})
  self.assertIn('database',[e['key'] for e in events]);self.assertNotIn('cpu',[e['key'] for e in events])
  state,events=self.module.evaluate({},state,{'reachable':True,'database_ok':False},{'cpu':95,'memory':95,'disk':95})
  self.assertIn('cpu',[e['key'] for e in events])
 def test_telegram_exception_never_returns_token_url(self):
  with patch.object(self.module.urllib.request,'urlopen',side_effect=RuntimeError('https://api.telegram.org/bot123:private/sendMessage')):
   ok,error=self.module.telegram({'bot_token':'123:private','chat_id':'1'},'Test')
  self.assertFalse(ok);self.assertEqual(error,'telegram_network_error');self.assertNotIn('private',error)
