from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
from django.test import TestCase,Client
from django.contrib.auth.models import User,Group
from django.utils import timezone
from .models import *


class AdminPortalTests(TestCase):
 @classmethod
 def setUpTestData(cls):
  cls.users={}
  for role in ['owner','manager','cashier','kitchen']:
   user=User.objects.create_user('portal-'+role);user.groups.add(Group.objects.create(name=role));cls.users[role]=user
  cls.customer=Customer.objects.create(name='Гость',phone='+77000000234',consent_at=timezone.now(),is_test=False)
  cls.table=Table.objects.create(name='Стол 8',is_test=False)
  cls.category=MenuCategory.objects.create(slug='portal',name_ru='Завтраки',name_kz='Таңғы ас')
  cls.food=MenuItem.objects.create(slug='portal-food',category=cls.category,name_ru='Овсянка',name_kz='Сұлы ботқасы',kind='food',price=100)
  policy=LoyaltyPolicy.get();policy.confirmed=True;policy.save()
 def setUp(self):self.client.force_login(self.users['owner'])
 def test_menu_counts_default_active_and_archive_filters(self):
  MenuItem.objects.create(slug='stopped-item',category=self.category,name_ru='Скрытая',price=100,available=False)
  MenuItem.objects.create(slug='test-item',category=self.category,name_ru='Тест',price=100,is_test=True)
  for suffix,expected in [('',1),('?availability=',2),('?availability=stopped',1),('?q=НетТакого',0)]:
   response=self.client.get('/admin/menu/'+suffix)
   self.assertEqual(response.status_code,200)
   self.assertEqual(response.context['menu_counts'],{'total':2,'active':1,'inactive':1})
   self.assertEqual(response.context['item_page'].paginator.count,expected)
  response=self.client.get('/admin/menu/')
  self.assertEqual(response.context['filters']['availability'],'available')
  self.assertEqual([i.pk for i in response.context['item_page']],[self.food.pk])
  self.assertContains(response,'data-menu-counts')
 def order(self,status='accepted',paid=False,amount=100):
  order=Order.objects.create(customer=self.customer,table=self.table,is_test=False,status=status,source='web',idempotency_key=str(uuid4()),payload_hash='portal',subtotal=amount,total=amount,payment_method='cash',payment_status='paid' if paid else 'unpaid',actual_paid=amount if paid else 0,paid_at=timezone.now() if paid else None)
  OrderItem.objects.create(order=order,menu_item=self.food,name_ru=self.food.name_ru,name_kz=self.food.name_kz,kind='food',quantity=1,unit_price=amount)
  if paid:Payment.objects.create(order=order,amount=amount,method='cash',confirmed_by=self.users['cashier'],idempotency_key=str(uuid4()))
  return order
 def test_all_sections_render_real_data(self):
  order=self.order(paid=True);order.guest_wish='Без сахара';order.guest_wish_at=timezone.now();order.save()
  Review.objects.create(order=order,customer=self.customer,rating=5,comment='Спасибо')
  for url in ['/admin/','/admin/orders/',f'/admin/orders/{order.public_id}/','/admin/analytics/','/admin/audit/','/admin/attention/','/admin/menu/','/admin/settings/','/admin/clients/',f'/admin/clients/{self.customer.pk}/','/admin/feedback/','/admin/employees/']:
   response=self.client.get(url);self.assertEqual(response.status_code,200,(url,response.content[:300]));self.assertContains(response,'admin-portal')
 def test_role_boundaries(self):
  urls=['/admin/orders/','/admin/clients/','/admin/employees/','/admin/menu/','/admin/settings/','/admin/audit/','/admin/analytics/','/admin/feedback/','/admin/attention/']
  for role in ['cashier','kitchen']:
   self.client.force_login(self.users[role])
   for url in urls:self.assertEqual(self.client.get(url).status_code,403,(role,url))
  self.client.force_login(self.users['manager'])
  for url in ['/admin/clients/','/admin/employees/','/admin/menu/','/admin/settings/','/admin/audit/']:self.assertEqual(self.client.get(url).status_code,403,url)
  self.client.logout();self.assertEqual(self.client.get('/admin/').status_code,302)
 def test_financial_totals_use_confirmations_and_refund_date(self):
  self.order(paid=True,amount=200);refunded=self.order(paid=True,amount=100);self.order(amount=9000)
  payment=refunded.payments.get();payment.reversed_at=timezone.now();payment.save();refunded.payment_status='refunded';refunded.actual_paid=0;refunded.save()
  stats=self.client.get('/admin/analytics/').context['stats']
  self.assertEqual(stats['gross'],300);self.assertEqual(stats['refunds'],100);self.assertEqual(stats['net'],200)
 def test_attention_ignores_ready_food_and_refunded_orders(self):
  pending=self.order('new');Order.objects.filter(pk=pending.pk).update(created_at=timezone.now()-timedelta(minutes=9))
  delayed=self.order();delayed.food_eta_at=timezone.now()-timedelta(minutes=2);delayed.save()
  done=self.order();done.food_eta_at=timezone.now()-timedelta(minutes=2);done.save();done.items.update(status='ready')
  self.order('served');refund=self.order('served');refund.payment_status='refunded';refund.save()
  groups=self.client.get('/admin/attention/').context['groups'];self.assertEqual({x['key']:x['count'] for x in groups},{'waiting':1,'delayed':1,'unpaid':1})
 def menu_payload(self,**extra):return {'action':'save','item_id':self.food.pk,'name_ru':'Овсянка новая','name_kz':'Сұлы ботқасы','category':self.category.pk,'kind':'food','price':'125.50','available':'on',**extra}
 def test_menu_price_and_stop_list_audited_without_repricing_history(self):
  order=self.order();response=self.client.post('/admin/menu/',self.menu_payload());self.assertEqual(response.status_code,302)
  self.food.refresh_from_db();self.assertEqual(self.food.price,Decimal('125.50'));self.assertEqual(order.items.get().unit_price,100)
  event=AuditEvent.objects.get(action='menu_item_updated');self.assertEqual(event.actor,self.users['owner']);self.assertEqual(event.before['price'],'100.00');self.assertEqual(event.after['price'],'125.50')
  self.assertEqual(self.client.post('/admin/menu/',{'action':'toggle','item_id':self.food.pk}).status_code,302);self.food.refresh_from_db();self.assertFalse(self.food.available)
 def test_invalid_price_ids_dates_do_not_mutate_or_crash(self):
  response=self.client.post('/admin/menu/',self.menu_payload(price='-10'));self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
  self.food.refresh_from_db();self.assertEqual(self.food.price,100)
  self.assertEqual(self.client.post('/admin/menu/',{'action':'toggle','item_id':'bad'}).status_code,404)
  self.assertEqual(self.client.post('/admin/settings/',{'action':'table','table_id':'bad'}).status_code,404)
  self.assertEqual(self.client.get('/admin/analytics/?start=bad').status_code,400)
 def test_client_totals_ledger_refunds_and_search(self):
  paid=self.order(paid=True,amount=50000);self.order(amount=80000)
  LoyaltyEntry.objects.create(customer=self.customer,order=paid,payment=paid.payments.get(),amount=50000,kind='purchase')
  response=self.client.get('/admin/clients/?q=8%20700%20000%2002%2034');row=list(response.context['clients_page'])[0]
  self.assertEqual(row.purchase_total,50000);self.assertEqual(row.purchase_count,1);self.assertEqual(row.current_discount,5);self.assertEqual(row.remaining,50000)
 def test_feedback_status_tracks_actor_for_review_and_wish(self):
  order=self.order();order.guest_wish='Без сахара';order.guest_wish_at=timezone.now();order.save();review=Review.objects.create(order=order,customer=self.customer,rating=4,comment='Хорошо')
  for kind in ['review','wish']:
   response=self.client.post('/admin/feedback/',{'order_id':order.pk,'kind':kind,'status':'handled','note':'Позвонили гостю'})
   self.assertEqual(response.status_code,302)
   record=FeedbackHandling.objects.get(order=order,kind=kind);self.assertEqual(record.handled_by,self.users['owner']);self.assertIsNotNone(record.handled_at)
  review.refresh_from_db();self.assertEqual(review.status,'handled')
  self.assertContains(self.client.get('/admin/feedback/?status=handled'),'portal-owner')
  self.assertEqual(self.client.post('/admin/feedback/',{'order_id':order.pk,'kind':'wish','status':'bad'}).status_code,400)
 def test_csrf_applies_to_admin_changes(self):
  client=Client(enforce_csrf_checks=True);client.force_login(self.users['owner'])
  self.assertEqual(client.post('/admin/menu/',self.menu_payload()).status_code,403)
 def test_photo_upload_is_separate_webp_and_invalid_image_rejected(self):
  from io import BytesIO
  from pathlib import Path
  from tempfile import TemporaryDirectory
  from django.core.files.uploadedfile import SimpleUploadedFile
  from django.test import override_settings
  from PIL import Image
  self.food.image='menu/original.jpg';self.food.save(update_fields=['image'])
  image=BytesIO();Image.new('RGB',(24,16),'white').save(image,'PNG')
  with TemporaryDirectory() as directory,override_settings(BASE_DIR=Path(directory),MENU_UPLOAD_DIR=Path(directory)/'static/uploads/menu'):
   response=self.client.post('/admin/menu/',self.menu_payload(photo=SimpleUploadedFile('new.png',image.getvalue(),content_type='image/png')))
   self.assertEqual(response.status_code,302);self.food.refresh_from_db();self.assertTrue(self.food.image.startswith('uploads/menu/'))
   output=Path(directory)/'static'/self.food.image;self.assertTrue(output.exists());self.assertEqual(Image.open(output).format,'WEBP')
   saved=self.food.image
   response=self.client.post('/admin/menu/',self.menu_payload(photo=SimpleUploadedFile('fake.png',b'<script>bad</script>',content_type='image/png')))
   self.assertEqual(response.status_code,200);self.assertIn('photo',response.context['form'].errors);self.food.refresh_from_db();self.assertEqual(self.food.image,saved)
 def test_orders_paginate_and_filter_without_exposing_test_orders(self):
  for _ in range(27):self.order()
  excluded=self.order();excluded.is_test=True;excluded.save()
  first=self.client.get('/admin/orders/').context['order_page'];self.assertEqual(first.paginator.count,27);self.assertEqual(len(first),25)
  self.assertEqual(len(self.client.get('/admin/orders/?page=2').context['order_page']),2)
  result=self.client.get('/admin/orders/',{'q':f'T{first.object_list[0].pk:04d}'}).context['order_page'];self.assertEqual(result.paginator.count,1)
 def test_settings_reject_descending_tiers_without_mutating_policy(self):
  policy=LoyaltyPolicy.get();before=policy.tiers;payload={'action':'policy','confirmed':'on'}
  for n,tier in enumerate(before,1):payload['threshold_'+str(n)]=tier['threshold'];payload['percent_'+str(n)]=tier['percent']
  payload['threshold_2']=1
  response=self.client.post('/admin/settings/',payload);self.assertTrue(response.context['policy_form'].errors);policy.refresh_from_db();self.assertEqual(policy.tiers,before)
 def test_table_and_loyalty_settings_audited(self):
  self.assertEqual(self.client.post('/admin/settings/',{'action':'table','table_id':self.table.pk,'name':'Стол 8 новый','active':'on'}).status_code,302)
  self.assertTrue(AuditEvent.objects.filter(action='table_updated').exists())
  policy=LoyaltyPolicy.get();payload={'action':'policy','confirmed':'on'}
  for n,tier in enumerate(policy.tiers,1):payload['threshold_'+str(n)]=tier['threshold'];payload['percent_'+str(n)]=tier['percent']
  self.assertEqual(self.client.post('/admin/settings/',payload).status_code,302)
  self.assertTrue(AuditEvent.objects.filter(action='loyalty_policy_updated').exists())

 def test_audit_displays_payment_diff_without_raw_snapshots(self):
  order=self.order()
  event=AuditEvent.objects.create(action='payment_confirmed',actor=self.users['cashier'],order=order,before={'payment_status':'unpaid','actual_paid':'0.00','total':'100.00'},after={'payment_status':'paid','actual_paid':'100.00','total':'100.00','payment_id':99})
  response=self.client.get('/admin/audit/')
  self.assertContains(response,'ap-audit-change')
  self.assertContains(response,'Не оплачен')
  self.assertContains(response,'Оплачен')
  self.assertNotContains(response,'payment_status')
  self.assertNotContains(response,'payment_id')
  self.assertNotContains(response,'ap-audit-json')
  event.refresh_from_db()
  self.assertEqual(event.after['payment_id'],99)
