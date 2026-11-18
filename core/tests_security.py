"""Independent negative-path regression tests for the local prototype."""
import uuid
from .test_helpers import authenticate_phone
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User, Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from .models import *
from .services import *

class SecurityServiceTests(TestCase):
    def setUp(self):
        self.cashier=self.user('cashier'); self.kitchen=self.user('kitchen'); self.owner=self.user('owner')
        self.customer=Customer.objects.create(name='Synthetic guest',phone='+70000000001',phone_verified_at=timezone.now(),consent_at=timezone.now())
        self.table=Table.objects.create(name='TEST 1',is_test=True)
        category=MenuCategory.objects.create(slug='test',name_ru='Тест',name_kz='Тест')
        self.food=MenuItem.objects.create(category=category,slug='food',name_ru='TEST FOOD',name_kz='TEST FOOD',kind='food',price=100)
        self.drink=MenuItem.objects.create(category=category,slug='drink',name_ru='TEST DRINK',name_kz='TEST DRINK',kind='drink',price=50,is_test=True)
    def user(self,role):
        user=User.objects.create_user(role,password='test-password-only'); user.groups.add(Group.objects.get_or_create(name=role)[0]); return user
    def payload(self,**kwargs):
        data={'idempotency_key':str(uuid.uuid4()),'table_token':self.table.token(),'payment_method':'kaspi','items':[{'id':self.food.pk,'quantity':2}]};data.update(kwargs);return data
    def order(self,**kwargs): return create_order(self.customer,self.payload(**kwargs))[0]
    def accept(self,order): return act_on_order(order.public_id,self.cashier,'accept',{'eta':20})
    def test_table_signature_and_inactive_table(self):
        with self.assertRaises(ValidationError): resolve_table(self.table.token()+'tamper')
        self.table.active=False;self.table.save()
        with self.assertRaises(ValidationError): resolve_table(self.table.token())
    def test_order_replay_is_idempotent_and_changed_replay_rejected(self):
        data=self.payload(); a,created=create_order(self.customer,data); b,created_again=create_order(self.customer,data)
        self.assertTrue(created); self.assertFalse(created_again);self.assertEqual(a.pk,b.pk);self.assertEqual(OutboxMessage.objects.count(),1)
        data['items'][0]['quantity']=3
        with self.assertRaises(ValidationError):create_order(self.customer,data)
    def test_client_prices_type_paid_and_test_flags_not_trusted(self):
        data=self.payload(total=1,is_test=False,payment_status='paid');data['items'][0].update(price=1,kind='drink')
        order=create_order(self.customer,data)[0]
        self.assertEqual(order.total,Decimal('200'));self.assertEqual(order.payment_status,'unpaid');self.assertTrue(order.is_test);self.assertEqual(order.items.get().kind,'food')
    def test_mixed_requires_preference_and_solo_discards_it(self):
        mixed=[{'id':self.food.pk,'quantity':1},{'id':self.drink.pk,'quantity':1}]
        with self.assertRaises(ValidationError):self.order(items=mixed)
        self.assertEqual(self.order(items=mixed,drink_preference='with_food').drink_preference,'with_food')
        self.assertEqual(self.order(drink_preference='with_food').drink_preference,'')
    def test_payment_is_separate_idempotent_and_excludes_test_loyalty(self):
        order=self.accept(self.order());order=confirm_payment(order,self.cashier,200,key='payment-test-once')
        self.assertEqual(order.status,'accepted');confirm_payment(order,self.cashier,200,key='payment-test-once')
        self.assertEqual(Payment.objects.count(),1);self.assertEqual(LoyaltyEntry.objects.count(),0)
        with self.assertRaises(ValidationError):confirm_payment(order,self.cashier,201,key='payment-test-twice')
    def test_mismatched_payment_requires_reason_and_refund_requires_owner(self):
        order=self.accept(self.order())
        with self.assertRaises(ValidationError):confirm_payment(order,self.cashier,180)
        order=confirm_payment(order,self.cashier,180,reason='Synthetic correction')
        with self.assertRaises(PermissionDenied):reverse_payment(order,self.cashier,'Synthetic refund')
        order=reverse_payment(order,self.owner,'Synthetic refund');self.assertEqual(order.payment_status,'refunded');self.assertEqual(Payment.objects.count(),1)
    def test_kitchen_cannot_pay_cancel_accept_or_access_drink_item(self):
        order=self.accept(self.order(items=[{'id':self.food.pk,'quantity':1},{'id':self.drink.pk,'quantity':1}],drink_preference='immediately'))
        for action in ['pay','accept','cancel','correct','drinks_ready','serve']:
            with self.subTest(action=action), self.assertRaises(PermissionDenied):act_on_order(order.public_id,self.kitchen,action,{'eta':5,'amount':150,'reason':'test'})
        with self.assertRaises(PermissionDenied):act_on_order(order.public_id,self.kitchen,'item_ready',{'item_id':order.drink_items.get().pk})
        act_on_order(order.public_id,self.kitchen,'item_ready',{'item_id':order.food_items.get().pk});order.refresh_from_db()
        self.assertEqual(order.food_items.get().status,'ready');self.assertEqual(order.drink_items.get().status,'pending');self.assertNotEqual(order.status,'ready')
    def test_payment_release_gates_kitchen(self):
        settings=AppSettings.get();settings.kitchen_release='payment';settings.save();order=self.accept(self.order())
        self.assertFalse(kitchen_queue().filter(pk=order.pk).exists())
        with self.assertRaises(PermissionDenied):act_on_order(order.public_id,self.kitchen,'ready')
        confirm_payment(order,self.cashier,200);self.assertTrue(kitchen_queue().filter(pk=order.pk).exists())
    def test_eta_expiry_never_makes_ready_and_notifies_once(self):
        order=self.accept(self.order());order.eta_at=timezone.now()-timedelta(minutes=1);order.save()
        mark_delays();mark_delays();order.refresh_from_db()
        self.assertTrue(order.is_delayed);self.assertEqual(order.status,'accepted');self.assertEqual(order.notifications.filter(kind='delayed').count(),1)
    def test_corrections_require_reason_and_paid_orders_cannot_be_corrected(self):
        order=self.accept(self.order())
        with self.assertRaises(ValidationError):act_on_order(order.public_id,self.cashier,'correct',{'items':[{'id':self.food.pk,'quantity':1}]})
        order=confirm_payment(order,self.cashier,200)
        with self.assertRaises(ValidationError):act_on_order(order.public_id,self.cashier,'correct',{'reason':'test','items':[{'id':self.food.pk,'quantity':1}]})
    def test_otp_bound_to_session_one_use_and_attempt_limited(self):
        code=request_otp('session-a','+70000000002','Synthetic OTP',True)
        with self.assertRaises(ValidationError):verify_otp('session-b','+70000000002',code)
        for _ in range(5):
            with self.assertRaises(ValidationError):verify_otp('session-a','+70000000002','wrong')
        with self.assertRaises(ValidationError):verify_otp('session-a','+70000000002',code)
        self.assertEqual(OTPChallenge.objects.get(phone='+70000000002').attempts,5)
    def test_otp_resend_expiry_and_replay(self):
        code=request_otp('session-a','+70000000003','Synthetic OTP',True)
        with self.assertRaises(ValidationError):request_otp('session-a','+70000000003','Synthetic OTP',True)
        customer=verify_otp('session-a','+70000000003',code);self.assertTrue(customer.phone_verified_at)
        with self.assertRaises(ValidationError):verify_otp('session-a','+70000000003',code)
        code=request_otp('session-a','+70000000004','Synthetic OTP',True)
        OTPChallenge.objects.filter(phone='+70000000004').update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):verify_otp('session-a','+70000000004',code)
    def test_pending_loyalty_policy_has_no_active_discount(self):
        policy=LoyaltyPolicy.get();self.assertFalse(policy.confirmed);self.assertEqual(self.customer.discount_percent,0)
    def test_invalid_quantity_and_unavailable_item_rejected(self):
        for qty in [0,-1,100,True,'1.5']:
            with self.subTest(qty=qty), self.assertRaises(ValidationError):self.order(items=[{'id':self.food.pk,'quantity':qty}])
        self.food.available=False;self.food.save()
        with self.assertRaises(ValidationError):self.order()

