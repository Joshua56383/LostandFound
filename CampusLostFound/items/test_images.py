from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from items import models
import os
from django.conf import settings

class ImageVisibilityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='student', password='password')
        self.admin = User.objects.create_superuser(username='admin', password='password')
        
        # Create a test image
        self.test_image = SimpleUploadedFile(
            name='test_image.jpg',
            content=b'\x00\x01\x02\x03',
            content_type='image/jpeg'
        )
        
        # Create an item
        self.item = models.Item.objects.create(
            name='Lost Wallet',
            description='Brown leather wallet',
            category='Accessories',
            location='Library',
            status='lost',
            owner=self.user,
            image=self.test_image,
            is_approved=False
        )

    def test_image_visibility_logic(self):
        image_url = self.item.image.url
        
        # 1. Unauthenticated user should NOT be able to see unapproved item image
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 403, "Unauthenticated user should be denied access to unapproved item image")
        
        # 2. Owner SHOULD be able to see their own unapproved item image
        self.client.login(username='student', password='password')
        response = self.client.get(image_url)
        if response.status_code != 200:
            print(f"DEBUG: URL={image_url}")
            print(f"DEBUG: Item Owner={self.item.owner}")
            print(f"DEBUG: Client User={self.user}")
            print(f"DEBUG: Response Content={response.content.decode()}")
        self.assertEqual(response.status_code, 200, "Owner should have access to their own unapproved item image")
        self.client.logout()
        
        # 3. Admin SHOULD be able to see unapproved item image
        self.client.login(username='admin', password='password')
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200, "Admin should have access to unapproved item image")
        self.client.logout()
        
        # 4. Approve the item
        self.item.is_approved = True
        self.item.save()
        
        # 5. Unauthenticated user SHOULD now be able to see the approved item image
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200, "Unauthenticated user should have access to approved item image")
        # Close responses that use files on Windows
        response.close()
        
        # Cleanup
        if self.item.image and os.path.exists(self.item.image.path):
            try:
                os.remove(self.item.image.path)
            except PermissionError:
                pass # Already closed or still in use
