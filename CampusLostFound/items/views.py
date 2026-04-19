"""
Consolidated Views Package for Campus Lost & Found
"""
import os
import csv
import secrets
import string
import logging
from functools import wraps

from django.shortcuts import render, redirect, get_object_or_404
from items.services.notification_service import NotificationService
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Count, Sum, Avg, F
from django.db.models.functions import TruncMonth, TruncDate, ExtractDay
from django.core.paginator import Paginator
from django.http import HttpResponse, FileResponse, HttpResponseForbidden, Http404, JsonResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from . import models
from . import ai_service
from .forms import ItemForm, UserUpdateForm, UserProfileForm, ClaimForm, MoneyClaimForm, CustomUserCreationForm

# Layered Architecture: Services
from .services.item_service import ItemService
from .services.claim_service import ClaimService
from .services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# ===============================
# DECORATORS
# ===============================
def role_required(allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            try:
                profile = request.user.userprofile
            except models.UserProfile.DoesNotExist:
                profile = models.UserProfile.objects.create(user=request.user)

            user_has_role = False
            if 'superadmin' in allowed_roles and profile.is_superadmin:
                user_has_role = True
            elif ('admin' in allowed_roles or 'staff' in allowed_roles) and profile.is_admin:
                user_has_role = True
            elif profile.user_type in allowed_roles:
                user_has_role = True
            elif not allowed_roles:
                user_has_role = True

            if user_has_role:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped_view
    return decorator

def superadmin_required(view_func):
    return role_required(['superadmin'])(view_func)

def admin_required(view_func):
    return role_required(['admin', 'superadmin'])(view_func)

# ===============================
# AUTHENTICATION
# ===============================
@login_required
def profile(request):
    user_items = models.Item.objects.filter(owner=request.user).order_by('-date_reported')
    user_items_resolved_count = user_items.filter(lifecycle_status='resolved').count()
    pending_claims = models.ClaimRequest.objects.filter(
        item__owner=request.user, 
        status='pending'
    ).order_by('-created_at')
    
    return render(request, 'user/profile.html', {
        'user_items': user_items,
        'user_items_resolved_count': user_items_resolved_count,
        'pending_claims': pending_claims,
        'breadcrumb_label': 'Profile'
    })

@login_required
def edit_profile(request):
    profile, created = models.UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return HttpResponse('<script>window.dispatchEvent(new CustomEvent("refresh-page"));</script>')
            messages.success(request, 'Your profile has been updated.')
            return redirect('items:profile')
    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = UserProfileForm(instance=profile)
    
    context = {'form': user_form, 'profile_form': profile_form, 'breadcrumb_label': 'Edit Profile'}
    return render(request, 'user/edit_profile.html', context)

@login_required
def my_activity(request):
    user_items = models.Item.objects.filter(owner=request.user, deleted_at__isnull=True).order_by('-date_reported')
    claim_requests = models.ClaimRequest.objects.filter(claimer=request.user).select_related('item').order_by('-created_at')
    
    # Stats for the student
    stats = {
        'total_reported': user_items.count(),
        'active_claims': claim_requests.filter(status='pending').count(),
        'resolved': user_items.filter(lifecycle_status='resolved').count()
    }
    
    return render(request, 'user/my_activity.html', {
        'items': user_items,
        'claims': claim_requests,
        'stats': stats,
        'breadcrumb_label': 'My Activity'
    })



def item_list(request):
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', 'all')
    location = request.GET.get('location', 'all')
    tab = request.GET.get('tab', 'all')
    show_pending = request.GET.get('pending') == '1'

    # Support for administrative approval queue
    is_admin = request.user.is_authenticated and (request.user.is_staff or getattr(request.user.userprofile, 'is_admin', False))
    
    if show_pending:
        items = models.Item.objects.filter(verification_status='pending', deleted_at__isnull=True)
    else:
        # Visibility Rule (State Decoupling): Only Approved + Active reports are public
        items = models.Item.objects.filter(
            verification_status='approved', 
            lifecycle_status='active',
            deleted_at__isnull=True
        )
    
    items = items.select_related('owner')
    
    if q:
        items = items.filter(
            Q(name__icontains=q) | 
            Q(description__icontains=q) | 
            Q(category__icontains=q)
        )
    
    if category and category != 'all':
        items = items.filter(category=category)
    if location and location != 'all':
        items = items.filter(location=location)
    if tab in ['lost', 'found']:
        items = items.filter(report_type=tab)

    items = items.order_by('-date_reported')

    paginator = Paginator(items, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Visibility Rule (State Decoupling): Statistics only count active items in the public hub
    approved_items = models.Item.objects.filter(verification_status='approved', lifecycle_status='active')
    
    # Efficiently aggregate counts in a single query
    stats = approved_items.aggregate(
        total=Count('id'),
        lost=Count('id', filter=Q(report_type='lost')),
        found=Count('id', filter=Q(report_type='found'))
    )
    total_count, lost_count, found_count = stats['total'], stats['lost'], stats['found']

    categories = approved_items.exclude(category='').order_by('category').values_list('category', flat=True).distinct()
    locations = approved_items.exclude(location='').order_by('location').values_list('location', flat=True).distinct()

    # Build options for select components
    categories_options = [('all', 'Categories')] + [(c, c) for c in categories]
    locations_options = [('all', 'Locations')] + [(l, l) for l in locations]

    context = {
        'items': page_obj, 'q': q, 'category': category, 'location': location,
        'tab': tab, 'total_count': total_count, 'lost_count': lost_count,
        'found_count': found_count, 'categories': categories, 'locations': locations,
        'categories_options': categories_options, 'locations_options': locations_options,
        'breadcrumb_label': 'Pending Approvals' if show_pending else 'Dashboard'
    }
    return render(request, 'item/item_list.html', context)

@login_required
def report_item(request, status=None):
    # Detect status
    active_status = request.GET.get('type') or status
    if active_status not in ['lost', 'found']:
        active_status = 'lost'

    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item, success, error = ItemService.report_item(request.user, form)
            if not success:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                     # Return 400 for validation failures to prevent false success in frontend
                     messages.error(request, "Submission failed. Please check the requirements.")
                     return render(request, 'item/add_item.html', {
                         'form': form, 'report_type': active_status, 'base_template': '_partial.html'
                     }, status=400)
                messages.error(request, f"Validation Failed: {error}")
                return redirect('items:item_list')

            is_emergency = request.GET.get('mode') == 'emergency'
            success_msg = "Report submitted! "
            
            if is_emergency:
                success_msg += "Tip: Edit your report later to add a photo or unique detail to increase recovery chance by 70%."
            elif item.verification_status == 'approved':
                success_msg += "Your post is now live and visible in the public registry."
            else:
                success_msg += "It is currently pending staff review for quality assurance."

            messages.success(request, success_msg)

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'pk': item.id})
            
            return redirect('items:item_detail', pk=item.id)
    else:
        form = ItemForm(initial={'report_type': active_status})
    
    context = {
        'form': form,
        'report_type': active_status,
        'breadcrumb_label': 'Report Item'
    }
    
    if request.method == 'POST' and not form.is_valid():
        logger.warning(f"FORM VALIDATION FAILED: {form.errors.as_json()}")
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
             # Provide a generic error message for the modal if the specific fields aren't clear
             messages.error(request, "Please check the form for errors.")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        context['base_template'] = '_partial.html'
        # Return 400 for validation failures to prevent false success in frontend
        return render(request, 'item/add_item.html', context, status=400 if request.method == 'POST' else 200)

    return render(request, 'item/add_item.html', context)