class SecurityEndpointTests(SecurityServiceTests):
    def setUp(self):
        super().setUp();self.table.is_test=False;self.table.save()
    def customer_client(self,customer=None):
        from django.test import Client
        client=Client();session=client.session;session['customer_id']=(customer or self.customer).pk;session['table_token']=self.table.token();session.save();return client
    def test_customer_cannot_read_or_review_another_order(self):
        order=self.order();other=Customer.objects.create(name='Other synthetic',phone='+70000000005',phone_verified_at=timezone.now(),consent_at=timezone.now())
        client=self.customer_client(other)
        self.assertEqual(client.get(f'/api/orders/{order.public_id}/').status_code,404)
        self.assertEqual(client.post(f'/api/orders/{order.public_id}/review/',data='{"rating":5}',content_type='application/json').status_code,404)
    def test_review_requires_served_and_replay_does_not_duplicate(self):
        order=self.order();client=self.customer_client();url=f'/api/orders/{order.public_id}/review/'
        self.assertEqual(client.post(url,data='{"rating":5}',content_type='application/json').status_code,400)
        order=self.accept(order);act_on_order(order.public_id,self.kitchen,'item_ready',{'item_id':order.food_items.get().pk});act_on_order(order.public_id,self.cashier,'ready');act_on_order(order.public_id,self.cashier,'serve')
        for _ in range(2):self.assertEqual(client.post(url,data='{"rating":5,"comment":"Synthetic review"}',content_type='application/json').status_code,200)
        self.assertEqual(Review.objects.count(),1)
    def test_rbac_and_kitchen_payload_redaction(self):
        self.customer.is_test=False;self.customer.save();self.drink.is_test=False;self.drink.save()
        order=self.accept(self.order(items=[{'id':self.food.pk,'quantity':1},{'id':self.drink.pk,'quantity':1}],drink_preference='with_food'))
        self.client.force_login(self.kitchen)
        for url in ['/api/staff/orders/','/staff/customers/','/staff/settings/','/staff/','/staff/telegram/']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,403)
        data=self.client.get('/api/kitchen/').json()['orders'][0]
        self.assertNotIn('customer',data);self.assertNotIn('payment_status',data);self.assertNotIn('total',data);self.assertNotIn(self.customer.phone,str(data))
        self.assertEqual(len(data['items']),1);self.assertEqual(data['items'][0]['kind'],'food')
        self.client.force_login(self.cashier)
        for url in ['/staff/customers/','/staff/settings/','/staff/','/staff/audit/']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,403)
    def test_csrf_required_for_mutations(self):
        from django.test import Client
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.cashier)
        order=self.order()
        self.assertEqual(strict.post(f'/api/staff/orders/{order.public_id}/action/',data='{"action":"accept","eta":10}',content_type='application/json').status_code,403)
        self.assertEqual(strict.post('/api/orders/',data='{}',content_type='application/json').status_code,403)
    def test_server_session_qr_context_cannot_be_swapped_by_body(self):
        client=self.customer_client();data=self.payload();other=Table.objects.create(name='Other test table');data['table_token']=other.token()
        import json
        response=client.post('/api/orders/',data=json.dumps(data),content_type='application/json')
        self.assertEqual(response.status_code,400);self.assertEqual(Order.objects.count(),0)
    def test_payment_release_cannot_be_bypassed_by_cashier_ready(self):
        settings=AppSettings.get();settings.kitchen_release='payment';settings.save();order=self.accept(self.order())
        with self.assertRaises(ValidationError):act_on_order(order.public_id,self.cashier,'ready')
        order.refresh_from_db();self.assertNotEqual(order.status,'ready')
    def test_bad_qr_and_bad_report_dates_are_validation_errors(self):
        self.assertEqual(self.client.get('/?table=tampered').status_code,400)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/staff/?start=not-a-date').status_code,400)

    def test_verified_phone_checkout_session_ownership_and_disabled_delivery(self):
        import json
        from django.test import Client
        guest=Client()
        self.assertEqual(guest.get('/checkout/').status_code,403)
        self.assertEqual(guest.get('/table/'+self.table.token()+'/').status_code,200)
        payload=self.payload()
        denied=guest.post('/api/orders/',data=json.dumps(payload),content_type='application/json')
        self.assertEqual(denied.status_code,401)
        self.assertEqual(denied.json()['redirect'],'/account/login/')
        disabled=guest.post('/api/otp/request/',data=json.dumps({'phone':'+70000000901'}),content_type='application/json')
        self.assertEqual(disabled.status_code,503)
        authenticate_phone(guest,phone='+70000000902')
        response=guest.post('/api/orders/',data=json.dumps(payload),content_type='application/json')
        self.assertEqual(response.status_code,201,response.content)
        ident=response.json()['order']['public_id']
        order=Order.objects.get(public_id=ident)
        self.assertIsNotNone(order.customer.phone_verified_at)
        self.assertEqual(order.customer.phone,'+70000000902')
        self.assertFalse(order.is_test)
        self.assertEqual(guest.get(f'/api/orders/{ident}/').status_code,200)
        stranger=Client()
        self.assertIn(stranger.get(f'/api/orders/{ident}/').status_code,[403,404])
        self.assertIn(stranger.post(f'/api/orders/{ident}/review/',data='{"rating":5}',content_type='application/json').status_code,[403,404])
        replay=guest.post('/api/orders/',data=json.dumps(payload),content_type='application/json')
        self.assertEqual(replay.status_code,200)
        self.assertEqual(replay.json()['order']['public_id'],ident)
    def test_anonymous_guest_cannot_access_staff_admin_aliases(self):
        for url in ['/admin/','/admin/cashier/','/admin/kitchen/']:
            response=self.client.get(url)
            self.assertEqual(response.status_code,302)
            self.assertIn('login',response['Location'])
        self.client.force_login(self.kitchen)
        self.assertEqual(self.client.get('/admin/cashier/').status_code,403)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get('/admin/kitchen/').status_code,403)

