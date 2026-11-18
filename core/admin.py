from django.contrib import admin
from .models import *
class ProtectedAdmin(admin.ModelAdmin):
 def has_delete_permission(self,request,obj=None):return False
 def has_add_permission(self,request):return False
 def has_change_permission(self,request,obj=None):return False
for model in [Order,OrderItem,Payment,AuditEvent,LoyaltyEntry,Customer,Review,OutboxMessage,OTPChallenge]:admin.site.register(model,ProtectedAdmin)
for model in [MenuCategory,MenuItem,Table,AppSettings]:admin.site.register(model)
admin.site.register(LoyaltyPolicy,ProtectedAdmin)

# Keep changes made through the technical Django editor visible in the same owner journal.
class AuditedMenuAdmin(admin.ModelAdmin):
 def save_model(self,request,obj,form,change):
  from .services import audit
  from .admin_portal import menu_snapshot
  before=menu_snapshot(MenuItem.objects.get(pk=obj.pk)) if change else {}
  super().save_model(request,obj,form,change)
  audit('menu_item_updated' if change else 'menu_item_created',request.user,before=before,after=menu_snapshot(obj))
 def has_delete_permission(self,request,obj=None):return False

class AuditedCategoryAdmin(admin.ModelAdmin):
 def save_model(self,request,obj,form,change):
  from .services import audit
  before={}
  if change:
   old=MenuCategory.objects.get(pk=obj.pk);before={'id':old.pk,'name_ru':old.name_ru,'name_kz':old.name_kz,'sort_order':old.sort_order}
  super().save_model(request,obj,form,change)
  audit('category_updated' if change else 'category_created',request.user,before=before,after={'id':obj.pk,'name_ru':obj.name_ru,'name_kz':obj.name_kz,'sort_order':obj.sort_order})
 def has_delete_permission(self,request,obj=None):return False

admin.site.unregister(MenuItem);admin.site.register(MenuItem,AuditedMenuAdmin)
admin.site.unregister(MenuCategory);admin.site.register(MenuCategory,AuditedCategoryAdmin)
admin.site.register(FeedbackHandling,ProtectedAdmin)

# Operational/technical administrators cannot enumerate or edit private developer users.
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from .models import DeveloperAccess
class PrivateUserAdmin(UserAdmin):
 def get_queryset(self,request):
  return super().get_queryset(request).exclude(pk__in=DeveloperAccess.objects.exclude(user_id=request.user.pk).values('user_id'))
 def has_change_permission(self,request,obj=None):
  if obj and obj.pk!=request.user.pk and DeveloperAccess.objects.filter(user_id=obj.pk).exists():return False
  return super().has_change_permission(request,obj)
 def has_delete_permission(self,request,obj=None):
  if obj and DeveloperAccess.objects.filter(user_id=obj.pk).exists():return False
  return super().has_delete_permission(request,obj)
UserModel=get_user_model()
admin.site.unregister(UserModel)
admin.site.register(UserModel,PrivateUserAdmin)
