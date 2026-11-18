import json
from django.contrib.auth.models import User,Group
from django.test import TestCase,Client
from .models import MenuCategory,MenuItem
from .menu_compositions import pos_composition

class PosCompositionTests(TestCase):
 def setUp(self):
  self.user=User.objects.create_user('composition-cashier')
  self.user.groups.add(Group.objects.create(name='cashier'))
  self.client.force_login(self.user)
  category=MenuCategory.objects.create(slug='composition-fixture',name_ru='Меню',name_kz='Мәзір')
  self.product=MenuItem.objects.create(category=category,slug='tuysqan-breakfast',name_ru='Tuysqan',name_kz='Tuysqan',price=4210,is_test=False)
 def catalog(self):
  response=self.client.get('/admin/pos/')
  self.assertEqual(response.status_code,200)
  return response.context['menu_data']
 def test_photo_description_is_matched_without_replacing_price(self):
  item=self.catalog()[0]
  self.assertEqual(item['price'],'4210.00')
  self.assertEqual(item['composition']['status'],'matched')
  self.assertIn('колбаски, кукуруза',item['composition']['ru'])
  self.assertNotIn('говядины',item['composition']['ru'])
  self.assertIn('шұжықтар',item['composition']['kz'])
 def test_unconfirmed_tortilla_does_not_present_existing_text_as_confirmed(self):
  item=pos_composition({'slug':'mexican-tortilla','name_ru':'Тортилья по-мексикански'})
  self.assertEqual(item,{'status':'missing'})
 def test_chicken_burger_conflict_does_not_show_beef_ingredients(self):
  result=pos_composition({'slug':'chicken-burger','name_ru':'Бургер с курицей'})
  self.assertEqual(result['status'],'conflict');self.assertNotIn('ru',result)
  self.assertIn('уточнить',result['note_ru'])
 def test_renamed_product_does_not_inherit_composition_by_reused_slug(self):
  self.product.name_ru='Совсем другое блюдо';self.product.save(update_fields=['name_ru'])
  self.assertEqual(self.catalog()[0]['composition'],{'status':'missing'})
 def test_pos_remains_staff_only(self):
  self.assertNotEqual(Client().get('/admin/pos/').status_code,200)
