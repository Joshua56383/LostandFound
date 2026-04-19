from django.db import models
from django.conf import settings
from django.urls import reverse
import os


def get_role_upload_path(instance, filename):
    # Keep uploads organized by model name and user id when available
    model_name = instance.__class__.__name__.lower()
    user_part = ''
    try:
        if hasattr(instance, 'uploader') and instance.uploader:
            user_part = f'user_{instance.uploader.id}'
        elif hasattr(instance, 'owner') and instance.owner:
            user_part = f'user_{instance.owner.id}'
    except Exception:
        user_part = ''
    folder = os.path.join('uploads', model_name, user_part) if user_part else os.path.join('uploads', model_name)
    return os.path.join(folder, filename)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Item(models.Model):
    REPORT_TYPE_CHOICES = [
        ('lost', 'Lost Report'),
        ('found', 'Found Report'),
    ]
    
    LIFECYCLE_STATUS_CHOICES = [
        ('draft', 'Draft (Private)'),
        ('active', 'Active (Searchable)'),
        ('claimed', 'Pending Claim'),
        ('resolved', 'Resolved (Completed)'),
        ('archived', 'Archived / Retired'),
    ]

    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField()
    location = models.CharField(max_length=255)
    date_reported = models.DateTimeField(auto_now_add=True)
    discovery_date = models.DateTimeField(null=True, blank=True, db_index=True, help_text="The actual date and time the item was lost or found.")
    
    # Legacy compatibility (Deprecated: Use report_type and lifecycle_status)
    status = models.CharField(max_length=10, choices=[('lost','Lost'),('found','Found'),('claimed','Claimed'),('archived','Archived')], db_index=True, blank=True, editable=False, help_text="[LEGACY] Do not use for new features.")
    
    # New architecture fields
    report_type = models.CharField(max_length=10, choices=REPORT_TYPE_CHOICES, default='found', db_index=True)
    lifecycle_status = models.CharField(max_length=10, choices=LIFECYCLE_STATUS_CHOICES, default='draft', db_index=True)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_STATUS_CHOICES, default='pending', db_index=True)
    is_manually_verified = models.BooleanField(default=False, help_text="True if an admin manually reviewed/posted this item.")

    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, null=True, blank=True, help_text="Amount of money if applicable")
    denominations = models.TextField(blank=True, help_text="Breakdown of bills/coins (e.g., 2x$50, 1x$20). Mandatory for found money.")
    turnover_status = models.CharField(
        max_length=20, 
        choices=[('pending', 'Pending turnover'), ('confirmed', 'Confirmed by Office'), ('not_required', 'Not Required')], 
        default='not_required'
    )
    category = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(max_length=254, blank=True)
    contact_name = models.CharField(max_length=100, blank=True)
    image = models.ImageField(blank=True, null=True, upload_to=get_role_upload_path)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)

    def clean(self):
        from django.core.exceptions import ValidationError
        # Rule 1: Only Approved items can be Active
        if self.lifecycle_status == 'active' and self.verification_status != 'approved':
            raise ValidationError("An item must be 'Approved' before it can become 'Active'.")
        
        # Rule 2: Rejected items must be Archived
        if self.verification_status == 'rejected' and self.lifecycle_status not in ['archived', 'resolved']:
            self.lifecycle_status = 'archived'

    @property
    def is_approved(self):
        return self.verification_status == 'approved'

    @property
    def display_status(self):
        if self.lifecycle_status == 'resolved':
            return {'label': 'Resolved', 'bg': 'bg-emerald-500/10', 'text': 'text-emerald-600', 'border': 'border-emerald-500/20', 'dot': 'bg-emerald-500'}
        if self.lifecycle_status == 'claimed':
            return {'label': 'Claimed', 'bg': 'bg-purple-500/10', 'text': 'text-purple-600', 'border': 'border-purple-500/20', 'dot': 'bg-purple-500'}
        if self.verification_status == 'rejected':
            return {'label': 'Rejected', 'bg': 'bg-red-500/10', 'text': 'text-red-600', 'border': 'border-red-500/20', 'dot': 'bg-red-500'}
        if self.verification_status == 'pending':
            return {'label': 'Pending', 'bg': 'bg-amber-500/10', 'text': 'text-amber-600', 'border': 'border-amber-500/20', 'dot': 'bg-amber-500'}
        if self.lifecycle_status == 'archived':
            return {'label': 'Archived', 'bg': 'bg-slate-500/10', 'text': 'text-slate-600', 'border': 'border-slate-500/20', 'dot': 'bg-slate-500'}
        return {'label': 'Active', 'bg': 'bg-blue-500/10', 'text': 'text-blue-600', 'border': 'border-blue-500/20', 'dot': 'bg-blue-500'}

    @property
    def report_badge(self):
        return {'label': self.report_type.upper(), 'bg': 'bg-slate-100', 'text': 'text-slate-500', 'border': 'border-slate-200'}

    @property
    def is_locked(self):
        return self.lifecycle_status in ['claimed', 'resolved']

    ai_tags = models.TextField(blank=True, help_text='AI-extracted visual tags for matching')
    date_resolved = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    is_deleted = models.BooleanField(default=False)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['-date_reported']

    @property
    def is_money(self):
        return self.category == 'Wallet / Money' or 'money' in self.name.lower()

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def get_absolute_url(self):
        return reverse('items:item_detail', kwargs={'pk': self.pk})

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()


