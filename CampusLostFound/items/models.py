from django.db import models
from django.contrib.auth.models import User

class Item(models.Model):
    STATUS_CHOICES = [
        ('lost', 'Lost'),
        ('found', 'Found'),
        ('claimed', 'Claimed'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField()
    category = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    contact_name = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)
    image = models.ImageField(upload_to='items/', blank=True, null=True)
    date_reported = models.DateField(auto_now_add=True)
    is_approved = models.BooleanField(default=False)


    def __str__(self):
        return self.name


class UserLoginLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    login_source = models.CharField(max_length=50, default='Web')
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} logged in at {self.timestamp} via {self.login_source}"


class UserProfile(models.Model):
    USER_TYPE_CHOICES = [
        ('student', 'Student'),
        ('staff', 'Staff'),
        ('admin', 'Admin'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    student_staff_id = models.CharField(max_length=20, blank=True, verbose_name="Student/Staff ID")
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='student')
    
    def __str__(self):
        return self.user.username


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    related_item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    status_trigger = models.CharField(max_length=50)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.recipient.username}: {self.message[:30]}..."

    class Meta:
        ordering = ['-created_at']

class ClaimRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='claims')
    claimer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='claims_made')
    message = models.TextField(help_text="Provide proof of ownership or additional details.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Claim for {self.item.name} by {self.claimer.username}"

    class Meta:
        ordering = ['-created_at']
