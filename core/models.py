import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core import signing

class MenuCategory(models.Model):
    slug=models.SlugField(unique=True)
    name_ru=models.CharField(max_length=180)
    name_kz=models.CharField(max_length=180)
    sort_order=models.PositiveIntegerField(default=0)
    class Meta: ordering=['sort_order','id']
    def __str__(self): return self.name_ru

class MenuItem(models.Model):
    KINDS=[('food','Блюдо'),('drink','Напиток')]
    category=models.ForeignKey(MenuCategory,on_delete=models.PROTECT,related_name='items')
    slug=models.SlugField(unique=True)
    name_ru=models.CharField(max_length=240)
    name_kz=models.CharField(max_length=240)
    description_ru=models.TextField(blank=True)
    description_kz=models.TextField(blank=True)
    kind=models.CharField(max_length=5,choices=KINDS,default='food')
    price=models.DecimalField(max_digits=10,decimal_places=2)
    available=models.BooleanField(default=True)
    image=models.CharField(max_length=300,blank=True)
    modifiers=models.JSONField(default=list,blank=True)
    source=models.CharField(max_length=240,blank=True)
    uncertainties=models.JSONField(default=list,blank=True)
    is_test=models.BooleanField(default=False)
    data_confirmed=models.BooleanField(default=False)
    class Meta:
        ordering=['category__sort_order','id']
        constraints=[models.CheckConstraint(condition=models.Q(price__gte=0),name='menu_nonnegative_price')]
    def __str__(self): return self.name_ru

class Table(models.Model):
    code=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    name=models.CharField(max_length=80)
    active=models.BooleanField(default=True)
    is_test=models.BooleanField(default=False)
    def token(self): return signing.Signer(salt='tuysqan-table-v1').sign(str(self.code))
    def __str__(self): return self.name

class Customer(models.Model):
    name=models.CharField(max_length=120)
    phone=models.CharField(max_length=20,unique=True)
    phone_verified_at=models.DateTimeField(null=True,blank=True)
    consent_at=models.DateTimeField()
    marketing_consent=models.BooleanField(default=False)
    marketing_consent_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    is_test=models.BooleanField(default=True)
    @property
    def loyalty_total(self):
        return self.loyalty_entries.aggregate(n=models.Sum('amount'))['n'] or Decimal('0')
    @property
    def last_purchase(self):
        return self.orders.filter(payment_status='paid',is_test=False).order_by('-paid_at').values_list('paid_at',flat=True).first()
    @property
    def discount_percent(self):
        policy=LoyaltyPolicy.get()
        if not policy.confirmed: return 0
        tiers=self.available_loyalty_tiers
        return int(tiers[0]['percent']) if tiers else 0
    @property
    def available_loyalty_tiers(self):
        policy=LoyaltyPolicy.get()
        if not policy.confirmed:return []
        total=self.loyalty_total
        reserved=set(self.loyalty_redemptions.filter(active=True).values_list('threshold',flat=True))
        return sorted([t for t in policy.tiers if total>=Decimal(str(t['threshold'])) and Decimal(str(t['threshold'])) not in reserved],key=lambda t:Decimal(str(t['threshold'])),reverse=True)
    def __str__(self): return self.name

class OTPChallenge(models.Model):
    phone=models.CharField(max_length=20)
    session_key=models.CharField(max_length=64)
    code_hash=models.CharField(max_length=128)
    name=models.CharField(max_length=120)
    consent=models.BooleanField(default=False)
    marketing=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    expires_at=models.DateTimeField()
    attempts=models.PositiveSmallIntegerField(default=0)
    consumed_at=models.DateTimeField(null=True)
    class Meta: indexes=[models.Index(fields=['phone','session_key','created_at'])]

