from .services import role_of
from .models import Customer,DeveloperAccess

def common(request):
 private_ids=set(DeveloperAccess.objects.values_list('user_id',flat=True)) if request.user.is_authenticated else set()
 return {'private_developer_ids':private_ids,'is_developer':request.user.pk in private_ids,'language':request.session.get('language','ru'),'role':role_of(request.user),'customer':Customer.objects.filter(pk=request.session.get('customer_id'),phone_verified_at__isnull=False).exclude(phone__startswith='guest-').first()}
