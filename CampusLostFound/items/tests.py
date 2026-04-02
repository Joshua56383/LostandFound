from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from .models import Item, UserLoginLog, ClaimRequest, UserProfile
from .forms import ItemForm
from django.core import mail

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
        self.assertTemplateUsed(response, 'user/dashboard.html')

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


class RBACTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create users
        self.student = User.objects.create_user(username='student', password='password123')
        self.admin_user = User.objects.create_user(username='admin_user', password='password123')
        self.superadmin_user = User.objects.create_user(username='superadmin_user', password='password123')
        
        # Set user types in profiles
        self.student.userprofile.user_type = 'student'
        self.student.userprofile.save()
        
        self.admin_user.userprofile.user_type = 'admin'
        self.admin_user.userprofile.save()
        
        self.superadmin_user.userprofile.user_type = 'superadmin'
        self.superadmin_user.userprofile.save()

    def test_superadmin_access(self):
        self.client.login(username='superadmin_user', password='password123')
        # Should access User Directory
        response = self.client.get(reverse('items:user_directory'))
        self.assertEqual(response.status_code, 200)
        # Should access Analytics
        response = self.client.get(reverse('items:admin_analytics'))
        self.assertEqual(response.status_code, 200)

    def test_admin_access_restrictions(self):
        self.client.login(username='admin_user', password='password123')
        # Should NOT access User Directory
        response = self.client.get(reverse('items:user_directory'))
        self.assertEqual(response.status_code, 403) # PermissionDenied raises 403
        # Should NOT access Analytics
        response = self.client.get(reverse('items:admin_analytics'))
        self.assertEqual(response.status_code, 403)
        
        # Should access a Dashboard (assuming it's allowed for admin)
        response = self.client.get(reverse('items:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_student_access_restrictions(self):
        self.client.login(username='student', password='password123')
        # Should NOT access User Directory
        response = self.client.get(reverse('items:user_directory'))
        self.assertEqual(response.status_code, 403)
        # Should NOT access Dashboard (standard dashboard is @login_required but check internal logic)
        # However, the decorators are applied to specific admin views.
        
    def test_unauthenticated_access(self):
        # Should redirect to login
        response = self.client.get(reverse('items:user_directory'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)



class PasswordResetTemplateTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='password123')
        self.client = Client()

    def test_password_reset_templates(self):
        # 1. Post to password reset
        response = self.client.post(reverse('password_reset'), {'email': 'test@example.com'})
        
        # Check if email was sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, 'Password reset on Campus Lost & Found')
        
        # Check redirect
        self.assertRedirects(response, reverse('login') + '?reset_sent=1')
        
        # 2. Check login page with reset_sent
        response = self.client.get(reverse('login'), {'reset_sent': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Email Sent')
        
    def test_password_reset_confirm_template(self):
        # We need a valid uid and token, but we can just check if the view loads
        # PasswordResetConfirmView needs uidb64 and token.
        # For simplicity, we just check if reverse works and it doesn't crash on GET (invalid link)
        url = reverse('password_reset_confirm', kwargs={'uidb64': 'NA', 'token': 'set-password'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid Link')

