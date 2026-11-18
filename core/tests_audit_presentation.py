from copy import deepcopy
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from .audit_presentation import differences


class AuditPresentationTests(SimpleTestCase):
    def test_payment_shows_only_changes_and_preserves_snapshots(self):
        before = {'status': 'served', 'payment_status': 'unpaid', 'total': '9101.00', 'actual_paid': '0.00', 'items': [{'id': 30, 'quantity': 1, 'price': '3870.00', 'status': 'ready'}]}
        after = {**before, 'payment_status': 'paid', 'actual_paid': '9101.00', 'payment_id': 12}
        original = deepcopy((before, after))
        rows = differences(before, after)
        self.assertEqual([row['label_ru'] for row in rows], ['Оплата', 'Оплачено'])
        self.assertEqual(rows[0]['before_ru'], 'Не оплачен')
        self.assertEqual(rows[0]['after_kz'], 'Төленген')
        self.assertEqual(rows[1]['after_ru'], '9\u00a0101 ₸')
        self.assertEqual((before, after), original)

    def test_item_changes_resolve_names_and_skip_unchanged_items(self):
        before = {'items': [{'id': 30, 'quantity': 1, 'status': 'pending'}, {'id': 31, 'quantity': 2}]}
        after = {'items': [{'id': 30, 'quantity': 1, 'status': 'ready'}, {'id': 31, 'quantity': 2}]}
        rows = differences(before, after, {'30': ('Овсянка', 'Сұлы ботқасы')})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label_ru'], 'Овсянка · Статус')
        self.assertEqual(rows[0]['label_kz'], 'Сұлы ботқасы · Күйі')

    def test_removed_item_and_empty_snapshot_are_readable(self):
        rows = differences({'items': [{'id': 4, 'quantity': 1}]}, {})
        self.assertEqual(rows[0]['after_ru'], '—')
        self.assertEqual(differences(None, None), [])

    def test_untrusted_values_are_escaped_in_both_languages(self):
        change = differences({'comment': ''}, {'comment': '<img src=x onerror=alert(1)>'})[0]
        html = render_to_string('admin_portal/audit_change.html', {'change': change})
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)

    def test_loyalty_settings_show_changed_tier_fields(self):
        rows = differences({'tiers': [{'threshold': 50000, 'percent': 5}]}, {'tiers': [{'threshold': 50000, 'percent': 7}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label_ru'], 'Уровень 1 · Скидка')
        self.assertEqual(rows[0]['after_ru'], '7%')
