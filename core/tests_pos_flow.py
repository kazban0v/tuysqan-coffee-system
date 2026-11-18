"""Cashier-only POS regressions. Every fixture lives in Django's test database."""
import copy
import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.utils import timezone

from .models import (
    AuditEvent, Customer, LoyaltyEntry, LoyaltyPolicy, MenuCategory, MenuItem,
    Order, OutboxMessage, Payment, Table,
)


class POSFlowTests(TestCase):
    def setUp(self):
        self.cashier = self.make_user('cashier')
        self.manager = self.make_user('manager')
        self.owner = self.make_user('owner')
        self.kitchen = self.make_user('kitchen')
        self.table = Table.objects.create(name='Стол 8', active=True, is_test=False)
        category = MenuCategory.objects.create(slug='pos-regression', name_ru='Меню', name_kz='Мәзір')
        self.food = MenuItem.objects.create(
            category=category, slug='pos-food', name_ru='Сохранённое блюдо',
            name_kz='Тағам', price=Decimal('1000.50'), kind='food', is_test=False,
        )
        self.drink = MenuItem.objects.create(
            category=category, slug='pos-drink', name_ru='Сохранённый напиток',
            name_kz='Сусын', price=Decimal('490.25'), kind='drink', is_test=False,
        )
        self.client.force_login(self.cashier)

    def make_user(self, role):
        user = User.objects.create_user('pos-' + role)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def payload(self, **changes):
        value = {
            'items': [{'id': self.food.pk, 'quantity': 2}, {'id': self.drink.pk, 'quantity': 1}],
            'fulfillment': 'dine_in', 'table_token': self.table.token(),
            'payment_method': 'cash', 'drink_preference': 'with_food',
            'comment': 'POS regression only', 'idempotency_key': str(uuid.uuid4()),
            'accept_order': True, 'eta': 15,
        }
        value.update(changes)
        return value

    def post(self, path, payload, client=None):
        return (client or self.client).post(path, json.dumps(payload), content_type='application/json')

    def create(self, payload=None):
        response = self.post('/api/staff/pos/', payload or self.payload())
        self.assertEqual(response.status_code, 201, response.content)
        return Order.objects.get(public_id=response.json()['order']['public_id']), response

    def test_cashier_can_create_without_qr_customer_session_and_server_prices_win(self):
        payload = self.payload(total='0.01', discount_percent=99, payment_status='paid', status='served')
        payload['items'][0].update(price='0.01', unit_price='0.01', kind='drink')
        order, response = self.create(payload)
        self.assertEqual(order.source, 'pos')
        self.assertEqual(order.table, self.table)
        self.assertEqual(order.status, 'accepted')
        self.assertEqual(order.payment_status, 'unpaid')
        self.assertEqual(order.total, Decimal('2491.25'))
        self.assertFalse(order.is_test)
        self.assertFalse(order.customer_identity_verified)
        self.assertEqual(order.discount_percent, 0)
        self.assertEqual(order.items.get(menu_item=self.food).unit_price, self.food.price)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(LoyaltyEntry.objects.count(), 0)
        self.assertEqual(response.json()['print_url'], f'/admin/orders/{order.public_id}/print/')
        self.assertNotIn('customer_id', self.client.session)
        self.assertNotIn('table_token', self.client.session)

    def test_takeaway_requires_no_table_but_web_customer_still_needs_qr(self):
        order, response = self.create(self.payload(fulfillment='takeaway', table_token=''))
        self.assertIsNone(order.table)
        self.assertEqual(response.json()['order']['fulfillment'], 'takeaway')
        anonymous = Client()
        rejected = self.post('/api/orders/', self.payload(fulfillment='takeaway', table_token=''), anonymous)
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(Order.objects.count(), 1)

    def test_bad_eta_rolls_back_profile_order_audit_and_outbox(self):
        payload = self.payload(eta=0, customer={'phone': '+77770000901', 'name': 'POS Guest', 'consent': True})
        response = self.post('/api/staff/pos/', payload)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertEqual(OutboxMessage.objects.count(), 0)
        self.assertFalse(Customer.objects.filter(phone='+77770000901').exists())

    def test_replay_is_idempotent_but_changed_customer_mode_and_acceptance_rejected(self):
        payload = self.payload()
        order, _ = self.create(payload)
        replay = self.post('/api/staff/pos/', payload)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertFalse(replay.json()['created'])
        self.assertEqual(replay.json()['order']['public_id'], str(order.public_id))
        events, notifications = AuditEvent.objects.count(), OutboxMessage.objects.count()
        changed_values = [
            {'customer': {'phone': '+77770000902', 'name': 'Different guest', 'consent': True}},
            {'fulfillment': 'takeaway', 'table_token': ''},
            {'eta': 20}, {'accept_order': False},
        ]
        for values in changed_values:
            changed = copy.deepcopy(payload)
            changed.update(values)
            with self.subTest(values=values):
                self.assertEqual(self.post('/api/staff/pos/', changed).status_code, 400)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), events)
        self.assertEqual(OutboxMessage.objects.count(), notifications)
        self.assertFalse(Customer.objects.filter(phone='+77770000902').exists())

    def test_existing_verified_phone_does_not_verify_pos_claim_or_activate_discount(self):
        customer = Customer.objects.create(
            phone='+77770000903', name='Existing private name', consent_at=timezone.now(),
            phone_verified_at=timezone.now(), is_test=False,
        )
        policy = LoyaltyPolicy.get()
        policy.confirmed = True
        policy.tiers = [{'threshold': 0, 'percent': 15}]
        policy.save()
        self.assertEqual(customer.discount_percent, 15)
        order, _ = self.create(self.payload(customer={'phone': customer.phone, 'name': 'Forged replacement', 'consent': True}))
        customer.refresh_from_db()
        self.assertEqual(customer.name, 'Existing private name')
        self.assertEqual(order.customer, customer)
        self.assertFalse(order.customer_identity_verified)
        self.assertEqual(order.discount_percent, 0)
        self.assertEqual(order.total, Decimal('2491.25'))
        payment = self.post(f'/api/staff/orders/{order.public_id}/action/', {
            'action': 'pay', 'amount': '2491.25', 'idempotency_key': str(uuid.uuid4()),
        })
        self.assertEqual(payment.status_code, 200, payment.content)
        self.assertEqual(LoyaltyEntry.objects.get(order=order).amount, Decimal('2491.25'))

    def test_new_phone_requires_name_and_consent_and_remains_unverified(self):
        claim = {'phone': '+77770000904'}
        for values in [claim, {**claim, 'name': 'New guest'}, {**claim, 'name': 'New guest', 'consent': False}]:
            with self.subTest(values=values):
                self.assertEqual(self.post('/api/staff/pos/', self.payload(customer=values)).status_code, 400)
        self.assertFalse(Customer.objects.filter(phone=claim['phone']).exists())
        order, _ = self.create(self.payload(customer={**claim, 'name': 'New guest', 'consent': True}))
        self.assertIsNone(order.customer.phone_verified_at)
        self.assertFalse(order.customer.is_test)
        self.assertFalse(order.customer_identity_verified)

    def test_table_and_mixed_drink_validation_do_not_save_partial_orders(self):
        inactive = Table.objects.create(name='Inactive', active=False, is_test=False)
        variations = [
            {'table_token': ''}, {'table_token': self.table.token() + 'tampered'},
            {'table_token': inactive.token()}, {'drink_preference': ''},
            {'fulfillment': 'unsupported'},
        ]
        for changes in variations:
            with self.subTest(changes=changes):
                self.assertEqual(self.post('/api/staff/pos/', self.payload(**changes)).status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_pos_details_and_print_are_staff_only_and_mutations_require_csrf(self):
        order, _ = self.create()
        detail_url = f'/api/staff/orders/{order.public_id}/'
        print_url = f'/admin/orders/{order.public_id}/print/'
        for role_user in [self.cashier, self.manager, self.owner]:
            client = Client()
            client.force_login(role_user)
            with self.subTest(user=role_user.username):
                self.assertEqual(client.get(detail_url).status_code, 200)
                self.assertEqual(client.get(print_url).status_code, 200)
        kitchen = Client()
        kitchen.force_login(self.kitchen)
        anonymous = Client()
        for client in [kitchen, anonymous]:
            self.assertEqual(self.post('/api/staff/pos/', self.payload(), client).status_code, 403)
            self.assertEqual(client.get(detail_url).status_code, 403)
        self.assertEqual(kitchen.get(print_url).status_code, 403)
        self.assertEqual(anonymous.get(print_url).status_code, 302)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.cashier)
        self.assertEqual(self.post('/api/staff/pos/', self.payload(), strict).status_code, 403)
        self.assertEqual(Order.objects.count(), 1)

    def test_print_uses_saved_prices_and_does_not_confirm_payment(self):
        order, _ = self.create()
        self.food.price = Decimal('8888.88')
        self.food.name_ru = 'Changed current menu name'
        self.food.save()
        original_updated_at = order.updated_at
        for _ in range(2):
            response = self.client.get(f'/admin/orders/{order.public_id}/print/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Сохранённое блюдо')
            self.assertNotContains(response, 'Changed current menu name')
            self.assertNotContains(response, '8888.88')
        order.refresh_from_db()
        self.assertEqual(order.updated_at, original_updated_at)
        self.assertEqual(order.total, Decimal('2491.25'))
        self.assertEqual(order.payment_status, 'unpaid')
        self.assertEqual(Payment.objects.count(), 0)
        result = self.client.get(f'/api/staff/orders/{order.public_id}/').json()['order']
        food = next(i for i in result['items'] if i['menu_item_id'] == self.food.pk)
        self.assertEqual(Decimal(food['unit_price']), Decimal('1000.50'))
        self.assertEqual(Decimal(result['total']), Decimal('2491.25'))

    def test_cash_tender_change_is_separate_from_revenue_and_replay_does_not_pay_twice(self):
        order, _ = self.create()
        url = f'/api/staff/orders/{order.public_id}/action/'
        insufficient = self.post(url, {'action': 'pay', 'amount': '2491.25', 'cash_received': '2400', 'idempotency_key': 'insufficient-cash-tender'})
        self.assertEqual(insufficient.status_code, 400, insufficient.content)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'unpaid')
        self.assertEqual(Payment.objects.count(), 0)
        payment = {'action': 'pay', 'amount': '2491.25', 'cash_received': '3000', 'idempotency_key': 'pos-cash-tender-payment'}
        response = self.post(url, payment)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.post(url, payment).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.actual_paid, Decimal('2491.25'))
        self.assertEqual(Payment.objects.get(order=order).amount, Decimal('2491.25'))
        self.assertEqual(Payment.objects.count(), 1)
        data = self.client.get(f'/api/staff/orders/{order.public_id}/').json()['order']
        self.assertEqual(Decimal(data['cash_received']), Decimal('3000'))
        self.assertEqual(Decimal(data['change']), Decimal('508.75'))
        response = self.client.get(f'/admin/orders/{order.public_id}/print/')
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.actual_paid, Decimal('2491.25'))
        self.assertEqual(Payment.objects.count(), 1)

    def test_non_cash_payment_cannot_record_cash_tender(self):
        order, _ = self.create(self.payload(payment_method='kaspi'))
        response = self.post(f'/api/staff/orders/{order.public_id}/action/', {
            'action': 'pay', 'amount': '2491.25', 'cash_received': '3000',
            'idempotency_key': 'invalid-noncash-tender',
        })
        self.assertEqual(response.status_code, 400, response.content)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'unpaid')
        self.assertEqual(Payment.objects.count(), 0)

    def test_recovery_key_is_scoped_to_operator(self):
        payload = self.payload(fulfillment='takeaway', table_token='')
        order, _ = self.create(payload)
        response = self.client.get('/api/staff/pos/status/', {'key': payload['idempotency_key']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['order']['public_id'], str(order.public_id))
        other = Client()
        other.force_login(self.manager)
        self.assertEqual(other.get('/api/staff/pos/status/', {'key': payload['idempotency_key']}).status_code, 404)
        self.assertEqual(Client().get('/api/staff/pos/status/', {'key': payload['idempotency_key']}).status_code, 403)
        self.assertEqual(Order.objects.count(), 1)

    def test_takeaway_is_labelled_for_kitchen_and_notifications(self):
        from .views import kitchen_data
        order, _ = self.create(self.payload(fulfillment='takeaway', table_token=''))
        self.assertEqual(kitchen_data(order)['table'], 'С собой')
        self.assertEqual(OutboxMessage.objects.filter(order=order).first().payload['table'], 'С собой')

    def test_takeaway_mixed_ignores_dine_in_service_choices_and_stale_table(self):
        payload=self.payload(fulfillment='takeaway',drink_preference='',table_token=self.table.token())
        order,_=self.create(payload)
        self.assertIsNone(order.table)
        self.assertEqual(order.drink_preference,'')
        repeat=self.post('/api/staff/pos/',{**payload,'drink_preference':'with_food','table_token':''})
        self.assertEqual(repeat.status_code,200,repeat.content)
        self.assertEqual(Order.objects.count(),1)
        correction=self.post(f'/api/staff/orders/{order.public_id}/action/',{'action':'correct','items':payload['items'],'reason':'Takeaway correction','drink_preference':''})
        self.assertEqual(correction.status_code,200,correction.content)
        order.refresh_from_db();self.assertEqual(order.drink_preference,'')

    def test_takeaway_legacy_idempotency_remains_recoverable(self):
        import hashlib
        payload=self.payload(fulfillment='takeaway',drink_preference='with_food',table_token='')
        order,_=self.create(payload)
        canonical={k:payload.get(k) for k in ['items','payment_method','drink_preference','comment']}
        canonical.update(table_token=None,fulfillment='takeaway',accept_order=True,eta=15,customer=None)
        old_hash=hashlib.sha256(json.dumps(canonical,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        Order.objects.filter(pk=order.pk).update(payload_hash=old_hash,drink_preference='with_food')
        replay=self.post('/api/staff/pos/',{**payload,'drink_preference':''})
        self.assertEqual(replay.status_code,200,replay.content)
        self.assertEqual(Order.objects.count(),1)
        order.refresh_from_db();self.assertEqual(order.payload_hash,old_hash)

    def test_dine_in_service_and_correction_remain_strict(self):
        self.assertEqual(self.post('/api/staff/pos/',self.payload(drink_preference='')).status_code,400)
        order,_=self.create(self.payload(items=[{'id':self.food.pk,'quantity':1}],drink_preference=''))
        response=self.post(f'/api/staff/orders/{order.public_id}/action/',{'action':'correct','items':[{'id':self.food.pk,'quantity':1},{'id':self.drink.pk,'quantity':1}],'reason':'Mixed order','drink_preference':''})
        self.assertEqual(response.status_code,400)
        self.assertEqual(order.items.count(),1)

    def test_takeaway_accepts_without_eta_and_never_invents_wait_time(self):
        order,_=self.create(self.payload(fulfillment='takeaway',table_token='',drink_preference='',eta=None))
        self.assertEqual(order.status,'accepted')
        self.assertIsNone(order.eta_minutes)
        self.assertIsNone(order.eta_at)
        self.assertFalse(order.is_delayed)

    def test_takeaway_ignores_stale_eta_and_dine_in_accepts_without_it(self):
        payload=self.payload(fulfillment='takeaway',table_token='',drink_preference='',eta=15)
        order,_=self.create(payload)
        self.assertIsNone(order.eta_at)
        self.assertEqual(self.post('/api/staff/pos/',{**payload,'eta':None}).status_code,200)
        self.assertEqual(self.post('/api/staff/pos/',self.payload(eta=None)).status_code,201)