@login_required
def money_tracker(request):
    """
    Dedicated view for tracking lost and found money records.
    Filters items by category='Wallet / Money'.
    """
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.method == 'GET':
        form = ItemForm(initial={'category': 'Wallet / Money', 'report_type': 'found'})
        return render(request, 'item/add_money_record.html', {'form': form, 'base_template': '_partial.html'})

    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item, success, error = ItemService.report_item(request.user, form)
            
            if not success:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': error})
                messages.error(request, f"Validation Failed: {error}")
                return redirect('items:money_tracker')

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'pk': item.id})
            
            success_msg = f"Cash record added! "
            if item.verification_status == 'approved':
                success_msg += "The entry is now reflected in the public tracking ledger."
            else:
                success_msg += "It is pending review before appearing in the public ledger."

            messages.success(request, success_msg)
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': "Form Error: " + str(form.errors)})
    else:
        form = ItemForm(initial={'category': 'Wallet / Money', 'report_type': 'found'})
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'item/add_money_record.html', {'form': form, 'base_template': '_partial.html'}, status=400 if request.method == 'POST' else 200)
    
    # Get all items for global history
    # Visibility Rules (Stage 10: State Awareness)
    # Admins see everything; Owners see their pending items; Guests see only approved.
    is_admin = request.user.is_authenticated and (request.user.is_staff or getattr(request.user.userprofile, 'is_admin', False))
    
    status_filter = request.GET.get('status', 'all')
    
    visibility_filter = Q(verification_status='approved')
    if request.user.is_authenticated:
        visibility_filter |= Q(owner=request.user)
    if is_admin:
        visibility_filter = Q() # Admins see all verification statuses

    records = models.Item.objects.filter(visibility_filter)
    
    if status_filter == 'active':
        records = records.filter(lifecycle_status='active')
    elif status_filter == 'resolved':
        records = records.filter(lifecycle_status='resolved')
    elif status_filter == 'claimed':
        records = records.filter(lifecycle_status='claimed')

    records = records.order_by('-date_reported')
    
    # Aggregates for summary cards (based on all items in history)
    # Total recorded, Total Found, Total Lost
    total_items = records.count()
    total_found = records.filter(report_type='found').count()
    total_lost = records.filter(report_type='lost').count()
    
    return render(request, 'item/history_vault.html', {
        'records': records,
        'total_found': total_found,
        'total_lost': total_lost,
        'total_records_count': total_items,
        'breadcrumb_label': 'History Vault',
        'is_admin': is_admin,
        'current_status': status_filter
    })

def item_detail(request, pk):
    # Use all_objects to allow handling of soft-deleted items gracefully
    item = get_object_or_404(models.Item.all_objects, pk=pk)
    
    is_admin = request.user.is_authenticated and (request.user.is_staff or getattr(request.user.userprofile, 'is_admin', False))
    is_owner = request.user.is_authenticated and item.owner == request.user

    # Handle Deleted State (Stage 9: Graceful Removal)
    if item.is_deleted:
        if not (is_admin or is_owner):
            return render(request, 'item/item_removed.html', {'item_name': item.name}, status=404)
        # Admins/Owners see the page with a warning banner

    # Visibility Logic
    if item.verification_status != 'approved' and not item.is_deleted:
        can_view = is_admin or is_owner
        
        if not can_view:
            messages.warning(request, "This item is still being checked by an admin.")
            return redirect('items:item_list')
    
    ai_suggestions = []
    if item.ai_tags and item.lifecycle_status == 'active':
        opposite_type = 'found' if item.report_type == 'lost' else 'lost'
        tag_list = [t.strip().lower() for t in item.ai_tags.split(',') if t.strip()]
        
        if tag_list:
            query = Q()
            for tag in tag_list[:3]: query |= Q(ai_tags__icontains=tag)
            ai_suggestions = models.Item.objects.filter(
                report_type=opposite_type, 
                verification_status='approved',
                lifecycle_status='active'
            ).filter(query).exclude(id=item.id)[:4]

    claims = []
    if request.user.is_authenticated:
        is_admin = request.user.userprofile.is_admin
        if is_admin or item.owner == request.user:
            claims = models.ClaimRequest.objects.filter(item=item).select_related('claimer').order_by('-created_at')

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'item/item_detail.html', {
            'item': item, 
            'ai_suggestions': ai_suggestions,
            'claims': claims,
            'is_admin': is_admin,
            'is_owner': is_owner,
            'base_template': '_partial.html'
        })

    return render(request, 'item/item_detail.html', {
        'item': item, 
        'ai_suggestions': ai_suggestions,
        'claims': claims,
        'is_admin': is_admin,
        'is_owner': is_owner,
        'breadcrumb_label': 'Item Details'
    })

