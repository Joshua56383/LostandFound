from django.db import models
from django.contrib.auth.models import User
import os
import uuid
from datetime import timedelta
from django.utils import timezone

def get_role_upload_path(instance, filename):
    """
    Organize files into template/<role>/ with unique filenames.
    """
    user = None
    if hasattr(instance, 'user'): user = instance.user
    elif hasattr(instance, 'owner'): user = instance.owner
    elif hasattr(instance, 'uploader'): user = instance.uploader
    
    role = 'student'
    if user and hasattr(user, 'userprofile'):
        role = user.userprofile.user_type
        if role == 'staff': role = 'admin'
    
    # Ensure role is restricted to student, admin, superadmin
    if role not in ['student', 'admin', 'superadmin']:
        role = 'student'
        
    ext = filename.split('.')[-1]
    # Unique name with user ID and timestamp
    user_id = user.id if user else '0'
    unique_name = f"{user_id}_{int(timezone.now().timestamp())}_{uuid.uuid4().hex[:8]}.{ext}"
    
    return os.path.join('template', role, unique_name)

class UploadedFile(models.Model):
    file = models.FileField(upload_to=get_role_upload_path)
    uploader = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_files')
    role = models.CharField(max_length=20)
    upload_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file.name} by {self.uploader.username} ({self.role})"

class ActiveItemManager(models.Manager):
    """Default manager that excludes soft-deleted items."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Item(models.Model):
    STATUS_CHOICES = [
        ('lost', 'Lost'),
        ('found', 'Found'),
        ('claimed', 'Claimed'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField()
    category = models.CharField(max_length=100, blank=True, db_index=True)
    location = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, db_index=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    contact_name = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)
    image = models.ImageField(upload_to=get_role_upload_path, blank=True, null=True)
    date_reported = models.DateTimeField(auto_now_add=True, db_index=True)
    is_approved = models.BooleanField(default=False, db_index=True)

    # Soft delete
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Item expiry (auto-archive after 30 days)
    expires_at = models.DateTimeField(null=True, blank=True)

    # Resolution tracking
    date_resolved = models.DateTimeField(null=True, blank=True)

    # AI-generated image tags for smart matching
    ai_tags = models.TextField(blank=True, help_text="AI-extracted visual tags for matching")

    # Managers
    objects = ActiveItemManager()
    all_objects = models.Manager()  # Includes soft-deleted

    def save(self, *args, **kwargs):
        # Auto-set expires_at on first save
        if not self.pk and not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=30)
        # Track resolution date
        if self.status == 'claimed' and not self.date_resolved:
            self.date_resolved = timezone.now()
        super().save(*args, **kwargs)

    def soft_delete(self):
        """Mark item as deleted without removing from DB."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def restore(self):
        """Restore a soft-deleted item."""
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def renew(self, days=30):
        """Extend the expiry date by given days."""
        self.expires_at = timezone.now() + timedelta(days=days)
        self.save(update_fields=['expires_at'])

    @property
    def is_expired(self):
        if self.expires_at and self.status not in ('claimed', 'archived'):
            return timezone.now() > self.expires_at
        return False

    @property
    def days_until_expiry(self):
        if self.expires_at:
            delta = self.expires_at - timezone.now()
            return max(0, delta.days)
        return None

    def __str__(self):
        return self.name


class UserLoginLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    login_source = models.CharField(max_length=50, default='Web')

    def __str__(self):
        return f"{self.user.username} logged in at {self.timestamp} via {self.login_source}"


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    details = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username if self.user else 'System'} - {self.action} - {self.timestamp}"


class UserProfile(models.Model):
    USER_TYPE_CHOICES = [
        ('student', 'Student'),
        ('staff', 'Staff'),
        ('admin', 'Admin'),
        ('superadmin', 'Superadmin'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.ImageField(upload_to=get_role_upload_path, null=True, blank=True)
    student_staff_id = models.CharField(max_length=20, blank=True, verbose_name="Student/Staff ID")
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='student')
    
    @property
    def trust_score(self):
        """Dynamic trust score based on real user behavior (0-100)."""
        score = 30  # Base score for having an account

        # +30 for verified student/staff ID
        if self.student_staff_id:
            score += 30

        # +10 for having email on the User model
        if self.user.email:
            score += 10

        # +10 for account age > 30 days
        if self.user.date_joined and (timezone.now() - self.user.date_joined).days > 30:
            score += 10

        # +5 for having a profile photo
        if self.avatar:
            score += 5

        # +5 per successfully returned item (max +25)
        returned_count = Item.objects.filter(
            owner=self.user, status='claimed'
        ).count()
        score += min(returned_count * 5, 25)

        # -10 per rejected claim
        rejected_claims = ClaimRequest.objects.filter(
            claimer=self.user, status='rejected'
        ).count()
        score -= rejected_claims * 10

        # -5 per rejected item submission
        # (items that were rejected by admin are deleted, so we can't count them directly)

        return max(0, min(100, score))  # Clamp to 0-100

    @property
    def trust_level(self):
        """Human-readable trust level."""
        s = self.trust_score
        if s >= 80:
            return 'Excellent'
        elif s >= 60:
            return 'Good'
        elif s >= 40:
            return 'Fair'
        else:
            return 'New'

    @property
    def is_admin(self):
        return self.user_type in ['admin', 'superadmin'] or self.user.is_staff

    @property
    def is_superadmin(self):
        return self.user_type == 'superadmin' or self.user.is_superuser
    
    def __str__(self):
        return self.user.username


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    related_item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    status_trigger = models.CharField(max_length=50)
    is_read = models.BooleanField(default=False, db_index=True)
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


class DirectMessage(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='messages', null=True, blank=True)
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Msg from {self.sender.username} to {self.recipient.username}"

    class Meta:
        ordering = ['created_at']
