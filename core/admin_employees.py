"""Owner-only operational staff accounts, separate from Django administration permissions."""
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .views import roles
from .models import DeveloperAccess

User = get_user_model()
STAFF_ROLES = {'cashier': 'Кассир', 'kitchen': 'Кухня'}
ROLE_LABELS = {'owner': 'Администратор', 'manager': 'Управляющий', **STAFF_ROLES}


class EmployeeCreateForm(forms.Form):
    username = forms.CharField(max_length=150, label='Логин', validators=User._meta.get_field('username').validators)
    name = forms.CharField(max_length=150, label='Имя сотрудника')
    role = forms.ChoiceField(choices=tuple(STAFF_ROLES.items()), label='Роль')
    password = forms.CharField(widget=forms.PasswordInput, strip=False, label='Пароль')
    password_confirm = forms.CharField(widget=forms.PasswordInput, strip=False, label='Повторите пароль')

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('Такой логин уже занят. Выберите другой.')
        return username

    def clean(self):
        values = super().clean()
        password = values.get('password')
        if password and password != values.get('password_confirm'):
            self.add_error('password_confirm', 'Пароли не совпадают.')
        if password:
            candidate = User(username=values.get('username', ''), first_name=values.get('name', ''))
            try:
                validate_password(password, user=candidate)
            except ValidationError as error:
                self.add_error('password', error)
        return values


class EmployeeStatusForm(forms.Form):
    employee_id = forms.IntegerField(min_value=1)
    active = forms.ChoiceField(choices=(('0', 'Заблокировать'), ('1', 'Разблокировать')))


def manageable(user, actor):
    """Never let an operational account form affect privileged or the acting account."""
    roles_set = {group.name for group in user.groups.all()}
    return (
        user.pk != actor.pk and not user.is_superuser and not user.is_staff
        and not hasattr(user,'developer_access')
        and account_role(user) in STAFF_ROLES
        and not roles_set.intersection({'owner', 'manager'})
    )


def account_role(user):
    if user.is_superuser:
        return 'owner'
    names = {group.name for group in user.groups.all()}
    return next((role for role in ('owner', 'manager', 'cashier', 'kitchen') if role in names), '')


@roles('owner')
def employees(request):
    create_form = EmployeeCreateForm()
    error = ''
    status_code = 200
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            create_form = EmployeeCreateForm(request.POST)
            if create_form.is_valid():
                values = create_form.cleaned_data
                try:
                    with transaction.atomic():
                        employee = User.objects.create_user(
                            username=values['username'], first_name=values['name'],
                            password=values['password'], is_active=True, is_staff=False, is_superuser=False,
                        )
                        employee.groups.add(Group.objects.get_or_create(name=values['role'])[0])
                        services.audit('employee_created', request.user, after={
                            'employee_id': employee.pk, 'username': employee.username,
                            'name': employee.first_name, 'role': values['role'], 'active': True,
                        })
                except IntegrityError:
                    create_form.add_error('username', 'Такой логин уже занят. Выберите другой.')
                else:
                    messages.success(request, 'Аккаунт сотрудника создан / Қызметкер аккаунты құрылды')
                    return redirect('/admin/employees/')
            status_code = 400
        elif action == 'toggle':
            form = EmployeeStatusForm(request.POST)
            if form.is_valid():
                with transaction.atomic():
                    employee = get_object_or_404(User.objects.select_for_update().prefetch_related('groups','developer_access'), pk=form.cleaned_data['employee_id'])
                    if not manageable(employee, request.user):
                        error = 'Этот аккаунт нельзя изменить здесь / Бұл аккаунтты мұнда өзгертуге болмайды'
                        status_code = 403
                    else:
                        active = form.cleaned_data['active'] == '1'
                        if employee.is_active != active:
                            before = {'employee_id': employee.pk, 'username': employee.username, 'active': employee.is_active}
                            employee.is_active = active
                            employee.save(update_fields=['is_active'])
                            services.audit('employee_unblocked' if active else 'employee_blocked', request.user,
                                before=before, after={**before, 'active': active, 'role': account_role(employee)})
                        messages.success(request, 'Доступ сотрудника обновлён / Қызметкер рұқсаты жаңартылды')
                        return redirect('/admin/employees/')
            else:
                error = 'Некорректные данные аккаунта / Аккаунт деректері қате'
                status_code = 400
        else:
            error = 'Неизвестное действие / Белгісіз әрекет'
            status_code = 400

    query = request.GET.get('q', '').strip()[:120]
    role = request.GET.get('role', '')
    if role not in ROLE_LABELS:
        role = ''
    status = request.GET.get('status', '')
    if status not in ('active', 'blocked'):
        status = ''
    users = User.objects.filter(Q(groups__name__in=services.ROLES) | Q(is_superuser=True)).distinct().select_related('developer_access').prefetch_related('groups').order_by('username', 'pk')
    users = users.exclude(pk__in=DeveloperAccess.objects.exclude(user_id=request.user.pk).values('user_id'))
    if query:
        users = users.filter(Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    if role == 'owner':
        users = users.filter(Q(groups__name=role) | Q(is_superuser=True)).distinct()
    elif role:
        users = users.filter(groups__name=role).distinct()
    if status:
        users = users.filter(is_active=(status == 'active'))
    page = Paginator(users, 25).get_page(request.GET.get('page'))
    rows = [{'user': user, 'role': account_role(user), 'label': ROLE_LABELS.get(account_role(user), 'Сотрудник'), 'manageable': manageable(user, request.user)} for user in page.object_list]
    return render(request, 'admin_portal/employees.html', {
        'section': 'employees', 'page_title': 'Сотрудники', 'page_title_kz': 'Қызметкерлер',
        'page_subtitle': 'Личные аккаунты и доступ к рабочим инструментам',
        'create_form': create_form, 'employee_page': page, 'employee_rows': rows,
        'filters': {'q': query, 'role': role, 'status': status},
        'filter_query': urlencode({'q': query, 'role': role, 'status': status}), 'employee_error': error,
    }, status=status_code)