@login_required
def edit_item(request, pk):
    item = get_object_or_404(models.Item, pk=pk)
    
    # Permission Check: Only Admins can edit reports after submission
    if not (request.user.is_staff or getattr(request.user.userprofile, 'is_admin', False)):
        messages.error(request, "Only administrators can edit reports after submission.")
        return redirect('items:item_list')

    # Quick Status Update (from query params)
    quick_status = request.GET.get('quick_status')
    if quick_status:
        # Map quick status to new architecture
        if quick_status in ['lost', 'found']:
            item.report_type = quick_status
            item.lifecycle_status = 'active'
        elif quick_status == 'claimed':
            item.lifecycle_status = 'claimed'
        elif quick_status == 'resolved':
            item.lifecycle_status = 'resolved'
        
        item.save()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Status updated!'})
            
        messages.success(request, 'Status updated!')
        return redirect('items:item_detail', pk=item.id)

    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Item details updated successfully.')
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'pk': item.id})
            return redirect('items:item_detail', pk=item.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        # Map current values to form
        form = ItemForm(instance=item)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'item/edit_item.html', {
            'form': form,
            'item': item,
            'base_template': '_partial.html'
        }, status=400 if request.method == 'POST' else 200)

    return render(request, 'item/edit_item.html', {
        'form': form,
        'item': item,
        'breadcrumb_label': 'Edit Item'
    })

@login_required
def delete_item(request, pk):
    try: item = models.Item.objects.get(pk=pk)
    except models.Item.DoesNotExist:
        messages.info(request, "We couldn't find that item.")
        return redirect('items:item_list')

    # Permission Check: Only Admins can delete reports
    if not (request.user.is_staff or getattr(request.user.userprofile, 'is_admin', False)):
        messages.error(request, "Only administrators can delete reports.")
        return redirect('items:item_list')

    if request.method == 'POST':
        item_name = item.name
        if item.owner and item.owner != request.user:
            NotificationService.send_status_notification(item.owner, item, 'item_deleted')
        item.soft_delete()
        messages.success(request, f'Item removed.')
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Item removed'})
            
    return redirect(request.META.get('HTTP_REFERER', 'items:item_list'))

def serve_private_file(request, file_path):
    normalized_path = os.path.normpath(file_path).lstrip(os.sep)
    full_path = os.path.join(settings.MEDIA_ROOT, normalized_path)
    if not os.path.exists(full_path):
        full_path = os.path.join(settings.PRIVATE_STORAGE_ROOT, normalized_path)

    is_in_media = os.path.abspath(full_path).startswith(os.path.abspath(str(settings.MEDIA_ROOT)))
    is_in_private = os.path.abspath(full_path).startswith(os.path.abspath(str(settings.PRIVATE_STORAGE_ROOT)))
    
    if not (is_in_media or is_in_private): return HttpResponseForbidden("Access Denied")
    if not os.path.exists(full_path): raise Http404("File not found")

    profile = None
    if request.user.is_authenticated:
        try: profile = request.user.userprofile
        except models.UserProfile.DoesNotExist: profile = models.UserProfile.objects.create(user=request.user)

    # Standardize path for matching
    web_path = normalized_path.replace('\\', '/')
    filename = os.path.basename(normalized_path)

    # Check if this file belongs to an approved item
    item = models.Item.objects.filter(image__icontains=filename).first()
    if item:
        if item.verification_status == 'approved': return FileResponse(open(full_path, 'rb'))
        if request.user.is_authenticated and profile:
            if profile.is_admin or item.owner == request.user: return FileResponse(open(full_path, 'rb'))
                
    if not request.user.is_authenticated: return HttpResponseForbidden("Please log in to see this.")
    if profile and profile.is_superadmin: return FileResponse(open(full_path, 'rb'))
    return HttpResponseForbidden("Access Denied")

# ===============================
# CLAIMS
# ===============================
@login_required
def claim_item(request, item_id):
    item = get_object_or_404(models.Item, id=item_id)
    if not item:
        messages.error(request, "Item not found.")
        return redirect('items:item_list')
        
    if item.owner != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to mark this as found.")
        return redirect('items:item_list')
        
    item.status = 'claimed'
    item.save()
    
    messages.success(request, f"Item marked as resolved!")
    return redirect('items:item_list')

@login_required
def submit_claim(request, item_id):
    item = get_object_or_404(models.Item, id=item_id)
    
    # Check if user already has an active claim
    existing_claim = models.ClaimRequest.objects.filter(
        item=item, claimer=request.user, status__in=['pending', 'approved']
    ).exists()
    
    if existing_claim:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponse(
                '<div class="py-20 text-center">'
                '<div class="w-16 h-16 rounded-2xl bg-amber-100 flex items-center justify-center text-amber-500 mx-auto mb-6">'
                '<i data-lucide="alert-circle" class="w-8 h-8"></i></div>'
                '<h3 class="text-lg font-black text-slate-800 mb-2">Already Claimed</h3>'
                '<p class="text-sm text-slate-500">You already have an active claim on this item. Check your Activity page for updates.</p>'
                '</div>'
            )
        messages.warning(request, f"You've already claimed this item.")
        return redirect('items:item_list')

    is_money = item.is_money
    FormClass = MoneyClaimForm if is_money else ClaimForm

    if request.method == 'POST':
        form = FormClass(request.POST, request.FILES)
        if form.is_valid():
            ClaimService.submit_claim(request.user, item, form)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return HttpResponse('<script>window.dispatchEvent(new CustomEvent("refresh-page"));</script>')
            
            messages.success(request, f"Claim submitted! We'll let you know once it's reviewed.")
            return redirect('items:item_detail', pk=item.id)
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return render(request, 'item/claim.html', {
                    'form': form, 'item': item, 'base_template': '_partial.html'
                }, status=400)
    else:
        form = FormClass()
    
    base_template = '_partial.html' if request.headers.get('x-requested-with') == 'XMLHttpRequest' else 'base.html'
    return render(request, 'item/claim.html', {'form': form, 'item': item, 'base_template': base_template, 'is_money': is_money})


