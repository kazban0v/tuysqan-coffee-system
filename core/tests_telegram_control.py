import sys,json,tempfile,time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from django.conf import settings
from django.test import TestCase as DjangoTestCase,override_settings
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import telegram_control as bot
import ssh_security_monitor as ssh

class BotSecurityTests(TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.path=Path(self.folder.name)
  self.config={'owner_user_id':42,'chat_id':'42','bot_token':'123:fixture'}
 def message(self,user=42,chat=42,kind='private',text='Выручка'):
  return {'update_id':100,'message':{'date':int(time.time()),'from':{'id':user},'chat':{'id':chat,'type':kind},'text':text}}
 def test_owner_allowed_other_users_groups_forwards_rejected(self):
  self.assertEqual(bot.action_for(self.config,self.message()),'revenue')
  for item in [self.message(user=43),self.message(chat=-42,kind='group'),self.message(user=43,chat=43),self.message(text='/exec rm anything')]:self.assertIsNone(bot.action_for(self.config,item))
  item=self.message();item['message']['forward_origin']={'type':'user'};self.assertIsNone(bot.action_for(self.config,item))
 def test_callback_needs_correct_sender_private_chat_and_whitelist(self):
  item={'callback_query':{'id':'c','from':{'id':42},'data':'security','message':{'date':1,'chat':{'id':42,'type':'private'}}}}
  self.assertEqual(bot.action_for(self.config,item),'security')
  item['callback_query']['from']['id']=43;self.assertIsNone(bot.action_for(self.config,item))
  item['callback_query']['from']['id']=42;item['callback_query']['data']='exec:root';self.assertIsNone(bot.action_for(self.config,item))
 def test_old_commands_rejected_and_duplicate_updates_do_not_send(self):
  item=self.message();item['message']['date']=1;self.assertIsNone(bot.action_for(self.config,item))
  with patch.object(bot,'send_reply') as send:
   bot.process_update(self.config,self.message(),{'offset':101},self.path);send.assert_not_called()
 def test_no_external_local_api_target_or_missing_secret(self):
  with patch.object(bot.urllib.request,'urlopen') as fetch:
   self.assertIsNone(bot.local_status({'bot_status_url':'https://example.org/internal/developer-bot-status/','bot_api_token':'private'}));fetch.assert_not_called()
 def test_unauthorized_updates_do_not_fetch_finance_or_send(self):
  with patch.object(bot,'local_status') as status,patch.object(bot,'send_reply') as send:
   state=bot.process_update(self.config,self.message(user=1),{},self.path)
  status.assert_not_called();send.assert_not_called();self.assertEqual(state['offset'],101)
 def test_owner_response_succeeds_failed_delivery_retried_and_rate_limited(self):
  with patch.object(bot,'local_status',return_value={}),patch.object(bot,'send_reply',return_value=({},'')) as send:
   state=bot.process_update(self.config,self.message(),{},self.path);self.assertEqual(state['offset'],101)
   item=self.message();item['update_id']=101;state=bot.process_update(self.config,item,state,self.path);self.assertEqual(send.call_count,1)
  with patch.object(bot,'local_status',return_value={}),patch.object(bot,'send_reply',return_value=(None,'telegram_network_error')):
   state=bot.process_update(self.config,self.message(),{},self.path);self.assertNotIn('offset',state)
 def test_transport_masks_secrets_and_rejects_unknown_methods(self):
  with patch.object(bot.urllib.request,'urlopen',side_effect=RuntimeError('https://api.telegram.org/bot123:secret')):
   _,error=bot.api(self.config,'sendMessage');self.assertEqual(error,'telegram_network_error')
  self.assertEqual(bot.api(self.config,'deleteWebhook')[1],'method_not_allowed')
 def test_missing_data_not_zero_and_no_ssh_false_claim(self):
  self.assertIn('недоступно',bot.reply_text('server',None,self.path))
  self.assertIn('не подключено',bot.security_text(self.path))
  self.assertIn('недоступны',bot.reply_text('revenue',{'business':{'available':False}},self.path))

class SSHObserverTests(TestCase):
 def entry(self,message='Accepted publickey for root from 203.0.113.10 port 2222 ssh2',cursor='s=fixture'):
  return {'SYSLOG_IDENTIFIER':'sshd','MESSAGE':message,'__CURSOR':cursor,'__REALTIME_TIMESTAMP':'1794182400000000'}
 def test_root_password_key_and_ipv6_success(self):
  for method,ip in [('publickey','203.0.113.10'),('password','2001:db8::1')]:
   event=ssh.parse_entry(self.entry(f'Accepted {method} for root from {ip} port 22 ssh2'))
   self.assertEqual(event['kind'],'ssh_success');self.assertEqual(event['user'],'root');self.assertEqual(event['ip'],ip)
 def test_no_raw_log_or_injected_user_in_alert_and_no_duplicate_event(self):
  event=self.entry();state=ssh.consume(event,{});state=ssh.consume(event,state)
  self.assertEqual(len(state['pending']),1);self.assertIn('ROOT',state['pending'][0]['text']);self.assertNotIn('MESSAGE',state['pending'][0])
  self.assertIsNone(ssh.parse_entry(self.entry('Accepted password for root;id from 203.0.113.10 port 22 ssh2')))
  self.assertIsNone(ssh.parse_entry({**event,'SYSLOG_IDENTIFIER':'application'}))
 def test_failures_grouped_and_sliding_window(self):
  state={}
  for n in range(3):state=ssh.consume(self.entry('Failed password for root from 203.0.113.10 port 22 ssh2',str(n)),state,1000+n)
  self.assertEqual(len(state['pending']),1);self.assertIn('не подтверждение',state['pending'][0]['text'])
  sparse={}
  for n in range(3):sparse=ssh.consume(self.entry('Failed password for root from 203.0.113.10 port 22 ssh2',str(n)),sparse,1000+250*n)
  self.assertFalse(sparse.get('pending'))
 def test_queue_survives_delivery_failure_and_resume_uses_cursor(self):
  state=ssh.consume(self.entry(),{})
  with patch.object(ssh,'api',return_value=(None,'telegram_network_error')):state=ssh.flush({},state)
  self.assertEqual(len(state['pending']),1);self.assertIn('--after-cursor=s=fixture',ssh.journal_command(state))
  with patch.object(ssh,'api',return_value=({},'')):state=ssh.flush({},state)
  self.assertFalse(state['pending'])
 def test_queue_cap_does_not_advance_cursor(self):
  state={'pending':[{}]*200,'cursor':'previous'}
  with self.assertRaises(RuntimeError):ssh.consume(self.entry(),state)
  self.assertEqual(state['cursor'],'previous')

class InternalBotAPITests(DjangoTestCase):
 def test_bot_secret_separate_from_health_and_data_never_exposes_secret(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'config.json';path.write_text(json.dumps({'bot_api_token':'bot-only-fixture','health_token':'health-only-fixture','bot_token':'123:private','chat_id':'42'}))
   with override_settings(MONITOR_CONFIG_PATH=path,MONITOR_STATE_DIR=Path(folder)/'state'):
    self.assertEqual(self.client.get('/internal/developer-bot-status/').status_code,404)
    self.assertEqual(self.client.get('/internal/developer-bot-status/',HTTP_AUTHORIZATION='Bearer health-only-fixture').status_code,404)
    response=self.client.get('/internal/developer-bot-status/',HTTP_AUTHORIZATION='Bearer bot-only-fixture')
    self.assertEqual(response.status_code,200);self.assertEqual(response['Cache-Control'],'private, no-store')
    for value in ['bot-only-fixture','health-only-fixture','123:private']:self.assertNotContains(response,value)
