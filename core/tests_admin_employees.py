from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import path

from .admin_employees import employees
from .models import AuditEvent

urlpatterns = [path('admin/employees/', employees)]
User = get_user_model()


@override_settings(ROOT_URLCONF=__name__)
class AdminEmployeeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('employee-owner')
        self.owner.groups.add(Group.objects.create(name='owner'))
        self.cashier = User.objects.create_user('employee-cashier', password='Existing-account-1948!')
        self.cashier.groups.add(Group.objects.create(name='cashier'))
        self.kitchen = User.objects.create_user('employee-kitchen')
        self.kitchen.groups.add(Group.objects.create(name='kitchen'))
        self.manager = User.objects.create_user('employee-manager')
        self.manager.groups.add(Group.objects.create(name='manager'))
        self.client.force_login(self.owner)

    def payload(self, **values):
        return {
            'action': 'create', 'username': 'new-cook', 'name': 'Новый повар', 'role': 'kitchen',
            'password': 'Unique-staff-password-5793!', 'password_confirm': 'Unique-staff-password-5793!',
            **values,
        }

    def test_only_owner_can_view_or_mutate_accounts(self):
        anonymous = Client()
        self.assertRedirects(anonymous.get('/admin/employees/'), '/admin/login/', fetch_redirect_response=False)
        for user in [self.cashier, self.kitchen, self.manager]:
            self.client.force_login(user)
            self.assertEqual(self.client.get('/admin/employees/').status_code, 403)
            self.assertEqual(self.client.post('/admin/employees/', self.payload()).status_code, 403)
        self.assertFalse(User.objects.filter(username='new-cook').exists())

    def test_create_hashes_password_and_grants_only_operational_role(self):
        values = self.payload(is_staff='true', is_superuser='true')
        response = self.client.post('/admin/employees/', values)
        self.assertRedirects(response, '/admin/employees/', fetch_redirect_response=False)
        employee = User.objects.get(username='new-cook')
        self.assertTrue(employee.check_password(values['password']))
        self.assertNotEqual(employee.password, values['password'])
        self.assertFalse(employee.is_staff)
        self.assertFalse(employee.is_superuser)
        self.assertEqual(list(employee.groups.values_list('name', flat=True)), ['kitchen'])
        event = AuditEvent.objects.get(action='employee_created')
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.after['employee_id'], employee.pk)
        self.assertNotIn(values['password'], str(event.before) + str(event.after))

    def test_creation_rejects_duplicate_privileged_role_or_bad_password(self):
        invalid = [
            self.payload(username='EMPLOYEE-CASHIER'), self.payload(role='owner'),
            self.payload(role='manager'), self.payload(password='short', password_confirm='short'),
            self.payload(password_confirm='different'),
        ]
        for values in invalid:
            with self.subTest(values={key: value for key, value in values.items() if 'password' not in key}):
                response = self.client.post('/admin/employees/', values)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, values['password'], status_code=400)
        self.assertFalse(User.objects.filter(username='new-cook').exists())
        self.assertEqual(AuditEvent.objects.filter(action='employee_created').count(), 0)

    def test_block_unblock_is_audited_and_idempotent(self):
        values = {'action': 'toggle', 'employee_id': self.cashier.pk, 'active': '0'}
        self.assertEqual(self.client.post('/admin/employees/', values).status_code, 302)
        self.cashier.refresh_from_db()
        self.assertFalse(self.cashier.is_active)
        self.assertEqual(AuditEvent.objects.filter(action='employee_blocked').count(), 1)
        self.client.post('/admin/employees/', values)
        self.assertEqual(AuditEvent.objects.filter(action='employee_blocked').count(), 1)
        self.assertEqual(self.client.post('/admin/employees/', {**values, 'active': '1'}).status_code, 302)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)
        self.assertEqual(AuditEvent.objects.filter(action='employee_unblocked').count(), 1)

    def test_owner_self_manager_superuser_and_staff_are_protected(self):
        superuser = User.objects.create_superuser('protected-superuser', password='Unique-superuser-9184!')
        staff = User.objects.create_user('protected-staff', is_staff=True)
        staff.groups.add(Group.objects.get(name='cashier'))
        self.manager.groups.add(Group.objects.get(name='cashier'))
        for user in [self.owner, self.manager, superuser, staff]:
            response = self.client.post('/admin/employees/', {'action': 'toggle', 'employee_id': user.pk, 'active': '0'})
            self.assertEqual(response.status_code, 403)
            user.refresh_from_db()
            self.assertTrue(user.is_active)

    def test_search_filters_and_blocked_role_are_visible(self):
        self.kitchen.is_active = False
        self.kitchen.save()
        response = self.client.get('/admin/employees/', {'role': 'kitchen', 'status': 'blocked', 'q': 'kitchen'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['user'].pk for row in response.context['employee_rows']], [self.kitchen.pk])
        self.assertTrue(response.context['employee_rows'][0]['manageable'])

    def test_create_requires_csrf_and_never_repopulates_password(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(browser.post('/admin/employees/', self.payload()).status_code, 403)
        page = browser.get('/admin/employees/')
        self.assertEqual(page.status_code, 200)
        token = browser.cookies[settings.CSRF_COOKIE_NAME].value
        values = self.payload(password_confirm='invalid')
        response = browser.post('/admin/employees/', values, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, values['password'], status_code=400)
        self.assertContains(response, 'name="password"', status_code=400)

    def test_invalid_toggle_values_do_not_change_accounts(self):
        for values in [{'action':'toggle','employee_id':'bad','active':'0'}, {'action':'toggle','employee_id':self.cashier.pk,'active':'yes'}, {'action':'delete','employee_id':self.cashier.pk}]:
            self.assertEqual(self.client.post('/admin/employees/', values).status_code, 400)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)