@login_required
def approve_claim(request, claim_id):
    claim = get_object_or_404(models.ClaimRequest, id=claim_id)
    item = claim.item
    
    if item.owner != request.user and not (request.user.is_staff or request.user.userprofile.is_admin):
        messages.error(request, "You don't have permission to approve this claim.")
        return redirect('items:item_list')
        
    remarks = request.POST.get('remarks', '') if request.method == 'POST' else ''
    ClaimService.approve_claim(claim, request.user, remarks)
    
    messages.success(request, f"Claim approved!")
    return redirect(request.META.get('HTTP_REFERER', 'items:item_list'))


@login_required
def reject_claim(request, claim_id):
    claim = get_object_or_404(models.ClaimRequest, id=claim_id)
    item = claim.item
    
    if item.owner != request.user and not (request.user.is_staff or request.user.userprofile.is_admin):
        messages.error(request, "You don't have permission to reject this claim.")
        return redirect('items:item_list')
        
    remarks = request.POST.get('remarks', 'Proof insufficient.') if request.method == 'POST' else 'Proof insufficient.'
    ClaimService.reject_claim(claim, request.user, remarks)
    
    messages.info(request, f"Claim rejected.")
    return redirect(request.META.get('HTTP_REFERER', 'items:item_list'))


@login_required
def complete_claim(request, claim_id):
    claim = get_object_or_404(models.ClaimRequest, id=claim_id)
    item = claim.item
    
    if item.owner != request.user and not (request.user.is_staff or request.user.userprofile.is_admin):
        messages.error(request, "Permission denied.")
        return redirect('items:item_list')

    ClaimService.complete_claim(claim, request.user)
    
    messages.success(request, f"Item returned! The report is now closed.")
    return redirect(request.META.get('HTTP_REFERER', 'items:item_list'))



# ===============================
# ADMIN
# ===============================
@admin_required
def user_directory(request):
    users = User.objects.all().order_by('-date_joined')
    q = request.GET.get('q', '')
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    
    role_options = [('all', 'All Roles'), ('admin', 'Admin'), ('student', 'Student')]
    status_options = [('all', 'Any Status'), ('active', 'Active'), ('suspended', 'Suspended')]
    
    return render(request, 'admin/user_directory.html', {
        'users': users, 'q': q, 
        'role_options': role_options, 'status_options': status_options,
        'breadcrumb_label': 'Manage Users'
    })

@admin_required
def manage_user(request, user_id):
    target_user = get_object_or_404(User, id=user_id)
    return render(request, 'admin/manage_user.html', {
        'target_user': target_user,
        'breadcrumb_label': f'Manage {target_user.username}'
    })

@admin_required
def toggle_user_active(request, user_id):
    if request.method == 'POST':
        user_to_toggle = get_object_or_404(User, id=user_id)
        
        # Superadmin Protect Check
        if user_to_toggle.userprofile.is_superadmin and not request.user.userprofile.is_superadmin:
            messages.error(request, "You cannot edit a superadmin account.")
            return redirect('items:user_directory')

        if user_to_toggle != request.user:
            user_to_toggle.is_active = not user_to_toggle.is_active
            user_to_toggle.save()
            status = "activated" if user_to_toggle.is_active else "deactivated"
            messages.success(request, f"User {status}!")
        else:
            messages.error(request, "You cannot deactivate your own account.")
    return redirect(request.META.get('HTTP_REFERER', 'items:user_directory'))

@admin_required
def toggle_user_role(request, user_id):
    if request.method == 'POST':
        user_to_toggle = get_object_or_404(User, id=user_id)

        # Superadmin Protect Check
        if user_to_toggle.userprofile.is_superadmin and not request.user.userprofile.is_superadmin:
            messages.error(request, "You cannot edit a superadmin account.")
            return redirect('items:user_directory')

        if user_to_toggle != request.user:
            user_to_toggle.is_staff = not user_to_toggle.is_staff
            user_to_toggle.save()
            role = "Admin" if user_to_toggle.is_staff else "Standard"
            messages.success(request, f'User role updated.')
        else:
            messages.error(request, "You cannot change your own role.")
    return redirect(request.META.get('HTTP_REFERER', 'items:user_directory'))

@admin_required
def delete_user_admin(request, user_id):
    if request.method == 'POST':
        user_to_delete = get_object_or_404(User, id=user_id)

        # Superadmin Protect Check
        if user_to_delete.userprofile.is_superadmin and not request.user.userprofile.is_superadmin:
            messages.error(request, "You cannot edit a superadmin account.")
            return redirect('items:user_directory')

        if user_to_delete != request.user:
            username = user_to_delete.username
            user_to_delete.delete()
            messages.success(request, f'User deleted.')
        else:
            messages.error(request, "You cannot delete your own account.")
    return redirect(request.META.get('HTTP_REFERER', 'items:user_directory'))

