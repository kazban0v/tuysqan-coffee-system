"""Read-only, localized differences for the administrator audit journal."""
from .templatetags.admin_format import money, status_ru, status_kz

LABELS = {
    'status': ('Статус', 'Күйі'), 'payment_status': ('Оплата', 'Төлем'),
    'subtotal': ('До скидки', 'Жеңілдікке дейін'), 'total': ('Итого', 'Барлығы'),
    'actual_paid': ('Оплачено', 'Төленді'), 'discount_percent': ('Скидка', 'Жеңілдік'),
    'payment_method': ('Способ оплаты', 'Төлем тәсілі'),
    'cash_received': ('Получено наличными', 'Қолма-қол алынды'), 'change': ('Сдача', 'Қайтарым'),
    'price': ('Цена', 'Бағасы'), 'quantity': ('Количество', 'Саны'),
    'comment': ('Комментарий', 'Түсініктеме'), 'note': ('Заметка', 'Ескертпе'),
    'name_ru': ('Название на русском', 'Орысша атауы'), 'name_kz': ('Название на казахском', 'Қазақша атауы'),
    'name': ('Имя / название', 'Аты / атауы'), 'username': ('Логин', 'Логин'),
    'role': ('Роль', 'Рөлі'), 'active': ('Доступ', 'Қолжетімділік'),
    'available': ('В наличии', 'Бар'), 'enabled': ('Включено', 'Қосылған'),
    'confirmed': ('Подтверждено', 'Расталған'), 'amount': ('Сумма', 'Сома'),
    'balance': ('Накопления', 'Жинақ'), 'kind': ('Тип', 'Түрі'), 'value': ('Значение', 'Мәні'),
    'food_eta_minutes': ('Время блюд', 'Тағам уақыты'), 'drink_eta_minutes': ('Время напитков', 'Сусын уақыты'),
    'eta_minutes': ('Время приготовления', 'Дайындалу уақыты'), 'image': ('Изображение', 'Сурет'),
    'category_id': ('Категория', 'Санат'), 'sort_order': ('Порядок', 'Реті'),
    'phone': ('Телефон', 'Телефон'), 'rating': ('Оценка', 'Баға'),
    'threshold': ('Порог покупок', 'Сатып алу шегі'), 'percent': ('Скидка', 'Жеңілдік'),
    'min_spend': ('Покупки от', 'Сатып алу сомасы'),
}
AMOUNTS = {'subtotal', 'total', 'actual_paid', 'price', 'amount', 'balance', 'cash_received', 'change', 'threshold', 'min_spend'}
INTERNAL = {'id', 'payment_id', 'handler_id', 'review_id', 'customer_id', 'user_id'}
VALUES = {
    'cash': ('Наличные', 'Қолма-қол'), 'kaspi': ('Kaspi QR', 'Kaspi QR'), 'halyk': ('Halyk', 'Halyk'),
    'food': ('Блюдо', 'Тағам'), 'drink': ('Напиток', 'Сусын'),
    'cashier': ('Кассир', 'Кассир'), 'kitchen': ('Кухня', 'Асүй'), 'owner': ('Администратор', 'Әкімші'),
    'manager': ('Менеджер', 'Менеджер'), 'new': ('Новый', 'Жаңа'),
    'pending': ('Ожидает', 'Күтуде'), 'done': ('Обработано', 'Өңделді'),
    'acceptance': ('После принятия', 'Қабылданғаннан кейін'), 'payment': ('После оплаты', 'Төлемнен кейін'),
}
MISSING = object()


def display(value, key, lang):
    if value is MISSING or value is None or value == '':
        return '—'
    if key in AMOUNTS:
        return money(value)
    if key in {'discount_percent', 'percent'}:
        return f'{value}%'
    if key.endswith('_minutes'):
        return f'{value} ' + ('мин' if lang == 0 else 'мин')
    if isinstance(value, bool) or str(value) in {'True', 'False'}:
        return ('Да', 'Иә')[lang] if value is True or value == 'True' else ('Нет', 'Жоқ')[lang]
    if key in {'status', 'payment_status'}:
        localized = (status_ru if lang == 0 else status_kz)(str(value))
        return VALUES.get(str(value), (localized, localized))[lang] if localized == str(value) else localized
    if isinstance(value, str) and value in VALUES:
        return VALUES[value][lang]
    return str(value)


def differences(before, after, names=None, prefix=('', '')):
    """Omit unchanged snapshots and internal IDs; preserve original stored events."""
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    rows = []
    for key in dict.fromkeys([*after, *before]):
        old, new = before.get(key, MISSING), after.get(key, MISSING)
        if old == new or key in INTERNAL:
            continue
        if key == 'items':
            old_items = {str(item.get('id', i)): item for i, item in enumerate(old if isinstance(old, list) else []) if isinstance(item, dict)}
            new_items = {str(item.get('id', i)): item for i, item in enumerate(new if isinstance(new, list) else []) if isinstance(item, dict)}
            for item_id in dict.fromkeys([*new_items, *old_items]):
                label = (names or {}).get(item_id, (f'Позиция №{item_id}', f'Позиция №{item_id}'))
                rows.extend(differences(old_items.get(item_id, {}), new_items.get(item_id, {}), names, label))
            continue
        if isinstance(old, dict) or isinstance(new, dict):
            rows.extend(differences(old, new, names, LABELS.get(key, ('Настройка', 'Баптау'))))
            continue
        if isinstance(old, list) or isinstance(new, list):
            # Structured settings, such as loyalty tiers, remain readable as individual changes.
            old_list = old if isinstance(old, list) else []
            new_list = new if isinstance(new, list) else []
            for i in range(max(len(old_list), len(new_list))):
                rows.extend(differences(old_list[i] if i < len(old_list) else {}, new_list[i] if i < len(new_list) else {}, names, (f'Уровень {i+1}', f'{i+1}-деңгей')))
            continue
        labels = LABELS.get(key, ('Дополнительное изменение', 'Қосымша өзгеріс'))
        rows.append({
            'label_ru': ' · '.join(filter(None, (prefix[0], labels[0]))),
            'label_kz': ' · '.join(filter(None, (prefix[1], labels[1]))),
            'before_ru': display(old, key, 0), 'before_kz': display(old, key, 1),
            'after_ru': display(new, key, 0), 'after_kz': display(new, key, 1),
        })
    return rows


def present_events(events):
    from .models import MenuItem
    ids = set()
    for event in events:
        for snapshot in (event.before, event.after):
            if isinstance(snapshot, dict):
                for item in snapshot.get('items', []) or []:
                    if isinstance(item, dict) and str(item.get('id', '')).isdigit():
                        ids.add(int(item['id']))
    names = {str(item.pk): (item.name_ru, item.name_kz or item.name_ru) for item in MenuItem.objects.filter(pk__in=ids)} if ids else {}
    for event in events:
        event.changes = differences(event.before, event.after, names)
        event.visible_changes = event.changes[:2]
        event.more_changes = event.changes[2:]
