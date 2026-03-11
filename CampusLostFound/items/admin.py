from django.contrib import admin
from django.contrib.auth.models import User
from . import models
from . import ai_service


class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'category', 'location', 'owner', 'is_approved', 'date_reported')
    list_filter = ('status', 'category', 'is_approved')
    search_fields = ('name', 'description', 'location')
    list_editable = ('status', 'is_approved')

    def save_model(self, request, obj, form, change):
        """When an admin changes an item's status, send an AI notification."""
        if change and 'status' in form.changed_data:
            old_status = models.Item.objects.get(pk=obj.pk).status
            new_status = obj.status

            # Save the item first
            super().save_model(request, obj, form, change)

            # Determine the notification trigger
            status_map = {
                'claimed': 'claim_approved',
                'lost': 'lost_reported',
                'found': 'found_reported',
            }
            trigger = status_map.get(new_status, f'status_changed_to_{new_status}')

            # Notify the item owner
            if obj.owner:
                message = ai_service.generate_notification_message(obj, trigger)
                models.Notification.objects.create(
                    recipient=obj.owner,
                    message=message,
                    related_item=obj,
                    status_trigger=trigger,
                )

            # Notify all admins about the status change
            for admin_user in User.objects.filter(is_staff=True).exclude(pk=request.user.pk):
                message = ai_service.generate_notification_message(obj, trigger)
                models.Notification.objects.create(
                    recipient=admin_user,
                    message=message,
                    related_item=obj,
                    status_trigger=trigger,
                )
        else:
            super().save_model(request, obj, form, change)


class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'short_message', 'status_trigger', 'is_read', 'created_at')
    list_filter = ('is_read', 'status_trigger', 'created_at')
    search_fields = ('message', 'recipient__username')
    readonly_fields = ('created_at',)
    list_editable = ('is_read',)

    def short_message(self, obj):
        return obj.message[:60] + '...' if len(obj.message) > 60 else obj.message
    short_message.short_description = 'Message'


admin.site.register(models.Item, ItemAdmin)
admin.site.register(models.UserLoginLog)
admin.site.register(models.Notification, NotificationAdmin)

# Register UserProfile if it exists
if hasattr(models, 'UserProfile'):
    admin.site.register(models.UserProfile)