@admin_required
def reset_user_password(request, user_id):
    if request.method == 'POST':
        user_to_reset = get_object_or_404(User, id=user_id)

        # Superadmin Protect Check
        if user_to_reset.userprofile.is_superadmin and not request.user.userprofile.is_superadmin:
            messages.error(request, "You cannot edit a superadmin account.")
            return redirect('items:user_directory')

        alphabet = string.ascii_letters + string.digits + '!@#$%'
        temp_pass = ''.join(secrets.choice(alphabet) for _ in range(12))
        user_to_reset.set_password(temp_pass)
        user_to_reset.save()
        messages.success(request, f'Password reset. New temp password: {temp_pass}')
    return redirect(request.META.get('HTTP_REFERER', 'items:user_directory'))

@admin_required
def approve_item(request, item_id):
    item = get_object_or_404(models.Item, id=item_id)
    if item.verification_status != 'pending':
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Already processed or invalid state'}, status=400)
    
    if item.verification_status != 'approved':
        ItemService.approve_item(item, request.user)
        
    if request.headers.get('Content-Type') == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'new_state': 'approved', 'previous_state': 'pending'})
        
    messages.success(request, f"Item approved!")
    return redirect(request.META.get('HTTP_REFERER', 'items:dashboard'))


@admin_required
def reject_item(request, item_id):
    item = get_object_or_404(models.Item, id=item_id)
    if item.verification_status != 'pending':
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Already processed or invalid state'}, status=400)

    reason = request.POST.get('reason', 'Policy violation')
    ItemService.reject_item(item, request.user, reason=reason)
    
    if request.headers.get('Content-Type') == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'new_state': 'rejected', 'previous_state': 'pending'})
        
    messages.warning(request, f"Item rejected. Reason: {reason}")
    return redirect(request.META.get('HTTP_REFERER', 'items:dashboard'))


@admin_required
def revert_item(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(models.Item, id=item_id)
        ItemService.revert_item(item, request.user)
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'new_state': 'pending'})
            
    return redirect(request.META.get('HTTP_REFERER', 'items:dashboard'))


@admin_required
def smart_approve_items(request):
    if request.method == 'POST':
        # Auto-approve items with trustworthy owners and no negative AI tags (just trusting all pending for now or with criteria)
        pending_items = models.Item.objects.filter(verification_status='pending')
        # In a real enterprise system, filter by trust_score > 80, but here we approve all non-flagged things
        safe_items = [i for i in pending_items if (i.owner and getattr(i.owner.userprofile, 'trust_score', 0) > 80)]
        
        approved_ids = []
        for item in safe_items:
            ItemService.approve_item(item, request.user)
            approved_ids.append(item.id)
            
        if request.headers.get('Content-Type') == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'approved_ids': approved_ids, 'count': len(approved_ids)})
            
        messages.success(request, f"{len(approved_ids)} safe items automatically approved.")
        
    return redirect(request.META.get('HTTP_REFERER', 'items:dashboard'))


@admin_required
def bulk_approve(request):
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        if item_ids:
            items = models.Item.objects.filter(id__in=item_ids, verification_status='pending')
            count = items.count()
            for item in items:
                ItemService.approve_item(item, request.user)
            messages.success(request, f'{count} items have been approved.')
        else: 
            messages.warning(request, 'No items selected.')
    return redirect(request.META.get('HTTP_REFERER', 'items:dashboard'))


@admin_required
def bulk_reject(request):
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        reason = request.POST.get('reason', 'Bulk policy enforcement')
        if item_ids:
            items = models.Item.objects.filter(id__in=item_ids)
            count = items.count()
            for item in items:
                ItemService.reject_item(item, request.user, reason=reason)
            messages.warning(request, f'{count} items have been rejected. Reason: {reason}')
        else: 
            messages.warning(request, 'No items selected.')
    return redirect(request.META.get('HTTP_REFERER', 'items:dashboard'))


# ===============================
# IMPRESSOR TRIO: AI, QR, PWA
# ===============================

@admin_required
def match_dashboard(request):
    """Specialized Triage Console for AI-detected Potential Matches."""
    suggestions = models.MatchSuggestion.objects.filter(status='pending').select_related('lost_item', 'found_item')
    return render(request, 'admin/match_dashboard.html', {
        'suggestions': suggestions,
        'breadcrumb_label': 'AI Match Triage'
    })

@admin_required
def verify_match_api(request, suggestion_id):
    """Admin confirms the AI match is accurate. Notifies both users."""
    if request.method == 'POST':
        match = get_object_or_404(models.MatchSuggestion, id=suggestion_id)
        match.status = 'linked'
        match.save()
        
        # Notify Both Parties
        NotificationService.notify_match_detected(match.lost_item, [match.found_item])
        
        return JsonResponse({'success': True, 'msg': 'Match verified and users notified!'})
    return JsonResponse({'error': 'POST required'}, status=405)

@admin_required
def dismiss_match_api(request, suggestion_id):
    """Admin dismisses the AI match as a false positive."""
    if request.method == 'POST':
        match = get_object_or_404(models.MatchSuggestion, id=suggestion_id)
        match.status = 'dismissed'
        match.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'POST required'}, status=405)

@admin_required
def qr_scanner(request):
    """The official Admin/Staff scanner portal for physical handovers."""
    return render(request, 'admin/qr_scanner.html', {
        'breadcrumb_label': 'Staff Security Scanner'
    })

@admin_required
def verify_qr_token_api(request):
    """Processes scan results and finalizes claim turnover."""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        token = data.get('token')
        
        claim = get_object_or_404(models.ClaimRequest, verification_token=token)
        
        if claim.status == 'completed':
            return JsonResponse({'error': 'Claim already finalized.', 'item': claim.item.name}, status=400)
            
        ClaimService.complete_claim(claim, request.user)
        
        return JsonResponse({
            'success': True, 
            'claimer': claim.claimer.username, 
            'item': claim.item.name
        })
    return JsonResponse({'error': 'Invalid request'}, status=405)