class GuestStaffEndToEndTests(TestCase):
    def setUp(self):
        SecurityServiceTests.setUp(self);self.table.is_test=False;self.table.save();self.drink.is_test=False;self.drink.save()
    user=SecurityServiceTests.user
    payload=SecurityServiceTests.payload
    def test_guest_order_through_cashier_kitchen_payment_and_handover(self):
        import json
        from django.test import Client
        guest=Client();self.assertEqual(guest.get('/table/'+self.table.token()+'/').status_code,200)
        authenticate_phone(guest)
        payload=self.payload(items=[{'id':self.food.pk,'quantity':2,'comment':'No salt'},{'id':self.drink.pk,'quantity':1}],drink_preference='with_food',total='0.01')
        response=guest.post('/api/orders/',data=json.dumps(payload),content_type='application/json');self.assertEqual(response.status_code,201,response.content)
        public_id=response.json()['order']['public_id'];self.assertEqual(response.json()['order']['total'],'250.00')
        order=Order.objects.get(public_id=public_id);self.assertEqual(order.payment_status,'unpaid')
        notification=OutboxMessage.objects.get(order=order);self.assertEqual(notification.payload['drink_preference'],'with_food')
        staff=Client();staff.force_login(self.cashier)
        endpoint=f'/api/staff/orders/{public_id}/action/'
        def action(client,action,**kwargs):
            result=client.post(endpoint,data=json.dumps({'action':action,**kwargs}),content_type='application/json');self.assertEqual(result.status_code,200,result.content);return result.json()['order']
        accepted=action(staff,'accept',eta=15);self.assertEqual(accepted['eta_minutes'],15)
        kitchen=Client();kitchen.force_login(self.kitchen)
        queue=kitchen.get('/api/kitchen/').json()['orders'];self.assertEqual(len(queue),1)
        self.assertEqual(len(queue[0]['items']),1);self.assertEqual(queue[0]['items'][0]['comment'],'No salt')
        self.assertNotIn('customer',queue[0]);self.assertNotIn('payment_method',queue[0])
        action(kitchen,'food_eta',eta=20);action(kitchen,'item_ready',item_id=queue[0]['items'][0]['id'])
        own=guest.get(f'/api/orders/{public_id}/').json()['order'];self.assertEqual(own['status'],'preparing')
        ready=action(staff,'drinks_ready');self.assertEqual(ready['status'],'preparing');ready=action(staff,'ready');self.assertEqual(ready['status'],'ready');self.assertEqual(ready['payment_status'],'unpaid')
        paid=action(staff,'pay',amount='250.00',idempotency_key='e2e-payment');self.assertEqual(paid['payment_status'],'paid');self.assertEqual(paid['status'],'ready')
        action(staff,'pay',amount='250.00',idempotency_key='e2e-payment');self.assertEqual(Payment.objects.filter(order=order).count(),1)
        served=action(staff,'serve');self.assertEqual(served['status'],'served')
        self.assertEqual(guest.post(f'/api/orders/{public_id}/review/',data='{"rating":5,"comment":"Synthetic test"}',content_type='application/json').status_code,200)
        self.assertEqual(LoyaltyEntry.objects.count(),0)

