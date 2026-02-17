from django.contrib import admin
from . import models

admin.site.register(models.Item)
admin.site.register(models.UserLoginLog)

# Register UserProfile if it exists
if hasattr(models, 'UserProfile'):
    admin.site.register(models.UserProfile)