@login_required
def claim_pass(request, claim_id):
    """The student's secure Digital Pass to show the Admin."""
    claim = get_object_or_404(models.ClaimRequest, id=claim_id, claimer=request.user)
    if claim.status != 'approved':
        messages.error(request, "This pass is not active. Your claim must be approved first.")
        return redirect('items:my_activity')
        
    return render(request, 'item/claim_pass.html', {
        'claim': claim,
        'breadcrumb_label': 'Handover Pass'
    })

# ===============================
# MESSAGING
# ===============================


@login_required
def mark_notification_read(request, pk):
    notification = get_object_or_404(models.Notification, id=pk, recipient=request.user)
    notification.is_read = True
    notification.save()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success'})
    return redirect(request.META.get('HTTP_REFERER', 'items:notifications'))

@login_required
def mark_all_notifications_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success'})
    messages.success(request, "All notifications marked as read.")
    return redirect(request.META.get('HTTP_REFERER', 'items:notifications'))

@login_required
def notifications_list(request):
    notifications = request.user.notifications.all()
    
    # Tier mapping for specific 1:1 design
    # Inbox = Unread & Not Archived
    # General = All Not Archived
    # Archived = Manually Archived
    counts = {
        'inbox': notifications.filter(is_read=False, is_archived=False).count(),
        'general': notifications.filter(is_archived=False).count(),
        'archived': notifications.filter(is_archived=True).count(),
    }
    
    # We display General by default (all non-archived)
    paginator = Paginator(notifications.filter(is_archived=False), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'user/notifications.html', {
        'notifications': page_obj, 
        'counts': counts,
        'breadcrumb_label': 'Activity Feed'
    })

@login_required
def archive_notification(request, pk):
    notification = get_object_or_404(models.Notification, id=pk, recipient=request.user)
    notification.is_archived = not notification.is_archived
    notification.is_read = True # Archiving usually implies seen
    notification.save()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'success', 'is_archived': notification.is_archived})
    return redirect(request.META.get('HTTP_REFERER', 'items:notifications'))

@login_required
def inbox(request):
    # Get all unique users this user has interacted with
    sent_to = models.DirectMessage.objects.filter(sender=request.user).values_list('recipient', flat=True)
    received_from = models.DirectMessage.objects.filter(recipient=request.user).values_list('sender', flat=True)
    
    # Combined set of unique user IDs
    interacted_user_ids = set(sent_to) | set(received_from)
    
    threads = []
    for other_user_id in interacted_user_ids:
        try:
            other_user = User.objects.get(id=other_user_id)
        except User.DoesNotExist:
            continue
            
        last_msg = models.DirectMessage.objects.filter(
            Q(sender=request.user, recipient=other_user) |
            Q(sender=other_user, recipient=request.user)
        ).order_by('-created_at').first()
        
        unread_count = models.DirectMessage.objects.filter(
            sender=other_user, recipient=request.user, is_read=False
        ).count()
        
        threads.append({
            'user': other_user, 
            'last_message': last_msg, 
            'unread_count': unread_count
        })

    # Sort threads by most recent message
    threads.sort(key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.now(), reverse=True)
    
    return render(request, 'user/inbox.html', {
        'threads': threads, 
        'breadcrumb_label': 'Messages',
        'current_user_profile': request.user.userprofile if hasattr(request.user, 'userprofile') else None
    })

@login_required
def conversation(request, user_id):
    other_user = get_object_or_404(User, id=user_id)
    messages_list = models.DirectMessage.objects.filter(
        Q(sender=request.user, recipient=other_user) |
        Q(sender=other_user, recipient=request.user)
    ).order_by('created_at')
    
    models.DirectMessage.objects.filter(sender=other_user, recipient=request.user, is_read=False).update(is_read=True)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'other_user': {
                'id': other_user.id,
                'name': other_user.username,
                'avatar': other_user.userprofile.avatar.url if hasattr(other_user, 'userprofile') and other_user.userprofile.avatar else None,
                'is_online': True # Placeholder
            },
            'chat_messages': [{
                'id': msg.id,
                'sender': msg.sender_id,
                'content': msg.content,
                'time': msg.created_at.strftime('%I:%M %p, %A'), # '08:40 AM, Today' style
                'is_me': msg.sender == request.user
            } for msg in messages_list]
        })

    return render(request, 'user/conversation.html', {'other_user': other_user, 'chat_messages': messages_list, 'breadcrumb_label': 'Conversation'})

@login_required
@require_http_methods(["POST"])
def send_message_api(request):
    recipient_id = request.POST.get('recipient_id')
    content = request.POST.get('content', '').strip() if request.POST.get('content') else ''
    item_id = request.POST.get('item_id')
    
    if not recipient_id or not content: return JsonResponse({'status': 'error', 'message': 'Missing fields'}, status=400)
    
    try: recipient = User.objects.get(id=recipient_id)
    except User.DoesNotExist: return JsonResponse({'status': 'error', 'message': 'Recipient not found'}, status=404)
    
    if item_id:
        try:
            item = models.Item.objects.get(id=item_id)
            if not (
                request.user == item.owner or request.user.is_staff or
                models.ClaimRequest.objects.filter(item=item, claimer=request.user, status__in=['pending', 'approved', 'completed']).exists()
            ):
                return JsonResponse({'status': 'error', 'message': 'No direct messaging for unapproved items'}, status=403)
        except models.Item.DoesNotExist: pass
    
    message = models.DirectMessage.objects.create(
        sender=request.user, recipient=recipient, content=content, item_id=item_id if item_id else None
    )
    
    return JsonResponse({'status': 'success', 'message_id': message.id, 'created_at': message.created_at.strftime('%b %d, %H:%M')})

# ===============================
# ANALYTICS
# ===============================


