"""Cash payment/method/history regressions, using only Django's isolated test DB."""
import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from . import services
from .models import AuditEvent, Customer, MenuCategory, MenuItem, Order, Payment, Table


class CashPaymentTests(TestCase):
    def setUp(self):
        self.cashier = User.objects.create_user('cash-money-cashier')
        self.cashier.groups.add(Group.objects.get_or_create(name='cashier')[0])
        self.manager = User.objects.create_user('cash-money-manager')
        self.manager.groups.add(Group.objects.get_or_create(name='manager')[0])
        self.client.force_login(self.cashier)
        self.table = Table.objects.create(name='Стол 8', active=True, is_test=False)
        category = MenuCategory.objects.create(slug='cash-money', name_ru='Блюда', name_kz='Тағамдар')
        self.food = MenuItem.objects.create(category=category, slug='cash-money-food', name_ru='Cash test food', name_kz='Cash test food', price='1000', kind='food', is_test=False)
        self.customer = Customer.objects.create(name='Synthetic guest', phone='+77770000881', consent_at=timezone.now(), phone_verified_at=timezone.now(), is_test=False)

    def order(self, method='cash', accepted=True):
        order, _ = services.create_order(self.customer, {
            'items': [{'id': self.food.pk, 'quantity': 1}], 'table_token': self.table.token(),
            'payment_method': method, 'idempotency_key': str(uuid.uuid4()),
        })
        if accepted:
            order = services.act_on_order(order.public_id, self.cashier, 'accept', {'eta': 10})
        return order

    def post(self, order, payload):
        return self.client.post(f'/api/staff/orders/{order.public_id}/action/', json.dumps(payload), content_type='application/json')

    def pay(self, order, **changes):
        payload = {'action': 'pay', 'amount': '1000', 'idempotency_key': str(uuid.uuid4())}
        payload.update(changes)
        return self.post(order, payload)

    def test_guest_planned_bank_can_be_paid_in_cash_without_counting_banknote_as_revenue(self):
        order = self.order(method='kaspi')
        response = self.pay(order, payment_method='cash', cash_received='2000')
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.payment_method, 'cash')
        self.assertEqual(order.actual_paid, Decimal('1000'))
        payment = Payment.objects.get(order=order)
        self.assertEqual(payment.method, 'cash')
        self.assertEqual(payment.amount, Decimal('1000'))
        self.assertEqual(services.payment_cash_facts(order), {'cash_received': '2000.00', 'change': '1000.00'})

    def test_cash_order_can_be_confirmed_by_bank_without_cash_tender(self):
        order = self.order()
        response = self.pay(order, payment_method='halyk')
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.payment_method, 'halyk')
        self.assertEqual(Payment.objects.get(order=order).method, 'halyk')
        self.assertEqual(services.payment_cash_facts(order), {'cash_received': None, 'change': None})

    def test_invalid_method_and_insufficient_cash_leave_method_status_and_audit_unchanged(self):
        order = self.order(method='kaspi')
        baseline = (order.version, order.updated_at, AuditEvent.objects.count())
        for changes in [{'payment_method': 'unsupported'}, {'payment_method': 'cash', 'cash_received': '999'}, {'payment_method': 'halyk', 'cash_received': '2000'}]:
            with self.subTest(changes=changes):
                response = self.pay(order, **changes)
                self.assertEqual(response.status_code, 400, response.content)
                order.refresh_from_db()
                self.assertEqual(order.payment_method, 'kaspi')
                self.assertEqual(order.payment_status, 'unpaid')
                self.assertEqual((order.version, order.updated_at, AuditEvent.objects.count()), baseline)
                self.assertEqual(Payment.objects.count(), 0)

    def test_exact_cash_replay_changes_no_version_audit_or_payment(self):
        order = self.order()
        payload = {'action': 'pay', 'payment_method': 'cash', 'amount': '1000', 'cash_received': '2000', 'idempotency_key': str(uuid.uuid4())}
        self.assertEqual(self.post(order, payload).status_code, 200)
        order.refresh_from_db()
        baseline = (order.version, order.updated_at, AuditEvent.objects.count(), Payment.objects.count())
        for _ in range(2):
            self.assertEqual(self.post(order, payload).status_code, 200)
        order.refresh_from_db()
        self.assertEqual((order.version, order.updated_at, AuditEvent.objects.count(), Payment.objects.count()), baseline)
        self.assertEqual(self.post(order, {**payload, 'payment_method': 'kaspi', 'cash_received': None}).status_code, 400)
        self.assertEqual(self.post(order, {**payload, 'cash_received': '3000'}).status_code, 400)

    def test_combined_acceptance_method_switch_and_payment_failure_are_atomic(self):
        order = self.order(method='kaspi', accepted=False)
        payload = {'action': 'accept_and_pay', 'eta': 10, 'payment_method': 'cash', 'amount': '1000', 'cash_received': '999', 'idempotency_key': str(uuid.uuid4())}
        baseline = (order.version, AuditEvent.objects.count())
        self.assertEqual(self.post(order, payload).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, 'new')
        self.assertEqual(order.payment_method, 'kaspi')
        self.assertEqual((order.version, AuditEvent.objects.count()), baseline)
        self.assertEqual(Payment.objects.count(), 0)
        payload['cash_received'] = '2000'
        self.assertEqual(self.post(order, payload).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertEqual(order.payment_method, 'cash')
        self.assertEqual(self.post(order, payload).status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)

    def test_refund_history_preserves_tender_change_and_is_staff_only(self):
        order = self.order()
        self.assertEqual(self.pay(order, payment_method='cash', cash_received='2000').status_code, 200)
        order.refresh_from_db()
        services.reverse_payment(order, self.manager, 'Synthetic reversal')
        order.refresh_from_db()
        current = services.order_data(order, True)
        self.assertEqual(order.actual_paid, 0)
        self.assertIsNone(current['cash_received'])
        self.assertIsNone(current['change'])
        self.assertEqual(len(current['payment_history']), 1)
        history = current['payment_history'][0]
        self.assertEqual(history['cash_received'], '2000.00')
        self.assertEqual(history['change'], '1000.00')
        self.assertEqual(history['amount'], '1000.00')
        self.assertIsNotNone(history['reversed_at'])
        self.assertEqual(history['reversal_reason'], 'Synthetic reversal')
        self.assertNotIn('payment_history', services.order_data(order))

    def test_changed_cost_needs_reason_and_stores_cost_separately_from_tender(self):
        order = self.order()
        self.assertEqual(self.pay(order, amount='900', cash_received='1000').status_code, 400)
        response = self.pay(order, amount='900', cash_received='1000', reason='Synthetic adjustment')
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal('1000'))
        self.assertEqual(order.actual_paid, Decimal('900'))
        self.assertEqual(Payment.objects.get(order=order).amount, Decimal('900'))
        self.assertEqual(services.payment_cash_facts(order)['change'], '100.00')
