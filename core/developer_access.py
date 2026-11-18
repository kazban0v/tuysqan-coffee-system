from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from .models import DeveloperAccess

def is_developer(user):
    if not user or not user.is_authenticated or not user.is_active:return False
    if not hasattr(user,'_private_developer_access'):
        user._private_developer_access=DeveloperAccess.objects.filter(user_id=user.pk).exists()
    return user._private_developer_access

def developer_only(view):
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        if not request.user.is_authenticated:return redirect('/developer/login/')
        if not is_developer(request.user):raise PermissionDenied('Раздел недоступен')
        response=view(request,*args,**kwargs)
        response['Cache-Control']='private, no-store'
        response['X-Robots-Tag']='noindex, nofollow'
        return response
    return wrapped