@admin_required
def admin_analytics(request):
    total_items = models.Item.objects.count()
    lost_items = models.Item.objects.filter(report_type='lost').count()
    found_items = models.Item.objects.filter(report_type='found').count()
    resolved_items = models.Item.objects.filter(lifecycle_status='resolved').count()
    claimed_items = models.Item.objects.filter(lifecycle_status='claimed').count()
    pending_items = models.Item.objects.filter(verification_status='pending').count()
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    success_rate = 0
    if total_items > 0: success_rate = (resolved_items / total_items) * 100

    # Claim Metrics (KPI: Processing Efficiency)
    claims_total = models.ClaimRequest.objects.count()
    claims_approved = models.ClaimRequest.objects.filter(status__in=['approved', 'completed']).count()
    claims_rejected = models.ClaimRequest.objects.filter(status='rejected').count()
    claim_success_rate = (claims_approved / claims_total * 100) if claims_total > 0 else 0

    # Physical Turnover (KPI: Security Assurance)
    money_items = models.Item.objects.filter(category='Wallet / Money')
    turnover_total = money_items.count()
    turnover_confirmed = money_items.filter(turnover_status='confirmed').count()
    turnover_pending = money_items.filter(turnover_status='pending').count()

    # Hotspot Analysis (KPI: Discovery Heatmap)
    category_data = models.Item.objects.exclude(category='').values('category').annotate(count=Count('id')).order_by('-count')[:8]
    category_stats = []
    for cat in category_data:
        pct = (cat['count'] / total_items * 100) if total_items > 0 else 0
        category_stats.append({'name': cat['category'], 'count': cat['count'], 'percentage': round(pct, 1)})

    location_data = models.Item.objects.exclude(location='').values('location').annotate(count=Count('id')).order_by('-count')[:8]
    location_stats = []
    for loc in location_data:
        pct = (loc['count'] / total_items * 100) if total_items > 0 else 0
        location_stats.append({'name': loc['location'], 'count': loc['count'], 'percentage': round(pct, 1)})

    # Activity Timeline
    monthly_reported = list(models.Item.objects.annotate(month=TruncMonth('date_reported')).values('month').annotate(count=Count('id')).order_by('month'))[-12:]
    monthly_resolved = list(models.Item.objects.filter(lifecycle_status='resolved', date_resolved__isnull=False).annotate(month=TruncMonth('date_resolved')).values('month').annotate(count=Count('id')).order_by('month'))[-12:]

    months_labels = [m['month'].strftime('%b %Y') for m in monthly_reported] if monthly_reported else []
    reported_counts = [m['count'] for m in monthly_reported] if monthly_reported else []
    resolved_counts_map = {m['month'].strftime('%b %Y'): m['count'] for m in monthly_resolved}
    resolved_counts = [resolved_counts_map.get(label, 0) for label in months_labels]

    # User Growth (KPI: Engagement Pulse)
    growth_data = list(User.objects.annotate(date=TruncDate('date_joined')).values('date').annotate(count=Count('id')).order_by('date'))[-14:]
    growth_labels = [d['date'].strftime('%b %d') for d in growth_data]
    growth_counts = [d['count'] for d in growth_data]

    # Resolution Efficiency (KPI: Velocity)
    resolved_with_time = models.Item.objects.filter(lifecycle_status='resolved', date_resolved__isnull=False)
    avg_resolution_days = None
    if resolved_with_time.exists():
        total_days = sum((item.date_resolved - item.date_reported).days for item in resolved_with_time if item.date_resolved and item.date_reported)
        avg_resolution_days = round(total_days / resolved_with_time.count(), 1)

    # Recent Audit Log (KPI: System Integrity)
    recent_activity = models.AuditLog.objects.select_related('user', 'item').all().order_by('-created_at')[:6]

    context = {
        'total_items': total_items, 'lost_items': lost_items, 'found_items': found_items, 'resolved_items': resolved_items,
        'claimed_items': claimed_items, 'pending_items': pending_items,
        'success_rate': success_rate, 'total_users': total_users, 'active_users': active_users, 'avg_resolution_days': avg_resolution_days,
        'claim_success_rate': claim_success_rate, 'claims_total': claims_total,
        'turnover_confirmed': turnover_confirmed, 'turnover_total': turnover_total,
        'category_stats': category_stats, 'location_stats': location_stats, 'months_labels': months_labels,
        'reported_counts': reported_counts, 'resolved_counts': resolved_counts,
        'growth_labels': growth_labels, 'growth_counts': growth_counts,
        'recent_activity': recent_activity,
        'breadcrumb_label': 'KPI Hub'
    }
    return render(request, 'admin/admin_analytics.html', context)



@admin_required
def export_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="lost_and_found_export_{timezone.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Name', 'Description', 'Category', 'Location',
        'Status', 'Reporter', 'Contact Name', 'Contact Email',
        'Date Reported', 'Approved', 'Date Resolved'
    ])

    items = models.Item.objects.all().select_related('owner').order_by('-date_reported')

    status_filter = request.GET.get('status', 'all')
    category_filter = request.GET.get('category', 'all')
    if status_filter != 'all': items = items.filter(lifecycle_status=status_filter)
    if category_filter != 'all': items = items.filter(category=category_filter)

    for item in items:
        writer.writerow([
            item.id, item.name, item.description, item.category, item.location,
            item.get_status_display(), item.owner.username if item.owner else 'N/A',
            item.contact_name, item.contact_email,
            item.date_reported.strftime('%Y-%m-%d %H:%M') if item.date_reported else '',
            'Yes' if item.is_approved else 'No',
            item.date_resolved.strftime('%Y-%m-%d %H:%M') if item.date_resolved else '',
        ])
    return response

