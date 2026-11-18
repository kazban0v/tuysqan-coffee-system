"""Image binding only; test database, no sales or image-generation API."""
from django.contrib.auth.models import User,Group
from django.test import TestCase
from .models import MenuCategory,MenuItem,Table

class FinalMenuPhotoTests(TestCase):
 def setUp(self):
  category=MenuCategory.objects.create(slug='photo-qa',name_ru='Фото QA',name_kz='Фото QA')
  self.item=MenuItem.objects.create(pk=56,category=category,slug='photo-sauce',name_ru='Грибной',name_kz='Саңырауқұлақ',description_ru='Состав',description_kz='Құрамы',price='590',image='/static/menu-final/id-56-approved.webp')
  self.other=MenuItem.objects.create(pk=9000,category=category,slug='photo-drink',name_ru='Другой',kind='drink',price='100',image='/static/unchanged.webp')
 def test_public_and_qr_have_exact_id_binding_and_same_image(self):
  public=self.client.get('/').context['menu_presentation']
  item=next(i for i in public if i['photo_id']==56)
  self.assertNotIn('id',item);self.assertTrue(item['photo_authoritative']);self.assertEqual(item['image'],self.item.image)
  self.assertFalse(next(i for i in public if i['photo_id']==9000)['photo_authoritative'])
  table=Table.objects.create(name='Photo QA')
  qr=self.client.get('/table/'+table.token()+'/').context['menu_data']
  self.assertEqual(next(i for i in qr if i['id']==56)['image'],item['image'])
 def test_admin_preview_and_save_without_upload_keep_image(self):
  user=User.objects.create_user('photo-review-owner');user.groups.add(Group.objects.get_or_create(name='owner')[0]);self.client.force_login(user)
  response=self.client.get('/admin/menu/?edit=56')
  self.assertContains(response,'data-menu-photo-id="56"');self.assertContains(response,self.item.image)
  data={field:getattr(self.item,field) for field in ['name_ru','name_kz','description_ru','description_kz','kind','price']}
  data.update(action='save',item_id=56,category=self.item.category_id,available='on')
  response=self.client.post('/admin/menu/',data);self.assertEqual(response.status_code,302)
  self.item.refresh_from_db();self.assertEqual(self.item.image,'/static/menu-final/id-56-approved.webp');self.assertEqual(str(self.item.price),'590.00')
 def test_pos_uses_same_authoritative_image(self):
  user=User.objects.create_user('photo-review-cashier');user.groups.add(Group.objects.get_or_create(name='cashier')[0]);self.client.force_login(user)
  response=self.client.get('/admin/pos/');self.assertEqual(response.status_code,200)
  self.assertEqual(next(i for i in response.context['menu_data'] if i['id']==56)['image'],self.item.image)
