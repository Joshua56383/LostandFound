from django.contrib import admin
from . import models


class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'report_type', 'lifecycle_status', 'verification_status', 'category', 'location', 'owner', 'date_reported')
    list_filter = ('report_type', 'lifecycle_status', 'verification_status', 'category')
    search_fields = ('name', 'description', 'location')
    list_editable = ('lifecycle_status', 'verification_status')



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
admin.site.register(models.Notification, NotificationAdmin)

# Register UserProfile if it exists
if hasattr(models, 'UserProfile'):
    admin.site.register(models.UserProfile)
