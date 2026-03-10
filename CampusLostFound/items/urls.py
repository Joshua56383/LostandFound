app_name = 'items'  # THIS MUST BE AT THE TOP

from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('admin/users/', views.user_directory, name='user_directory'),
    path('admin/analytics/', views.admin_analytics, name='admin_analytics'),
    path('admin/logs/', views.audit_logs, name='audit_logs'),
    path('', views.item_list, name='item_list'),
    path('add/', views.add_item, name='add_item'),
    path('report/<str:status>/', views.report_item, name='report_item'),
    path('<int:pk>/', views.item_detail, name='item_detail'),
    path('edit/<int:pk>/', views.edit_item, name='edit_item'),
    path('delete/<int:pk>/', views.delete_item, name='delete_item'),
    path('profile/', views.profile, name='profile'),
    path('edit-profile/', views.edit_profile, name='edit_profile'),
    path('claim/<int:item_id>/', views.claim_item, name='claim_item'),
    path('admin/users/toggle-active/<int:user_id>/', views.toggle_user_active, name='toggle_user_active'),
    path('admin/users/toggle-role/<int:user_id>/', views.toggle_user_role, name='toggle_user_role'),
    path('admin/users/delete/<int:user_id>/', views.delete_user_admin, name='delete_user_admin'),
    path('admin/users/reset-password/<int:user_id>/', views.reset_user_password, name='reset_user_password'),
    path('api/notifications/', views.get_notifications, name='get_notifications'),
    path('api/notifications/read/<int:notif_id>/', views.mark_notification_read, name='mark_notification_read'),
]
