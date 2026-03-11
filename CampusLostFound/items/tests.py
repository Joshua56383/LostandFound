from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from .models import Item, UserLoginLog, ClaimRequest
from .forms import ItemForm

class ItemModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser_model', password='password123')
        self.item = Item.objects.create(
            name='Test Item',
            description='Test Description',
            location='Test Location',
            status='lost',
            owner=self.user,
            is_approved=True
        )

    def test_item_creation(self):
        self.assertEqual(self.item.name, 'Test Item')
        self.assertEqual(str(self.item), 'Test Item')
        self.assertEqual(self.item.status, 'lost')
        self.assertTrue(self.item.is_approved)

class DashboardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='admin_user', password='password123', is_staff=True)
        self.item = Item.objects.create(
            name='Dashboard Item',
            description='Test',
            location='Test',
            status='lost',
            owner=self.user,
            is_approved=True
        )

    def test_dashboard_view_authenticated(self):
        self.client.login(username='admin_user', password='password123')
        response = self.client.get(reverse('items:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'items/dashboard.html')

    def test_dashboard_view_unauthenticated(self):
        response = self.client.get(reverse('items:dashboard'))
        self.assertRedirects(response, '/accounts/login/?next=/dashboard/')

class ItemViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='regular_user', password='password123')
        self.item = Item.objects.create(
            name='Public Item',
            description='Visible',
            location='Here',
            status='found',
            owner=self.user,
            is_approved=True
        )
        self.pending_item = Item.objects.create(
            name='Secret Item',
            description='Hidden',
            location='Somewhere',
            status='lost',
            owner=self.user,
            is_approved=False
        )

    def test_item_list_view_filters_approved(self):
        response = self.client.get(reverse('items:item_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Item')
        self.assertNotContains(response, 'Secret Item')

    def test_item_detail_view(self):
        response = self.client.get(reverse('items:item_detail', args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Item')

    def test_add_item_submission_unapproved(self):
        self.client.login(username='regular_user', password='password123')
        data = {
            'name': 'New Unapproved',
            'description': 'Description',
            'location': 'Library',
            'status': 'lost',
            'category': 'Electronics',
        }
        response = self.client.post(reverse('items:add_item'), data)
        self.assertRedirects(response, reverse('items:item_list'))
        item = Item.objects.get(name='New Unapproved')
        self.assertFalse(item.is_approved)

    def test_login_creates_log(self):
        self.client.login(username='regular_user', password='password123')
        self.assertTrue(UserLoginLog.objects.filter(user=self.user).exists())

class AdminApprovalWorkflowTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin_staff', password='password123', is_staff=True)
        self.user = User.objects.create_user(username='requester', password='password123')
        self.item = Item.objects.create(
            name='Pending Item',
            description='Wait',
            location='Desk',
            status='lost',
            owner=self.user,
            is_approved=False
        )

    def test_approve_item_workflow(self):
        self.client.login(username='admin_staff', password='password123')
        response = self.client.get(reverse('items:approve_item', args=[self.item.id]))
        self.assertRedirects(response, reverse('items:dashboard'))
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_approved)

    def test_reject_item_workflow(self):
        self.client.login(username='admin_staff', password='password123')
        response = self.client.get(reverse('items:reject_item', args=[self.item.id]))
        self.assertRedirects(response, reverse('items:dashboard'))
        self.assertFalse(Item.objects.filter(id=self.item.id).exists())

    def test_approve_non_existent_item_redirects(self):
        self.client.login(username='admin_staff', password='password123')
        response = self.client.get(reverse('items:approve_item', args=[9999]))
        self.assertRedirects(response, reverse('items:dashboard'))
        # Check that an info message was sent
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("already processed" in str(m) for m in messages))

    def test_reject_non_existent_item_redirects(self):
        self.client.login(username='admin_staff', password='password123')
        # Use an ID that definitely doesn't exist
        response = self.client.get(reverse('items:reject_item', args=[8888]))
        self.assertRedirects(response, reverse('items:dashboard'))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any("already rejected" in str(m) for m in messages))

class NotificationMatchTest(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username='user_a_notif', password='password123')
        self.user_b = User.objects.create_user(username='user_b_notif', password='password123')
        self.admin = User.objects.create_superuser(username='admin_notif', password='password123', email='admin_notif@test.com')

    def test_matching_notifications(self):
        # 1. User A reports a lost "Black Wallet"
        self.client.login(username='user_a_notif', password='password123')
        response = self.client.post(reverse('items:report_item', args=['lost']), {
            'name': 'Black Wallet',
            'description': 'Leather wallet with ID',
            'category': 'Accessories',
            'location': 'Library',
            'status': 'lost',
            'contact_name': 'User A',
            'contact_email': 'a@test.com'
        })
        self.assertEqual(response.status_code, 302) # Should redirect
        
        # User A should have 1 notification (Received)
        self.assertEqual(self.user_a.notifications.all().count(), 1)
        
        # 2. Admin approves User A's item
        item_a = Item.objects.get(name='Black Wallet')
        self.client.login(username='admin_notif', password='password123')
        self.client.get(reverse('items:approve_item', args=[item_a.id]))
        
        # 3. User B reports a found "Black Wallet"
        self.client.login(username='user_b_notif', password='password123')
        self.client.post(reverse('items:report_item', args=['found']), {
            'name': 'Black Wallet',
            'description': 'Found a black leather wallet',
            'category': 'Accessories',
            'location': 'Library',
            'status': 'found',
            'contact_name': 'User B',
            'contact_email': 'b@test.com'
        })
        
        # User B should have 2 notifications: 1 Received, 1 Match
        self.assertEqual(self.user_b.notifications.all().count(), 2)
        self.assertTrue(self.user_b.notifications.filter(status_trigger='match_detected').exists())
        
        # User A should NOT have a match notification yet because User B is unapproved.
        self.assertEqual(self.user_a.notifications.filter(status_trigger='match_detected').count(), 0)
        
        # 4. Admin approves User B's item
        item_b = Item.objects.get(owner=self.user_b)
        self.client.login(username='admin_notif', password='password123')
        self.client.get(reverse('items:approve_item', args=[item_b.id]))
        
        # Now User A should have a match notification!
        self.assertTrue(self.user_a.notifications.filter(status_trigger='match_detected').exists())

class ClaimWorkflowTest(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username='user_a_claim', password='password123')
        self.user_b = User.objects.create_user(username='user_b_claim', password='password123')
        self.admin = User.objects.create_superuser(username='admin_claim', password='password123')
        
        # User A finds a "Gold Ring"
        self.item = Item.objects.create(
            name='Gold Ring',
            description='Found at the park',
            category='Jewelry',
            location='Park',
            status='found',
            owner=self.user_a,
            is_approved=True
        )

    def test_claim_submission_and_approval(self):
        # 1. User B submits a claim
        self.client.login(username='user_b_claim', password='password123')
        response = self.client.post(reverse('items:submit_claim', args=[self.item.id]), {
            'message': 'I lost my gold ring yesterday at the park.'
        })
        self.assertEqual(response.status_code, 302)
        
        claim = ClaimRequest.objects.get(item=self.item, claimer=self.user_b)
        self.assertEqual(claim.status, 'pending')
        
        # 2. User A (finder) approves the claim
        self.client.login(username='user_a_claim', password='password123')
        self.client.get(reverse('items:approve_claim', args=[claim.id]))
        
        # Verify status updates
        claim.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(claim.status, 'approved')
        self.assertEqual(self.item.status, 'claimed')
        
        # Verify notification to claimer
        self.assertTrue(self.user_b.notifications.filter(status_trigger='claim_approved').exists())

    def test_staff_item_auto_approved(self):
        self.client.login(username='admin_claim', password='password123')
        data = {
            'name': 'Staff Item',
            'description': 'Direct',
            'location': 'Office',
            'status': 'found',
            'category': 'Other',
            'contact_name': 'Staff',
            'contact_email': 'staff@test.com'
        }
        self.client.post(reverse('items:report_item', args=['found']), data)
        item = Item.objects.get(name='Staff Item')
        self.assertTrue(item.is_approved)

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
            'name': '', 
            'description': 'Valid Description',
        }
        form = ItemForm(data=data)
        self.assertFalse(form.is_valid())