class ClaimRequest(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('completed', 'Completed')]

    message = models.TextField(help_text='Provide proof of ownership or additional details.')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    claimer = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='claims_made', on_delete=models.CASCADE)
    item = models.ForeignKey(Item, related_name='claims', on_delete=models.CASCADE)

    # Handover Security [Ph 5]
    verification_token = models.UUIDField(null=True, blank=True, unique=True, help_text="Secret token for QR verification handover.")

    # Fields added later
    admin_remarks = models.TextField(blank=True, help_text='Feedback or instructions from admin.')
    contact_phone = models.CharField(max_length=20, blank=True, help_text='Direct contact phone number.')
    proof_file = models.FileField(blank=True, null=True, upload_to=get_role_upload_path, help_text='Upload image or PDF as proof of ownership.')
    
    # Money specific claim fields
    claimed_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    claimed_denominations = models.TextField(blank=True, help_text="Detail the bills/coins you lost.")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Claim by {self.claimer} for {self.item} ({self.status})"


class Notification(models.Model):
    CATEGORY_CHOICES = [
        ('system', 'System Update'),
        ('activity', 'User Activity'),
        ('admin', 'Admin Alert')
    ]
    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('high', 'High Priority')
    ]

    title = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='system', db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal', db_index=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    status_trigger = models.CharField(max_length=50)
    is_read = models.BooleanField(default=False, db_index=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='notifications', on_delete=models.CASCADE)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='notifications_sent', null=True, blank=True, on_delete=models.SET_NULL)
    related_item = models.ForeignKey(Item, related_name='notifications', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification to {self.recipient}: {self.status_trigger}"


class DirectMessage(models.Model):
    content = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    item = models.ForeignKey(Item, related_name='messages', null=True, blank=True, on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='received_messages', on_delete=models.CASCADE)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_messages', on_delete=models.CASCADE)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"DM from {self.sender} to {self.recipient}"




class UserProfile(models.Model):
    USER_TYPE_CHOICES = [('student', 'Student'), ('staff', 'Staff'), ('admin', 'Admin'), ('superadmin', 'Superadmin')]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='userprofile', on_delete=models.CASCADE)
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.ImageField(blank=True, null=True, upload_to=get_role_upload_path)
    student_staff_id = models.CharField(max_length=20, blank=True, verbose_name='Student/Staff ID')
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='student')
    trust_score = models.PositiveIntegerField(default=100, db_index=True)

    @property
    def is_admin(self):
        return self.user_type in ['admin', 'superadmin'] or self.user.is_staff

    @property
    def is_superadmin(self):
        return self.user_type == 'superadmin' or self.user.is_superuser

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"{self.user.username}'s profile"

    @property
    def unread_notification_count(self):
        try:
            return self.user.notifications.filter(is_read=False).count()
        except Exception:
            return 0

class MatchSuggestion(models.Model):
    STATUS_CHOICES = [('pending', 'Pending Review'), ('linked', 'Matched & Notified'), ('dismissed', 'Dismissed')]
    
    lost_item = models.ForeignKey(Item, related_name='lost_matches', on_delete=models.CASCADE)
    found_item = models.ForeignKey(Item, related_name='found_matches', on_delete=models.CASCADE)
    score = models.FloatField(default=0.0, help_text="Similarity score 0.0 to 1.0")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-score']
        unique_together = ('lost_item', 'found_item')

    def __str__(self):
        return f"Match {self.score*100:.1f}%: {self.lost_item} <-> {self.found_item}"

class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='push_subscriptions', on_delete=models.CASCADE)
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Subscription for {self.user.username}"


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100, db_index=True)
    item = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.action} - {self.created_at}"