@admin_required
def export_users_csv(request):
    """
    Exports the User Directory to a standardized CSV format.
    Ensures backend logic aligns with the 'Download CSV' UI directive.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="users_export_{timezone.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Username', 'Email', 'Is Staff', 'Role', 'Date Joined'])

    users = User.objects.all().select_related('userprofile').order_by('-date_joined')
    
    for user in users:
        role = 'Student'
        try:
            role = user.userprofile.get_user_type_display()
        except:
            if user.is_staff: role = 'Admin'
            
        writer.writerow([
            user.username,
            user.email,
            'Yes' if user.is_staff else 'No',
            role,
            user.date_joined.strftime('%Y-%m-%d %H:%M')
        ])

    return response

@admin_required
def trash_view(request):
    deleted_items = models.Item.all_objects.filter(is_deleted=True).order_by('-deleted_at')
    return render(request, 'admin/trash.html', {'items': deleted_items, 'breadcrumb_label': 'Trash Bin'})

@require_http_methods(['GET', 'POST'])
def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('items:item_list')
    else:
        form = CustomUserCreationForm()
    
    user_type_options = [('student', 'Student'), ('staff', 'Staff')]
    
    return render(request, 'user/signup.html', {
        'form': form,
        'user_type_options': user_type_options,
    })

@login_required
def restore_item(request, pk):
    # Use all_objects to find soft-deleted items
    item = get_object_or_404(models.Item.all_objects, pk=pk)
    if not item.is_deleted:
        messages.warning(request, "This item has not been deleted.")
        return redirect('items:trash')
    
    if not (item.owner == request.user or request.user.userprofile.is_admin):
        messages.error(request, "You don't have permission to restore this item.")
        return redirect('items:trash')
        
    item.is_deleted = False
    item.deleted_at = None
    item.save()
    
    if item.owner and item.owner != request.user:
        NotificationService.send_status_notification(item.owner, item, 'item_restored')

    messages.success(request, f'Item "{item.name}" has been restored.')
    return redirect('items:trash')






@admin_required
def admin_claims(request):
    claims = models.ClaimRequest.objects.all().select_related('item', 'claimer').order_by('-created_at')
    status_filter = request.GET.get('status', 'pending')
    if status_filter != 'all':
        claims = claims.filter(status=status_filter)
        
    return render(request, 'admin/admin_claims.html', {
        'claims': claims,
        'status_filter': status_filter
    })

@login_required
@transaction.atomic
def mark_item_resolved(request, item_id):
    item = get_object_or_404(models.Item, id=item_id)
    if item.owner != request.user and not (request.user.is_staff or request.user.userprofile.is_admin):
        messages.error(request, "You are not authorized to close this report.")
        return redirect(item.get_absolute_url())

    item.lifecycle_status = 'resolved'
    item.date_resolved = timezone.now()
    item.save()

    models.AuditLog.objects.create(
        user=request.user, action="Direct Resolution", item=item,
        details=f"Item '{item.name}' marked as resolved/returned by @{request.user.username}."
    )

    # Cross-resolve any linked matches so both pair items are removed from registry
    linked_matches = models.MatchSuggestion.objects.filter(
        Q(lost_item=item) | Q(found_item=item),
        status='linked'
    )
    for match in linked_matches:
        matched_item = match.found_item if match.lost_item == item else match.lost_item
        if matched_item.lifecycle_status != 'resolved':
            matched_item.lifecycle_status = 'resolved'
            matched_item.date_resolved = timezone.now()
            matched_item.save()
            
            # Notify the matched item owner automatically
            if matched_item.owner:
                NotificationService.send_status_notification(
                    matched_item.owner, matched_item, 'item_resolved'
                )
            
            models.AuditLog.objects.create(
                user=request.user, action="Matched Item Auto-Resolved", item=matched_item,
                details=f"Item '{matched_item.name}' automatically resolved because its linked match '{item.name}' was directly resolved."
            )

    messages.success(request, f"Item has been marked as resolved!")
    return redirect(item.get_absolute_url())

@admin_required
def empty_trash(request):
    if request.method == 'POST':
        deleted_count = models.Item.all_objects.filter(is_deleted=True).count()
        models.Item.all_objects.filter(is_deleted=True).delete()
        
        models.AuditLog.objects.create(
            user=request.user, action="Empty Trash",
            details=f"Admin @{request.user.username} permanently cleared {deleted_count} items from the trash bin."
        )
        messages.success(request, f"Trash bin cleared! {deleted_count} items permanently deleted.")
    return redirect('items:trash')

@admin_required
def bulk_restore(request):
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        items = models.Item.all_objects.filter(id__in=item_ids, is_deleted=True)
        count = items.count()
        
        for item in items:
            item.is_deleted = False
            item.deleted_at = None
            item.save()
            if item.owner and item.owner != request.user:
                NotificationService.send_status_notification(item.owner, item, 'item_restored')
        
        models.AuditLog.objects.create(
            user=request.user, action="Bulk Restore",
            details=f"Admin @{request.user.username} bulk-restored {count} items from trash."
        )
        messages.success(request, f"Successfully restored {count} items.")
    return redirect('items:trash')

@admin_required
def system_logs(request):
    """
    Unified view for administrators to audit all major system events.
    """
    logs = models.AuditLog.objects.select_related('user').all().order_by('-created_at')
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(logs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'admin/system_logs.html', {
        'page_obj': page_obj,
        'breadcrumb_label': 'Activity History'
    })

@admin_required
def confirm_turnover(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(models.Item, id=item_id)
        if item.is_money and item.turnover_status == 'pending':
            item.turnover_status = 'confirmed'
            item.save()
            
            models.AuditLog.objects.create(
                user=request.user, action="Confirmed Turnover", item=item,
                details=f"Admin confirmed physical receipt of the found money for '{item.name}'."
            )
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'new_status': 'confirmed'})
            
            messages.success(request, "Physical turnover confirmed!")
    return redirect(request.META.get('HTTP_REFERER', 'items:item_detail', pk=item_id))


def error_404_view(request, exception):
    return render(request, '404.html', status=404)

def error_500_view(request):
    return render(request, '500.html', status=500)