class Order(models.Model):
    STATUSES=[('new','Новый'),('accepted','Принят'),('preparing','Готовится'),('ready','Готов'),('served','Выдан'),('rejected','Отклонён'),('cancelled','Отменён')]
    PAYMENT_METHODS=[('cash','Наличные'),('kaspi','Kaspi QR'),('halyk','Halyk')]
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='orders')
    table=models.ForeignKey(Table,on_delete=models.PROTECT,related_name='orders',null=True)
    customer_identity_verified=models.BooleanField(default=False,editable=False)
    idempotency_key=models.CharField(max_length=100)
    payload_hash=models.CharField(max_length=64)
    status=models.CharField(max_length=12,choices=STATUSES,default='new')
    payment_status=models.CharField(max_length=12,choices=[('unpaid','Не оплачен'),('paid','Оплачен'),('refunded','Возвращён')],default='unpaid')
    payment_method=models.CharField(max_length=10,choices=PAYMENT_METHODS)
    drink_preference=models.CharField(max_length=12,choices=[('','Не требуется'),('immediately','Сразу'),('with_food','Вместе с блюдами')],blank=True)
    comment=models.TextField(blank=True)
    subtotal=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    discount_choice=models.CharField(max_length=16,choices=[('legacy','Ранее оформлен'),('applied','Применена'),('declined','Без скидки'),('not_available','Недоступна')],default='legacy')
    discount_offer_percent=models.PositiveSmallIntegerField(default=0)
    discount_source=models.CharField(max_length=24,blank=True,default='')
    residential_complex=models.CharField(max_length=24,blank=True,default='')
    loyalty_eligible=models.BooleanField(default=False,editable=False)
    discount_percent=models.PositiveSmallIntegerField(default=0)
    discount_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    total=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    actual_paid=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    is_test=models.BooleanField(default=True)
    source=models.CharField(max_length=10,default='web')
    created_at=models.DateTimeField(auto_now_add=True)
    accepted_at=models.DateTimeField(null=True,blank=True)
    eta_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    eta_at=models.DateTimeField(null=True,blank=True)
    food_eta_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    food_eta_at=models.DateTimeField(null=True,blank=True)
    drink_eta_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    drink_eta_at=models.DateTimeField(null=True,blank=True)
    drink_started_at=models.DateTimeField(null=True,blank=True)
    drink_food_eta_at_start=models.DateTimeField(null=True,blank=True)
    drink_notice_seen_token=models.CharField(max_length=64,blank=True)
    ready_at=models.DateTimeField(null=True,blank=True)
    served_at=models.DateTimeField(null=True,blank=True)
    mascot_dismissed_at=models.DateTimeField(null=True,blank=True)
    guest_wish=models.TextField(blank=True,max_length=1000)
    guest_wish_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    was_delayed=models.BooleanField(default=False)
    delay_notified_at=models.DateTimeField(null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)
    version=models.PositiveIntegerField(default=0)
    class Meta:
        ordering=['-created_at']
        constraints=[models.UniqueConstraint(fields=['customer','idempotency_key'],name='order_customer_idempotency'),models.UniqueConstraint(fields=['idempotency_key'],condition=models.Q(source='pos'),name='unique_pos_idempotency_key'),models.CheckConstraint(condition=models.Q(total__gte=0),name='order_nonnegative_total')]
    @property
    def number(self): return f'T{self.pk:04d}'
    @property
    def is_delayed(self):
        if self.status not in ['accepted','preparing']:return False
        now=timezone.now()
        if self.food_eta_at or self.drink_eta_at:
            return any(deadline and deadline<now and self.items.filter(kind=kind).exclude(status='ready').exists() for kind,deadline in [('food',self.food_eta_at),('drink',self.drink_eta_at)])
        return bool(self.eta_at and self.eta_at<now)
    @property
    def food_items(self): return self.items.filter(kind='food')
    @property
    def drink_items(self): return self.items.filter(kind='drink')
    @property
    def preparation_minutes(self): return round((self.ready_at-self.accepted_at).total_seconds()/60,1) if self.ready_at and self.accepted_at else None
    def __str__(self): return self.number

class OrderItem(models.Model):
    order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name='items')
    menu_item=models.ForeignKey(MenuItem,on_delete=models.PROTECT)
    name_ru=models.CharField(max_length=240)
    name_kz=models.CharField(max_length=240)
    kind=models.CharField(max_length=5,choices=MenuItem.KINDS)
    unit_price=models.DecimalField(max_digits=10,decimal_places=2)
    quantity=models.PositiveSmallIntegerField()
    comment=models.CharField(max_length=500,blank=True)
    status=models.CharField(max_length=12,choices=[('pending','Ожидает'),('preparing','Готовится'),('ready','Готов')],default='pending')
    eta_minutes=models.PositiveSmallIntegerField(null=True,blank=True)
    eta_at=models.DateTimeField(null=True,blank=True)
    @property
    def line_total(self): return self.unit_price*self.quantity

