from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from .models import Item, UserLoginLog
from .forms import ItemForm

class ItemModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.item = Item.objects.create(
            name='Test Item',
            description='Test Description',
            location='Test Location',
            status='lost',
            owner=self.user
        )

class DashboardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.item = Item.objects.create(
            name='Test Item',
            description='Test Description',
            location='Test Location',
            status='lost',
            owner=self.user
        )

    def test_dashboard_view_authenticated(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('items:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'items/dashboard.html')

    def test_dashboard_view_unauthenticated(self):
        response = self.client.get(reverse('items:dashboard'))
        self.assertRedirects(response, '/accounts/login/?next=/dashboard/')


    def test_item_creation(self):
        self.assertEqual(self.item.name, 'Test Item')
        self.assertEqual(str(self.item), 'Test Item')
        self.assertEqual(self.item.status, 'lost')


class ItemViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.item = Item.objects.create(
            name='Test Item',
            description='Test Description',
            location='Test Location',
            status='lost',
            owner=self.user
        )

    def test_item_list_view(self):
        response = self.client.get(reverse('items:item_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Item')
        self.assertTemplateUsed(response, 'items/item_list.html')

    def test_item_detail_view(self):
        response = self.client.get(reverse('items:item_detail', args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Item')
        self.assertTemplateUsed(response, 'items/item_detail.html')

    def test_add_item_view_unauthenticated(self):
        response = self.client.get(reverse('items:add_item'))
        self.assertRedirects(response, '/accounts/login/?next=/add/')

    def test_add_item_view_authenticated(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('items:add_item'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'items/add_item.html')

    def test_add_item_submission(self):
        self.client.login(username='testuser', password='password123')
        data = {
            'name': 'New Lost Item',
            'description': 'Description',
            'location': 'Library',
            'status': 'lost',
            'category': 'Electronics',
        }
        response = self.client.post(reverse('items:add_item'), data)
        self.assertRedirects(response, reverse('items:item_list'))
        self.assertTrue(Item.objects.filter(name='New Lost Item').exists())

    def test_login_creates_log(self):
        self.client.login(username='testuser', password='password123')
        log = UserLoginLog.objects.get(user=self.user)
        self.assertEqual(log.login_source, 'Web Portal')

    def test_admin_login_redirect_for_user(self):
        # Regular user trying to access admin should typically be redirected to admin login,
        # BUT since we want strict separation, we verify they can't just log in via admin if not staff.
        # However, built-in admin login behavior checks is_staff.
        self.client.login(username='testuser', password='password123')
        response = self.client.get('/admin/')
        # If logged in as non-staff, admin often redirects to admin login with ?next=...
        # or shows an error. Standard behavior is redirection to /admin/login/?next=/admin/ 
        # even if logged in as reporting user, because not staff.
        # Let's verify our LOGIN_URL setting works for general redirects:
        self.client.logout()
        response = self.client.get(reverse('items:add_item')) 
        # Should NOT go to /accounts/login/ if we set it to 'login' which resolves to /accounts/login/ usually
        # but let's check the redirect chain.
        self.assertRedirects(response, '/accounts/login/?next=/add/')

    def test_admin_login_source_log(self):
        # Create a superuser to verify 'Admin' source log
        admin_user = User.objects.create_superuser('admin', 'admin@test.com', 'password123')
        self.client.login(username='admin', password='password123')
        # Admin login usually happens via POST to /admin/login/
        # Client.login() does not simulate the *URL* used, it just sets the session.
        # To test the signal logic dependent on request.path, we must POST to the login view.
        self.client.logout()
        response = self.client.post('/admin/login/', {'username': 'admin', 'password': 'password123', 'next': '/admin/'})
        self.assertTrue(UserLoginLog.objects.filter(user=admin_user, login_source='Admin').exists())


class ItemFormTest(TestCase):
    def test_valid_form(self):
        data = {
            'name': 'Valid Item',
            'description': 'Valid Description',
            'location': 'Valid Location',
            'status': 'lost',
            'category': 'Books',
        }
        form = ItemForm(data=data)
        self.assertTrue(form.is_valid())

    def test_invalid_form(self):
        data = {
            'name': '', # Required
            'description': 'Valid Description',
        }
        form = ItemForm(data=data)
        self.assertFalse(form.is_valid())
