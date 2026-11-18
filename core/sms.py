"""SMS delivery boundary. A production transport requires an explicitly chosen provider."""
from django.conf import settings
from django.utils.module_loading import import_string
class SMSUnavailable(Exception):pass
class DisabledBackend:
 def send_code(self,phone,code):raise SMSUnavailable('SMS-провайдер не подключён. Подтверждение телефона временно недоступно. / SMS қызметі қосылмаған.')
class MemoryBackend:
 """Test transport; never selectable outside Django test overrides."""
 outbox=[]
 def send_code(self,phone,code):self.outbox.append({'phone':phone,'code':code})
def deliver_code(phone,code):
 backend=getattr(settings,'SMS_BACKEND','disabled')
 if backend=='disabled':transport=DisabledBackend()
 elif backend=='memory':
  if not getattr(settings,'SMS_TEST_TRANSPORT_ALLOWED',False):raise SMSUnavailable('Тестовая SMS-доставка отключена')
  transport=MemoryBackend()
 else:
  # A provider adapter must be implemented and explicitly configured server-side.
  try:transport=import_string(backend)()
  except Exception:raise SMSUnavailable('SMS-сервис не настроен. Обратитесь к администратору.') from None
 try:transport.send_code(phone,code)
 except SMSUnavailable:raise
 except Exception:raise SMSUnavailable('SMS-сервис временно недоступен. Повторите позже.') from None
