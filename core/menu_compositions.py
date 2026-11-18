"""Photo-backed POS descriptions; independent of prices and historical orders."""
import json
from functools import lru_cache
from django.conf import settings

@lru_cache(maxsize=1)
def confirmed_compositions():
    path=settings.BASE_DIR/'data/menu/confirmed-compositions.json'
    return json.loads(path.read_text(encoding='utf-8'))['items']

def pos_composition(item):
    record=confirmed_compositions().get(item['slug'])
    # An administrator may reuse a slug while changing the product itself.
    if not record or record['catalog_name_ru'].strip().casefold()!=item['name_ru'].strip().casefold():
        return {'status':'missing'}
    return {key:record[key] for key in ('status','ru','kz','note_ru','note_kz') if key in record}
