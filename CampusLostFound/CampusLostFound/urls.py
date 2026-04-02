"""
URL configuration for CampusLostFound project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# CampusLostFound/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.contrib.auth import views as auth_views
from . import views


urlpatterns = [
    path('', include('items.urls', namespace='items')),
    path('admin/', admin.site.urls),
    path('admin-login/', auth_views.LoginView.as_view(template_name='user/admin_login.html'), name='admin_login'),
    
    # Custom Auth Flow: All pointing to login.html
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='user/login.html'
    ), name='login'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(
        template_name='user/login.html',
        email_template_name='user/password_reset_email.html',
        subject_template_name='user/password_reset_subject.txt',
        success_url='/accounts/login/?reset_sent=1'
    ), name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='user/login.html'
    ), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='user/login.html',
        success_url='/accounts/login/?reset_complete=1'
    ), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='user/login.html'
    ), name='password_reset_complete'),
    
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),
    path('signup/', views.signup, name='signup'),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