class Payment(models.Model):
    order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name='payments')
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    method=models.CharField(max_length=10,choices=Order.PAYMENT_METHODS)
    confirmed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    idempotency_key=models.CharField(max_length=100,unique=True)
    reason=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    reversed_at=models.DateTimeField(null=True,blank=True)
    reversal_reason=models.TextField(blank=True)

class AuditEvent(models.Model):
    order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name='events',null=True,blank=True)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True)
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,null=True,blank=True)
    action=models.CharField(max_length=80)
    channel=models.CharField(max_length=20,default='web')
    reason=models.TextField(blank=True)
    before=models.JSONField(default=dict)
    after=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at']

class LoyaltyPolicy(models.Model):
    confirmed=models.BooleanField(default=False)
    tiers=models.JSONField(default=list)
    threshold_order_rule=models.CharField(max_length=50,default='pending')
    accumulation_basis=models.CharField(max_length=50,default='pending')
    refund_rule=models.CharField(max_length=50,default='pending')
    inactivity_rule=models.CharField(max_length=50,default='pending')
    promotions_rule=models.CharField(max_length=50,default='pending')
    @classmethod
    def get(cls): return cls.objects.get_or_create(pk=1,defaults={'tiers':[{'threshold':50000,'percent':5},{'threshold':100000,'percent':7},{'threshold':150000,'percent':10},{'threshold':250000,'percent':12},{'threshold':500000,'percent':15}]})[0]

class LoyaltyEntry(models.Model):
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='loyalty_entries')
    order=models.ForeignKey(Order,on_delete=models.PROTECT)
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    kind=models.CharField(max_length=12,choices=[('purchase','Покупка'),('reversal','Сторно')])
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['payment','kind'],name='loyalty_payment_once')]

class Review(models.Model):
    order=models.OneToOneField(Order,on_delete=models.PROTECT,related_name='review')
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='reviews')
    kind=models.CharField(max_length=12,choices=[('service','Обслуживание'),('experience','Впечатление')],default='experience')
    rating=models.PositiveSmallIntegerField()
    comment=models.TextField(blank=True)
    status=models.CharField(max_length=12,choices=[('new','Новый'),('viewed','Просмотрен'),('handled','Обработан')],default='new')
    staff_note=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']
        constraints=[models.CheckConstraint(condition=models.Q(rating__gte=1,rating__lte=5),name='review_rating_range')]

class AppSettings(models.Model):
    kitchen_release=models.CharField(max_length=12,choices=[('acceptance','После принятия — демо'),('payment','После оплаты — демо')],default='acceptance')
    payment_instructions=models.JSONField(default=dict)
    telegram_mode=models.CharField(max_length=12,default='local_outbox',editable=False)
    @classmethod
    def get(cls): return cls.objects.get_or_create(pk=1)[0]

class OutboxMessage(models.Model):
    order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name='notifications')
    kind=models.CharField(max_length=20,default='new_order')
    payload=models.JSONField(default=dict)
    status=models.CharField(max_length=20,default='local_only')
    created_at=models.DateTimeField(auto_now_add=True)
    last_error=models.TextField(blank=True)
    class Meta: ordering=['-created_at']


class FeedbackHandling(models.Model):
    """Staff workflow for a guest review or wish; never edits the guest's text."""
    order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name='feedback_handling')
    kind=models.CharField(max_length=10,choices=[('review','Отзыв'),('wish','Пожелание')])
    status=models.CharField(max_length=10,choices=[('new','Новый'),('viewed','Просмотрен'),('handled','Обработан')],default='new')
    note=models.TextField(blank=True)
    handled_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='handled_guest_feedback')
    handled_at=models.DateTimeField(null=True,blank=True)
    updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='updated_guest_feedback')
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['order','kind'],name='feedback_order_kind_once')]

class DeveloperAccess(models.Model):
    """Explicit private developer access, independent of owner/superuser status."""
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='developer_access')
    created_at=models.DateTimeField(auto_now_add=True)


class LoyaltyRedemption(models.Model):
    """Reserve one earned threshold atomically; paid uses remain spent after refunds."""
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='loyalty_redemptions')
    order=models.OneToOneField(Order,on_delete=models.PROTECT,related_name='loyalty_redemption')
    threshold=models.DecimalField(max_digits=12,decimal_places=2)
    percent=models.PositiveSmallIntegerField()
    active=models.BooleanField(default=True)
    consumed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['customer','threshold'],condition=models.Q(active=True),name='one_active_loyalty_threshold')]
