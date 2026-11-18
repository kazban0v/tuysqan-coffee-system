from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Customer, LoyaltyEntry, LoyaltyPolicy
from core import services


class Command(BaseCommand):
    help = 'Restore missing loyalty entries from confirmed payments for one phone (dry run by default).'

    def add_arguments(self, parser):
        parser.add_argument('--phone', required=True)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        phone = services.phone_normalize(options['phone'])
        customer = Customer.objects.select_for_update().filter(phone=phone).first()
        if not services.loyalty_phone_customer(customer):
            raise CommandError('Eligible phone account not found')
        if not LoyaltyPolicy.get().confirmed:
            raise CommandError('Loyalty program is inactive')
        count, amount, skipped = 0, Decimal('0'), 0
        orders = customer.orders.filter(payment_status='paid', is_test=False).exclude(status__in=['cancelled', 'rejected'])
        for order in orders:
            payments = list(order.payments.filter(reversed_at=None))
            # Never infer payment from an order flag alone, or repair inconsistent financial facts.
            if not payments or sum((p.amount for p in payments), Decimal('0')) != order.actual_paid:
                skipped += 1
                continue
            for payment in payments:
                if LoyaltyEntry.objects.filter(payment=payment, kind='purchase').exists():
                    continue
                count += 1
                amount += payment.amount
                if options['apply']:
                    entry, created = LoyaltyEntry.objects.get_or_create(
                        payment=payment, kind='purchase',
                        defaults={'customer':customer, 'order':order, 'amount':payment.amount},
                    )
                    if created:
                        services.audit('loyalty_reconciled', None, order,
                            reason='Restore confirmed phone purchases before unified loyalty',
                            after={'payment_id': payment.pk, 'amount':str(entry.amount)}, customer=customer)
        self.stdout.write(f"{'Applied' if options['apply'] else 'Dry run'}: {count} entries, {amount} KZT; inconsistent orders skipped: {skipped}")
