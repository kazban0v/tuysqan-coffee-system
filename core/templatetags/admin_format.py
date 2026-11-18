from decimal import Decimal, InvalidOperation
from django import template

register=template.Library()

@register.filter
def money(value):
    try:
        number=Decimal(str(value or 0))
        return (f'{number:,.0f}' if number==number.to_integral_value() else f'{number:,.2f}').replace(',','\u00a0').replace('.',',')+' ₸'
    except (InvalidOperation,ValueError,TypeError):return '—'

@register.simple_tag
def ap_query(request,**values):
    query=request.GET.copy()
    for key,value in values.items():query[key]=value
    return '?'+query.urlencode()

@register.filter
def status_ru(value):return {'new':'Ожидает подтверждения','accepted':'Принят','preparing':'Готовится','ready':'Готов','served':'Подан / выдан','cancelled':'Отменён','rejected':'Отклонён','paid':'Оплачен','unpaid':'Не оплачен','refunded':'Возврат'}.get(value,value)

@register.filter
def status_kz(value):return {'new':'Растауды күтуде','accepted':'Қабылданды','preparing':'Дайындалуда','ready':'Дайын','served':'Ұсынылды / берілді','cancelled':'Тоқтатылды','rejected':'Қабылданбады','paid':'Төленген','unpaid':'Төленбеген','refunded':'Қайтарылды'}.get(value,value)

@register.filter
def action_ru(value):
    from core.admin_portal import ACTION_LABELS
    return ACTION_LABELS.get(value,value)

@register.filter
def action_kz(value):
    return {'accept':'Тапсырысты қабылдады','accept_and_pay':'Тапсырыс пен төлемді қабылдады','payment_confirmed':'Төлемді растады','payment_reversed':'Төлемді қайтарды','ready':'Тапсырыс дайындығын растады','serve':'Ұсынуды белгіледі','food_eta':'Тағам уақытын белгіледі','drink_eta':'Сусын уақытын белгіледі','item_ready':'Позиция дайындығын белгіледі','discount_confirmed':'Жеңілдікті өзгертті','review_updated':'Пікірді өңдеді','feedback_updated':'Өтінішті өңдеді','menu_item_updated':'Мәзір позициясын өзгертті','menu_item_created':'Мәзір позициясын қосты','menu_availability':'Стоп-парақты өзгертті','category_updated':'Санатты өзгертті','category_created':'Санат қосты','employee_created':'Қызметкер аккаунтын құрды','employee_blocked':'Қызметкерді бұғаттады','employee_unblocked':'Қызметкер бұғатын ашты','loyalty_policy_updated':'Жеңілдік бағдарламасын өзгертті','settings_kitchen_release':'Асүйге жіберу тәртібін өзгертті','table_updated':'Үстелді өзгертті','order_created':'Тапсырыс құрды','loyalty_purchase':'Жинақ есептеді','loyalty_reversal':'Жинақты жойды','loyalty_reconciled':'Жинақты қалпына келтірді','customer_phone_verified':'Телефонды растады','customer_profile_completed':'Профильді толтырды','preparing':'Дайындауды бастады','item_preparing':'Позицияны дайындай бастады','drinks_ready':'Сусындар дайындығын белгіледі','cancel':'Тапсырысты тоқтатты','reject':'Тапсырысты қабылдамады','correct':'Тапсырыс құрамын өзгертті','eta':'Сусын уақытын өзгертті'}.get(value,value)

@register.simple_tag(takes_context=True)
def staff_identity(context,user):
    if not user:return 'Система / Жүйе'
    actor=context.get('request').user if context.get('request') else None
    if user.pk in context.get('private_developer_ids',set()) and (not actor or actor.pk!=user.pk):return 'Служебный аккаунт / Жүйелік аккаунт'
    return user.username
