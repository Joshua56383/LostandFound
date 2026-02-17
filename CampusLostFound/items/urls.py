app_name = 'items'  # THIS MUST BE AT THE TOP

from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('', views.item_list, name='item_list'),
    path('add/', views.add_item, name='add_item'),
    path('report/<str:status>/', views.report_item, name='report_item'),
    path('<int:pk>/', views.item_detail, name='item_detail'),  # optional if you have a detail view
    path('profile/', views.profile, name='profile'),
    path('edit-profile/', views.edit_profile, name='edit_profile'),
]
