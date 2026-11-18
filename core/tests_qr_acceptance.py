"""Manual QR acceptance and payment regressions, isolated in Django's test DB."""
import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.utils import timezone

from .models import (
    AppSettings, AuditEvent, Customer, MenuCategory, MenuItem, Order,
    OutboxMessage, Payment, Table,
)
from . import services


class QRAcceptanceTests(TestCase):
    def setUp(self):
        self.cashier = self.user('cashier')
        self.kitchen = self.user('kitchen')
        self.staff = Client()
        self.staff.force_login(self.cashier)
        self.table = Table.objects.create(name='Стол 8', active=True, is_test=False)
        category = MenuCategory.objects.create(slug='qr-acceptance', name_ru='Блюда', name_kz='Тағамдар')
        self.food = MenuItem.objects.create(
            category=category, slug='qr-acceptance-food', name_ru='QR test food',
            name_kz='QR test food', kind='food', price='1000.00', is_test=False,
        )
        self.customer = Customer.objects.create(
            name='QR synthetic guest', phone='+77770000801', consent_at=timezone.now(), is_test=False,
        )
        self.guest = Client()
        self.guest.get('/table/' + self.table.token() + '/')
        identified = self.post(self.guest, '/api/account/identify/', {'phone': self.customer.phone, 'consent': True})
        self.assertEqual(identified.status_code, 200)

    def user(self, role):
        user = User.objects.create_user('qr-acceptance-' + role)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def post(self, client, path, payload):
        return client.post(path, json.dumps(payload), content_type='application/json')

    def qr_order(self, **changes):
        payload = {
            'items': [{'id': self.food.pk, 'quantity': 1}],
            'table_token': self.table.token(), 'payment_method': 'cash',
            'idempotency_key': str(uuid.uuid4()),
        }
        payload.update(changes)
        response = self.post(self.guest, '/api/orders/', payload)
        self.assertEqual(response.status_code, 201, response.content)
        return Order.objects.get(public_id=response.json()['order']['public_id'])

    def action(self, order, payload=None, client=None):
        return self.post(client or self.staff, f'/api/staff/orders/{order.public_id}/action/', payload or self.combined())

    def combined(self, **changes):
        payload = {
            'action': 'accept_and_pay', 'eta': 10, 'amount': '1000.00',
            'cash_received': '2000.00', 'idempotency_key': str(uuid.uuid4()),
        }
        payload.update(changes)
        return payload

    def test_qr_order_waits_for_manual_acceptance(self):
        order = self.qr_order()
        self.assertEqual(order.source, 'web')
        self.assertEqual(order.status, 'new')
        self.assertEqual(order.payment_status, 'unpaid')
        self.assertIsNone(order.accepted_at)
        self.assertIsNone(order.eta_at)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertFalse(services.kitchen_queue().filter(pk=order.pk).exists())
        self.assertEqual(OutboxMessage.objects.filter(order=order).count(), 1)

    def test_standard_manual_acceptance_stays_separate_from_payment(self):
        order = self.qr_order()
        response = self.action(order, {'action': 'accept', 'eta': 15})
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertEqual(order.payment_status, 'unpaid')
        self.assertIsNone(order.eta_minutes)
        self.assertIsNone(order.food_eta_at)
        self.assertEqual(Payment.objects.count(), 0)

    def test_combined_action_accepts_and_confirms_payment_without_marking_ready(self):
        settings = AppSettings.get()
        settings.kitchen_release = 'payment'
        settings.save()
        order = self.qr_order()
        response = self.action(order)
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertIsNotNone(order.accepted_at)
        self.assertIsNone(order.eta_minutes)
        self.assertIsNone(order.food_eta_at)
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.actual_paid, Decimal('1000.00'))
        self.assertEqual(Payment.objects.get(order=order).amount, Decimal('1000.00'))
        self.assertEqual(order.items.get().status, 'pending')
        self.assertIsNone(order.ready_at)
        self.assertIsNone(order.served_at)
        self.assertTrue(services.kitchen_queue().filter(pk=order.pk).exists())
        self.assertEqual(services.payment_cash_facts(order), {'cash_received': '2000.00', 'change': '1000.00'})
        self.assertFalse(order.customer_identity_verified)

    def test_invalid_combined_action_rolls_back_acceptance_and_finances(self):
        order = self.qr_order()
        version = order.version
        baseline = (AuditEvent.objects.count(), OutboxMessage.objects.count())
        for changes in [{'eta': 0}, {'amount': '0'}, {'amount': '900'}, {'cash_received': '900'}]:
            with self.subTest(changes=changes):
                response = self.action(order, self.combined(**changes))
                self.assertEqual(response.status_code, 400, response.content)
                order.refresh_from_db()
                self.assertEqual(order.status, 'new')
                self.assertEqual(order.payment_status, 'unpaid')
                self.assertEqual(order.actual_paid, 0)
                self.assertIsNone(order.accepted_at)
                self.assertIsNone(order.eta_at)
                self.assertEqual(order.version, version)
                self.assertEqual(Payment.objects.count(), 0)
                self.assertEqual((AuditEvent.objects.count(), OutboxMessage.objects.count()), baseline)

    def test_exact_replay_changes_no_version_audit_or_payment(self):
        order = self.qr_order()
        payload = self.combined()
        self.assertEqual(self.action(order, payload).status_code, 200)
        order.refresh_from_db()
        baseline = (order.version, order.updated_at, order.accepted_at, order.eta_at,
                    AuditEvent.objects.count(), OutboxMessage.objects.count())
        for _ in range(2):
            response = self.action(order, payload)
            self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db()
        self.assertEqual((order.version, order.updated_at, order.accepted_at, order.eta_at,
                          AuditEvent.objects.count(), OutboxMessage.objects.count()), baseline)
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        self.assertEqual(Order.objects.count(), 1)
        services.act_on_order(order.public_id, self.kitchen, 'item_ready', {'item_id':order.items.get().pk})
        services.act_on_order(order.public_id, self.cashier, 'ready')
        order.refresh_from_db()
        version = order.version
        self.assertEqual(self.action(order, payload).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, 'ready')
        self.assertEqual(order.version, version)

    def test_changed_replay_key_amount_or_tender_is_rejected(self):
        order = self.qr_order()
        payload = self.combined()
        self.assertEqual(self.action(order, payload).status_code, 200)
        order.refresh_from_db()
        baseline = (order.version, AuditEvent.objects.count(), OutboxMessage.objects.count())
        for changes in [
            {'idempotency_key': str(uuid.uuid4())},
            {'amount': '1100', 'reason': 'changed replay'},
            {'cash_received': '3000'},
        ]:
            with self.subTest(changes=changes):
                response = self.action(order, {**payload, **changes})
                self.assertEqual(response.status_code, 400, response.content)
        order.refresh_from_db()
        self.assertEqual((order.version, AuditEvent.objects.count(), OutboxMessage.objects.count()), baseline)
        self.assertEqual(order.actual_paid, Decimal('1000.00'))
        self.assertEqual(Payment.objects.count(), 1)

    def test_kitchen_anonymous_and_csrf_requests_cannot_combine_acceptance(self):
        order = self.qr_order()
        kitchen = Client()
        kitchen.force_login(self.kitchen)
        anonymous = Client()
        for client in [kitchen, anonymous]:
            with self.subTest(client=client):
                self.assertEqual(self.action(order, client=client).status_code, 403)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.cashier)
        self.assertEqual(self.action(order, client=strict).status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, 'new')
        self.assertEqual(Payment.objects.count(), 0)

    def test_combined_action_does_not_reinterpret_pos_orders(self):
        order, _ = services.create_pos_order(self.cashier, {
            'items': [{'id': self.food.pk, 'quantity': 1}],
            'fulfillment': 'takeaway', 'payment_method': 'cash',
            'idempotency_key': str(uuid.uuid4()), 'accept_order': False,
        })
        response = self.action(order)
        self.assertEqual(response.status_code, 400, response.content)
        order.refresh_from_db()
        self.assertEqual(order.status, 'new')
        services.act_on_order(order.public_id, self.cashier, 'accept')
        services.confirm_payment(order, self.cashier, '1000.00', key='pos-standard-payment')
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertIsNone(order.eta_at)
        self.assertEqual(order.payment_status, 'paid')
