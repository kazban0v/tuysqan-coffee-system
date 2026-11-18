"""Request-local batching for order lists; no cached payment or loyalty decisions."""
from collections import defaultdict
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from .models import OrderItem, Review, Payment, AuditEvent, LoyaltyEntry, Order, LoyaltyPolicy, LoyaltyRedemption


def prepare_order_list(query, include_customer=False):
    orders = list(query)
    if not orders:
        return orders
    ids = [order.pk for order in orders]
    items = defaultdict(list)
    for item in OrderItem.objects.filter(order_id__in=ids).select_related('menu_item'):
        items[item.order_id].append(item)
    reviewed = set(Review.objects.filter(order_id__in=ids).values_list('order_id', flat=True))
    now = timezone.now()
    for order in orders:
        deadlines = [(order.food_eta_at, 'food'), (order.drink_eta_at, 'drink')]
        order._display_is_delayed = order.status in ('accepted', 'preparing') and (any(at and at < now and any(item.kind == kind and item.status != 'ready' for item in items[order.pk]) for at, kind in deadlines) if any(at for at, kind in deadlines) else bool(order.eta_at and order.eta_at < now))
        order._display_items = items[order.pk]
        order._display_reviewed = order.pk in reviewed
    if not include_customer:
        return orders
    payments, events = defaultdict(list), defaultdict(list)
    for payment in Payment.objects.filter(order_id__in=ids).order_by('-created_at', '-pk'):
        payments[payment.order_id].append(payment)
    for event in AuditEvent.objects.filter(order_id__in=ids, action='payment_confirmed').order_by('-created_at', '-pk'):
        events[event.order_id].append(event)
    customer_ids = {order.customer_id for order in orders}
    ledger = dict(LoyaltyEntry.objects.filter(customer_id__in=customer_ids).values('customer_id').annotate(total=Sum('amount')).values_list('customer_id', 'total'))
    paid = dict(Order.objects.filter(customer_id__in=customer_ids, payment_status='paid', is_test=False).exclude(status__in=['cancelled', 'rejected']).values('customer_id').annotate(total=Sum('actual_paid')).values_list('customer_id', 'total'))
    used=defaultdict(set)
    for customer_id,threshold in LoyaltyRedemption.objects.filter(customer_id__in=customer_ids,active=True).values_list("customer_id","threshold"):
        used[customer_id].add(threshold)
    policy = LoyaltyPolicy.get()
    for order in orders:
        order._display_payments = payments[order.pk]
        order._display_payment_events = events[order.pk]
        order._display_available_percent=max([0]+[int(t["percent"]) for t in policy.tiers if policy.confirmed and Decimal(str(t["threshold"]))<=ledger.get(order.customer_id,0) and Decimal(str(t["threshold"])) not in used[order.customer_id]])
        order._display_loyalty = (policy, max(Decimal('0'), ledger.get(order.customer_id, 0)), max(Decimal('0'), paid.get(order.customer_id, 0)))
    return orders