class OperationalClassificationTests(TestCase):
    setUp=SecurityServiceTests.setUp
    user=SecurityServiceTests.user
    payload=SecurityServiceTests.payload
    order=SecurityServiceTests.order
    accept=SecurityServiceTests.accept
    def test_operational_and_synthetic_flags_come_from_server_records(self):
        self.customer.is_test=False;self.customer.save();self.table.is_test=False;self.table.save()
        normal=self.order(is_test=True);self.assertFalse(normal.is_test)
        for target in [self.customer,self.table,self.food]:
            target.is_test=True;target.save()
            order=self.order(is_test=False);self.assertTrue(order.is_test)
            target.is_test=False;target.save()
    def test_legacy_test_orders_excluded_from_operational_queues_and_finance(self):
        operational_customer=self.customer;operational_customer.is_test=False;operational_customer.save();self.table.is_test=False;self.table.save()
        operational=self.accept(self.order());self.food.is_test=True;self.food.save();synthetic=self.accept(self.order());self.food.is_test=False;self.food.save()
        confirm_payment(operational,self.cashier,200);confirm_payment(synthetic,self.cashier,200)
        self.client.force_login(self.cashier)
        queue=self.client.get('/api/staff/orders/').json()['orders'];self.assertEqual([x['public_id'] for x in queue],[str(operational.public_id)])
        self.client.force_login(self.kitchen)
        kitchen=self.client.get('/api/kitchen/').json()['orders'];self.assertEqual([x['public_id'] for x in kitchen],[str(operational.public_id)])
        from django.test import RequestFactory
        from .views import analytics
        totals=analytics(RequestFactory().get('/staff/'))
        self.assertEqual(Decimal(totals['confirmed_payments']),Decimal('200'))
        self.assertEqual(Order.objects.count(),2);self.assertEqual(Payment.objects.count(),2)
        self.assertFalse(LoyaltyPolicy.get().confirmed);self.assertEqual(LoyaltyEntry.objects.count(),0)
