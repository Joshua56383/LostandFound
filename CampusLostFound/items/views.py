from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.db.models import Q, Count
from django.db.models.functions import TruncMonth, TruncWeek
from . import models
from . import ai_service
from .forms import ItemForm, UserUpdateForm, UserProfileForm, ClaimForm
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponseForbidden, Http404, JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
import os
import csv
import secrets
import string
from functools import wraps

def serve_private_file(request, file_path):
    """
    Serve files with conditional access control.
    - Public: Images of approved items (is_approved=True)
    - Private: User documents, unapproved items, or system files (Owner/Admin only)
    """
    # Security: prevent directory traversal
    normalized_path = os.path.normpath(file_path).lstrip(os.sep)
    
    # Try finding the file in MEDIA_ROOT first (where items are stored)
    full_path = os.path.join(settings.MEDIA_ROOT, normalized_path)
    if not os.path.exists(full_path):
        # Fallback to PRIVATE_STORAGE_ROOT
        full_path = os.path.join(settings.PRIVATE_STORAGE_ROOT, normalized_path)

    # Ensure the path is within valid storage roots
    is_in_media = os.path.abspath(full_path).startswith(os.path.abspath(str(settings.MEDIA_ROOT)))
    is_in_private = os.path.abspath(full_path).startswith(os.path.abspath(str(settings.PRIVATE_STORAGE_ROOT)))
    
    if not (is_in_media or is_in_private):
        return HttpResponseForbidden("Access Denied")

    if not os.path.exists(full_path):
        print(f"DEBUG VIEW: File NOT found on disk at: {full_path}")
        raise Http404("File not found")

    # --- Access Control Logic ---
    
    # 0. Failsafe: Get or create profile if authenticated
    profile = None
    if request.user.is_authenticated:
        try:
            profile = request.user.userprofile
        except models.UserProfile.DoesNotExist:
            profile = models.UserProfile.objects.create(user=request.user)

    # 1. Check if the file is an Item image
    # Note: get_role_upload_path saves to 'template/<role>/<unique_name>'
    # Use cross-platform check for the 'template' directory
    path_parts = normalized_path.split(os.sep)
    if 'template' in path_parts or 'template' in normalized_path.replace('\\', '/').split('/'):
        filename = os.path.basename(normalized_path)
        # Search for the item by image filename
        item = models.Item.objects.filter(image__icontains=filename).first()
        
        if item:
            # PUBLIC ACCESS: If the item is approved, anyone can see the image
            if item.is_approved:
                return FileResponse(open(full_path, 'rb'))
            
            # PRIVATE ACCESS: Only owner or admin for unapproved items
            if request.user.is_authenticated and profile:
                if profile.is_admin or item.owner == request.user:
                    return FileResponse(open(full_path, 'rb'))
                
        # Also check for UploadedFile model if applicable
        uploaded_file = models.UploadedFile.objects.filter(file__icontains=filename).first()
        if uploaded_file and request.user.is_authenticated and profile:
            if profile.is_admin or uploaded_file.uploader == request.user:
                return FileResponse(open(full_path, 'rb'))

    # 2. General Auth-required check for everything else
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Authentication Required")

    # Final RBAC Fallback (Superadmin always has access)
    if profile and profile.is_superadmin:
        return FileResponse(open(full_path, 'rb'))

    return HttpResponseForbidden("Access Denied")

def role_required(allowed_roles):
    """
    Decorator for views that checks whether a user has a specific role.
    Supports role names: 'student', 'staff', 'admin', 'superadmin'.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            # 1. Superusers always have full access
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            try:
                profile = request.user.userprofile
            except models.UserProfile.DoesNotExist:
                # Failsafe: Create missing profile
                profile = models.UserProfile.objects.create(user=request.user)

            # 2. Check if user satisfies any of the required roles
            user_has_role = False
            
            if 'superadmin' in allowed_roles and profile.is_superadmin:
                user_has_role = True
            elif ('admin' in allowed_roles or 'staff' in allowed_roles) and profile.is_admin:
                user_has_role = True
            elif profile.user_type in allowed_roles:
                user_has_role = True
            elif not allowed_roles: # Open to any authenticated user if no roles specified
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

def create_notification(recipient, item, status_trigger):
    """Call Gemini to generate a message and save a Notification."""
    message = ai_service.generate_notification_message(item, status_trigger)
    models.Notification.objects.create(
        recipient=recipient,
        message=message,
        related_item=item,
        status_trigger=status_trigger
    )

def find_matches(new_item):
    """
    Search for potential matches for a newly reported item.
    - Opposite status (lost vs found)
    - Same category
    - Case-insensitive overlap in name or description
    """
    opposite_status = 'found' if new_item.status == 'lost' else 'lost'
    
    # 1. Start with opposite status and same category
    potential_matches = models.Item.objects.filter(
        status=opposite_status,
        category=new_item.category,
        is_approved=True # Only match against approved items
    ).exclude(id=new_item.id)
    
    matches = []
    
    # Simple keyword-based matching for now
    name_words = set(new_item.name.lower().split())
    
    for potential in potential_matches:
        pot_name_words = set(potential.name.lower().split())
        
        # Check for word overlap in names
        if name_words & pot_name_words:
            matches.append(potential)
            continue
            
        # Check if new item name is in potential's description or vice versa
        if new_item.name.lower() in potential.description.lower() or \
           potential.name.lower() in new_item.description.lower():
            matches.append(potential)
            
    return matches

@login_required
def dashboard(request):
    # 1. Consolidated System Stats (Single Query)
    stats = models.Item.objects.aggregate(
        total=Count('id'),
        lost=Count('id', filter=Q(status='lost')),
        found=Count('id', filter=Q(status='found')),
        claimed=Count('id', filter=Q(status='claimed')),
        pending=Count('id', filter=Q(is_approved=False))
    )
    
    total_items = stats['total']
    success_rate = int((stats['claimed'] / total_items) * 100) if total_items > 0 else 0

    # 2. User Stats (Single Query)
    user_stats = models.Item.objects.filter(owner=request.user).aggregate(
        total=Count('id'),
        resolved=Count('id', filter=Q(status='claimed'))
    )

    # 3. Filtering logic
    q = request.GET.get('q', '')
    status_filter = request.GET.get('status', 'all')
    category_filter = request.GET.get('category', 'all')
    approval_filter = request.GET.get('approval', 'all')
    
    # Robust staff/admin check
    is_staff = (request.user.is_staff or 
               request.user.userprofile.is_admin)

    if is_staff:
        items_query = models.Item.objects.all().order_by('-date_reported')
        pending_claims = models.ClaimRequest.objects.filter(status='pending').order_by('-created_at')
        template = 'user/dashboard.html'
    else:
        items_query = models.Item.objects.filter(owner=request.user).order_by('-date_reported')
        pending_claims = models.ClaimRequest.objects.filter(item__owner=request.user, status='pending').order_by('-created_at')
        template = 'user/user_dashboard.html'
    
    if q:
        items_query = items_query.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
        
    if status_filter != 'all':
        items_query = items_query.filter(status=status_filter)
        
    if category_filter != 'all':
        items_query = items_query.filter(category=category_filter)

    # Approval filter (admin/staff only)
    if is_staff and approval_filter != 'all':
        if approval_filter == 'pending':
            items_query = items_query.filter(is_approved=False)
        elif approval_filter == 'approved':
            items_query = items_query.filter(is_approved=True)
        
    # Pagination
    paginator = Paginator(items_query, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Unique categories for filter
    categories = models.Item.objects.exclude(category='').values_list('category', flat=True).distinct().order_by('category')

    context = {
        'total_items': total_items,
        'lost_count': stats['lost'],
        'found_count': stats['found'],
        'claimed_count': stats['claimed'],
        'pending_count': stats['pending'],
        'success_rate': success_rate,
        'items': page_obj,
        'pending_claims': pending_claims,
        'q': q,
        'status_filter': status_filter,
        'category_filter': category_filter,
        'approval_filter': approval_filter,
        'categories': categories,
        'user_total': user_stats['total'],
        'user_resolved': user_stats['resolved'],
    }
        
    return render(request, template, context)


def item_list(request):
    # query params
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', 'all')
    location = request.GET.get('location', 'all')
    tab = request.GET.get('tab', 'all')

    # Public feed: only show approved items
    items = models.Item.objects.filter(is_approved=True)

    if q:
        items = items.filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )

    if category and category != 'all':
        items = items.filter(category=category)

    if location and location != 'all':
        items = items.filter(location=location)

    if tab in ['lost', 'found']:
        items = items.filter(status=tab)

    items = items.order_by('-date_reported')

    # Pagination
    paginator = Paginator(items, 10) # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # counts only for approved items in public feed
    approved_items = models.Item.objects.filter(is_approved=True)
    total_count = approved_items.count()
    lost_count = approved_items.filter(status='lost').count()
    found_count = approved_items.filter(status='found').count()

    categories = approved_items.exclude(category='').order_by('category').values_list('category', flat=True).distinct()
    locations = approved_items.exclude(location='').order_by('location').values_list('location', flat=True).distinct()

    context = {
        'items': page_obj, # Use page_obj instead of all items
        'q': q,
        'category': category,
        'location': location,
        'tab': tab,
        'total_count': total_count,
        'lost_count': lost_count,
        'found_count': found_count,
        'categories': categories,
        'locations': locations,
    }

    return render(request, 'item/item_list.html', context)


@login_required
def report_item(request, status=None):
    """
    Unified view for reporting lost or found items.
    If status is not provided, it defaults to 'lost' or can be chosen in the form.
    """
    # handle both legacy 'add/' (no status) and 'report/<status>/'
    active_status = status if status in ['lost', 'found'] else 'lost'
    
    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            # Auto-approve for staff, pending for regular users
            item.is_approved = (request.user.is_staff or 
                               request.user.userprofile.user_type in ['admin', 'superadmin'])
            item.save()
            
            # 1. Send "Report Received" notification to the owner
            trigger = 'lost_reported' if item.status == 'lost' else 'found_reported'
            create_notification(request.user, item, trigger)
            
            # 2. Check for matches (notifying the new owner immediately)
            matches = find_matches(item)
            if matches:
                create_notification(request.user, item, 'match_detected')
                
                # If auto-approved, notify existing match owners
                if item.is_approved:
                    for match in matches:
                        if match.owner:
                            create_notification(match.owner, match, 'match_detected')

            # 3. Notify Admins about new submission
            for admin_user in User.objects.filter(is_staff=True):
                if admin_user != request.user:
                    create_notification(admin_user, item, trigger)
                
            # 4. AI Image Tagging (Phase 3)
            if item.image:
                try:
                    tags = ai_service.extract_image_tags(item.image.path)
                    if tags:
                        item.ai_tags = tags
                        item.save(update_fields=['ai_tags'])
                except Exception as e:
                    print(f"AI Tagging Error: {e}")

            if item.is_approved:
                messages.success(request, f'"{item.name}" reported and approved.')
            else:
                messages.info(request, f'"{item.name}" reported. It will appear publicly after admin approval.')

            return redirect('items:item_list')
    else:
        form = ItemForm(initial={'status': active_status})
    
    return render(request, 'item/add_item.html', {
        'form': form, 
        'report_type': active_status,
        'title': f'Report {active_status.capitalize()} Item'
    })


def item_detail(request, pk):
    item = get_object_or_404(models.Item, pk=pk)
    
    # AI Match Suggestions (Phase 3)
    ai_suggestions = []
    if item.ai_tags and item.status in ['lost', 'found']:
        opposite_status = 'found' if item.status == 'lost' else 'lost'
        tag_list = [t.strip().lower() for t in item.ai_tags.split(',') if t.strip()]
        
        if tag_list:
            # Simple keyword search in ai_tags of opposite items
            query = Q()
            for tag in tag_list[:3]: # Use top 3 tags for performance
                query |= Q(ai_tags__icontains=tag)
            
            ai_suggestions = models.Item.objects.filter(
                status=opposite_status,
                is_approved=True
            ).filter(query).exclude(id=item.id)[:4]

    return render(request, 'item/item_detail.html', {
        'item': item,
        'ai_suggestions': ai_suggestions
    })

@login_required
def profile(request):
    user_items = models.Item.objects.filter(owner=request.user).order_by('-date_reported')
    user_items_resolved_count = user_items.filter(status='claimed').count()
    return render(request, 'user/profile.html', {
        'user_items': user_items,
        'user_items_resolved_count': user_items_resolved_count
    })


@login_required
def claim_item(request, item_id):
    """Allow owners or finders to mark an item as claimed/resolved."""
    item = get_object_or_404(models.Item, id=item_id)
    if not item:
        messages.error(request, "Item not found.")
        return redirect('items:dashboard')
        
    if item.owner != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to resolve this item.")
        return redirect('items:dashboard')
        
    item.status = 'claimed'
    item.save()
    
    # Send Notification to the owner
    create_notification(item.owner, item, 'resolved')
    
    messages.success(request, f"Successfully marked '{item.name}' as resolved!")
    return redirect('items:dashboard')
@login_required
def edit_profile(request):
    profile, created = models.UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('items:profile')
    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = UserProfileForm(instance=profile)
    
    context = {
        'form': user_form,
        'profile_form': profile_form
    }
    return render(request, 'user/edit_profile.html', context)

@login_required
def edit_item(request, pk):
    item = get_object_or_404(models.Item, pk=pk)
    
    # Handle quick status update from dashboard dropdown
    quick_status = request.GET.get('quick_status')
    if quick_status:
        if quick_status in ['lost', 'found', 'claimed']:
            old_status = item.status
            item.status = quick_status
            item.save()
            
            # Send AI notification on status change
            if old_status != quick_status and item.owner:
                status_map = {
                    'claimed': 'claim_approved',
                    'lost': 'lost_reported',
                    'found': 'found_reported',
                }
                trigger = status_map.get(quick_status, f'status_changed_to_{quick_status}')
                create_notification(item.owner, item, trigger)
            
            messages.success(request, f'Status of "{item.name}" updated to {quick_status}.')
        return redirect('items:dashboard')

    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'Item "{item.name}" updated successfully.')
        else:
            messages.error(request, 'Failed to update item. Please check the form.')
    return redirect('items:dashboard')

@login_required
def delete_item(request, pk):
    try:
        item = models.Item.objects.get(pk=pk)
    except models.Item.DoesNotExist:
        messages.info(request, "Item already deleted or does not exist.")
        return redirect('items:dashboard')

    # Ownership check: only the item owner or staff can delete
    if item.owner != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to delete this item.")
        return redirect('items:dashboard')

    if request.method == 'POST':
        item_name = item.name
        # Soft delete instead of hard delete
        item.soft_delete()
        messages.success(request, f'Item "{item_name}" has been removed.')
    return redirect('items:dashboard')


@superadmin_required
def user_directory(request):
    
    users = User.objects.all().order_by('-date_joined')
    q = request.GET.get('q', '')
    if q:
        users = users.filter(
            Q(username__icontains=q) | 
            Q(email__icontains=q) | 
            Q(first_name__icontains=q) | 
            Q(last_name__icontains=q)
        )
    
    context = {
        'users': users,
        'q': q,
    }
    return render(request, 'admin/user_directory.html', context)


@superadmin_required
def admin_analytics(request):
    """Analytics dashboard with real data."""
    total_items = models.Item.objects.count()
    lost_items = models.Item.objects.filter(status='lost').count()
    found_items = models.Item.objects.filter(status='found').count()
    resolved_items = models.Item.objects.filter(status='claimed').count()
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    success_rate = 0
    if total_items > 0:
        success_rate = (resolved_items / total_items) * 100

    # Category distribution (real data)
    category_data = (
        models.Item.objects
        .exclude(category='')
        .values('category')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )
    # Calculate percentages
    category_stats = []
    for cat in category_data:
        pct = (cat['count'] / total_items * 100) if total_items > 0 else 0
        category_stats.append({
            'name': cat['category'],
            'count': cat['count'],
            'percentage': round(pct, 1),
        })

    # Location hotspots (real data)
    location_data = (
        models.Item.objects
        .exclude(location='')
        .values('location')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )
    location_stats = []
    for loc in location_data:
        pct = (loc['count'] / total_items * 100) if total_items > 0 else 0
        location_stats.append({
            'name': loc['location'],
            'count': loc['count'],
            'percentage': round(pct, 1),
        })

    # Monthly activity trends (real data)
    monthly_reported = list(
        models.Item.objects
        .annotate(month=TruncMonth('date_reported'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )[-12:]  # Last 12 months

    monthly_resolved = list(
        models.Item.objects
        .filter(status='claimed', date_resolved__isnull=False)
        .annotate(month=TruncMonth('date_resolved'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )[-12:]

    # Convert to lists for Chart.js
    months_labels = [m['month'].strftime('%b %Y') for m in monthly_reported] if monthly_reported else []
    reported_counts = [m['count'] for m in monthly_reported] if monthly_reported else []
    resolved_counts_map = {m['month'].strftime('%b %Y'): m['count'] for m in monthly_resolved}
    resolved_counts = [resolved_counts_map.get(label, 0) for label in months_labels]

    # Average resolution time
    resolved_with_time = models.Item.objects.filter(
        status='claimed', date_resolved__isnull=False
    )
    avg_resolution_days = None
    if resolved_with_time.exists():
        total_days = sum(
            (item.date_resolved - item.date_reported).days
            for item in resolved_with_time
            if item.date_resolved and item.date_reported
        )
        avg_resolution_days = round(total_days / resolved_with_time.count(), 1)

    context = {
        'total_items': total_items,
        'lost_items': lost_items,
        'found_items': found_items,
        'resolved_items': resolved_items,
        'success_rate': success_rate,
        'total_users': total_users,
        'active_users': active_users,
        'avg_resolution_days': avg_resolution_days,
        'category_stats': category_stats,
        'location_stats': location_stats,
        'months_labels': months_labels,
        'reported_counts': reported_counts,
        'resolved_counts': resolved_counts,
    }
    return render(request, 'admin/admin_analytics.html', context)


@superadmin_required
def audit_logs(request):
    
    # Use UserLoginLog model for actual data
    logs = models.UserLoginLog.objects.all().order_by('-timestamp')[:50]
    
    context = {
        'logs': logs,
    }
    return render(request, 'admin/audit_logs.html', context)


@superadmin_required
def toggle_user_active(request, user_id):
    if request.method == 'POST':
        user_to_toggle = get_object_or_404(User, id=user_id)
        if user_to_toggle != request.user: # Prevent self-deactivation
            user_to_toggle.is_active = not user_to_toggle.is_active
            user_to_toggle.save()
            status = "activated" if user_to_toggle.is_active else "deactivated"
            messages.success(request, f'User {user_to_toggle.username} has been {status}.')
        else:
            messages.error(request, "You cannot deactivate your own account.")
    return redirect('items:user_directory')

@superadmin_required
def toggle_user_role(request, user_id):
    if request.method == 'POST':
        user_to_toggle = get_object_or_404(User, id=user_id)
        if user_to_toggle != request.user:
            user_to_toggle.is_staff = not user_to_toggle.is_staff
            user_to_toggle.save()
            role = "Admin" if user_to_toggle.is_staff else "Standard"
            messages.success(request, f'User {user_to_toggle.username} role updated to {role}.')
        else:
            messages.error(request, "You cannot change your own role.")
    return redirect('items:user_directory')

@superadmin_required
def delete_user_admin(request, user_id):
    if request.method == 'POST':
        user_to_delete = get_object_or_404(User, id=user_id)
        if user_to_delete != request.user:
            username = user_to_delete.username
            user_to_delete.delete()
            messages.success(request, f'User {username} has been permanently deleted.')
        else:
            messages.error(request, "You cannot delete your own account.")
    return redirect('items:user_directory')

@superadmin_required
def reset_user_password(request, user_id):
    if request.method == 'POST':
        user_to_reset = get_object_or_404(User, id=user_id)
        # Generate a secure random password
        alphabet = string.ascii_letters + string.digits + '!@#$%'
        temp_pass = ''.join(secrets.choice(alphabet) for _ in range(12))
        user_to_reset.set_password(temp_pass)
        user_to_reset.save()
        messages.success(request, f'Password for {user_to_reset.username} has been reset. Temporary password: {temp_pass}')
    return redirect('items:user_directory')



@admin_required
def approve_item(request, item_id):
    """Admin action to approve a pending item for the public feed."""
    
    try:
        item = models.Item.objects.get(id=item_id)
    except models.Item.DoesNotExist:
        messages.info(request, "Item already processed or does not exist.")
        return redirect('items:dashboard')

    if not item.is_approved:
        item.is_approved = True
        item.save()
        # 1. Notify the item owner
        if item.owner:
            create_notification(item.owner, item, 'item_approved')
        
        # 2. Notify owners of matching items
        matches = find_matches(item)
        for match in matches:
            if match.owner:
                create_notification(match.owner, match, 'match_detected')

        # Audit Log
        models.AuditLog.objects.create(
            user=request.user,
            action="Approved Item",
            item=item,
            details=f"Item '{item.name}' approved manually by @{request.user.username}."
        )

        messages.success(request, f'"{item.name}" has been approved and is now visible in the public feed.')
    return redirect('items:dashboard')


@admin_required
def reject_item(request, item_id):
    """Admin action to reject and delete a pending item."""

    try:
        item = models.Item.objects.get(id=item_id)
    except models.Item.DoesNotExist:
        messages.info(request, "Item already rejected or does not exist.")
        return redirect('items:dashboard')

    item_name = item.name
    owner = item.owner
    # Notify the owner before deleting
    if owner:
        create_notification(owner, item, 'item_rejected')
        
    # Audit Log
    models.AuditLog.objects.create(
        user=request.user,
        action="Rejected Item",
        details=f"Item '{item_name}' (ID: {item.id}) rejected and deleted by @{request.user.username}."
    )
    
    item.delete()
    messages.success(request, f'"{item_name}" has been rejected and removed.')
    return redirect('items:dashboard')

@login_required
def get_notifications(request):
    """API endpoint to fetch unread notifications for the user."""
    notifications = request.user.notifications.filter(is_read=False)[:5]
    data = [{
        'id': n.id,
        'message': n.message,
        'time_ago': n.created_at.strftime('%b %d, %H:%M'),
        'item_id': n.related_item.id if n.related_item else None
    } for n in notifications]
    return JsonResponse({'notifications': data})

@login_required
def mark_notification_read(request, notif_id):
    """API endpoint to mark a specific notification as read."""
    if request.method == 'POST':
        try:
            notif = request.user.notifications.get(id=notif_id)
            notif.is_read = True
            notif.save()
            return JsonResponse({'status': 'success'})
        except models.Notification.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Not found'}, status=404)
    return JsonResponse({'status': 'error'}, status=400)
@login_required
def submit_claim(request, item_id):
    item = get_object_or_404(models.Item, id=item_id)
    
    # Check if user already claimed this item
    if models.ClaimRequest.objects.filter(item=item, claimer=request.user).exists():
        messages.warning(request, "You have already submitted a claim for this item.")
        return redirect('items:item_detail', pk=item.id)

    if request.method == 'POST':
        form = ClaimForm(request.POST)
        if form.is_valid():
            claim = form.save(commit=False)
            claim.item = item
            claim.claimer = request.user
            claim.save()
            
            # Notify item owner
            if item.owner:
                create_notification(item.owner, item, 'claim_submitted')
                
                # Start in-app message thread (Phase 3)
                models.DirectMessage.objects.create(
                    sender=request.user,
                    recipient=item.owner,
                    item=item,
                    content=f"SYSTEM: User @{request.user.username} has submitted a claim for '{item.name}'.\n\nMESSAGE: {claim.message}"
                )
            
            # Notify admins
            for admin in User.objects.filter(is_staff=True):
                create_notification(admin, item, 'claim_submitted')
                
            messages.success(request, "Claim submitted successfully! A secure message thread has been started with the finder.")
            return redirect('items:item_detail', pk=item.id)
    else:
        form = ClaimForm()
    
    return render(request, 'item/claim_form.html', {'form': form, 'item': item})

@login_required
def approve_claim(request, claim_id):
    claim = get_object_or_404(models.ClaimRequest, id=claim_id)
    item = claim.item
    
    # Permission check: Only item owner or staff can approve
    if item.owner != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to approve this claim.")
        return redirect('items:dashboard')
        
    # Mark claim as approved
    claim.status = 'approved'
    claim.save()
    
    # Mark item as claimed
    item.status = 'claimed'
    item.save()
    
    # Reject other pending claims for this same item
    models.ClaimRequest.objects.filter(item=item, status='pending').exclude(id=claim.id).update(status='rejected')
    
    # Notify claimer
    create_notification(claim.claimer, item, 'claim_approved')
    
    # Audit Log
    models.AuditLog.objects.create(
        user=request.user,
        action="Approved Claim",
        item=item,
        details=f"Claim approved for item '{item.name}' by @{request.user.username}."
    )
    
    messages.success(request, f"Claim for '{item.name}' approved successfully!")
    return redirect('items:dashboard')

@login_required
def reject_claim(request, claim_id):
    claim = get_object_or_404(models.ClaimRequest, id=claim_id)
    item = claim.item
    
    # Permission check: Only item owner or staff can reject
    if item.owner != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to reject this claim.")
        return redirect('items:dashboard')
        
    claim.status = 'rejected'
    claim.save()
    
    # Notify claimer
    create_notification(claim.claimer, item, 'claim_rejected')
    
    messages.info(request, f"Claim for '{item.name}' rejected.")
    return redirect('items:dashboard')


# =====================================================
# NEW FEATURES: Analytics API, CSV Export, Bulk Actions
# =====================================================

@superadmin_required
def analytics_api(request):
    """JSON API endpoint for analytics chart data."""
    # Monthly activity trends
    monthly_reported = list(
        models.Item.objects
        .annotate(month=TruncMonth('date_reported'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )[-12:]

    monthly_resolved = list(
        models.Item.objects
        .filter(status='claimed', date_resolved__isnull=False)
        .annotate(month=TruncMonth('date_resolved'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )[-12:]

    data = {
        'months': [m['month'].strftime('%b %Y') for m in monthly_reported],
        'reported': [m['count'] for m in monthly_reported],
        'resolved': {
            m['month'].strftime('%b %Y'): m['count'] for m in monthly_resolved
        },
        'categories': list(
            models.Item.objects
            .exclude(category='')
            .values('category')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        ),
        'locations': list(
            models.Item.objects
            .exclude(location='')
            .values('location')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        ),
    }
    return JsonResponse(data)


@admin_required
def export_csv(request):
    """Export all items as a CSV file."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="lost_and_found_export_{timezone.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Name', 'Description', 'Category', 'Location',
        'Status', 'Reporter', 'Contact Name', 'Contact Email',
        'Date Reported', 'Approved', 'Date Resolved'
    ])

    items = models.Item.objects.all().select_related('owner').order_by('-date_reported')

    # Apply same filters as dashboard if provided
    status_filter = request.GET.get('status', 'all')
    category_filter = request.GET.get('category', 'all')
    if status_filter != 'all':
        items = items.filter(status=status_filter)
    if category_filter != 'all':
        items = items.filter(category=category_filter)

    for item in items:
        writer.writerow([
            item.id,
            item.name,
            item.description,
            item.category,
            item.location,
            item.get_status_display(),
            item.owner.username if item.owner else 'N/A',
            item.contact_name,
            item.contact_email,
            item.date_reported.strftime('%Y-%m-%d %H:%M') if item.date_reported else '',
            'Yes' if item.is_approved else 'No',
            item.date_resolved.strftime('%Y-%m-%d %H:%M') if item.date_resolved else '',
        ])

    return response


@admin_required
def bulk_approve(request):
    """Bulk approve multiple pending items."""
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        if item_ids:
            items = models.Item.objects.filter(id__in=item_ids, is_approved=False)
            count = items.count()
            for item in items:
                item.is_approved = True
                item.save()
                # Audit Log
                models.AuditLog.objects.create(
                    user=request.user,
                    action="Bulk Approved Item",
                    item=item,
                    details="Item approved via admin bulk action."
                )
                # Notify item owner
                if item.owner:
                    create_notification(item.owner, item, 'item_approved')
                # Check for matches
                matches = find_matches(item)
                for match in matches:
                    if match.owner:
                        create_notification(match.owner, match, 'match_detected')
            messages.success(request, f'{count} item(s) approved successfully.')
        else:
            messages.warning(request, 'No items selected.')
    return redirect('items:dashboard')


@admin_required
def bulk_reject(request):
    """Bulk reject and soft-delete multiple items."""
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        if item_ids:
            items = models.Item.objects.filter(id__in=item_ids)
            count = items.count()
            for item in items:
                if item.owner:
                    create_notification(item.owner, item, 'item_rejected')
                # Audit Log
                models.AuditLog.objects.create(
                    user=request.user,
                    action="Bulk Rejected Item",
                    item=item,
                    details="Item rejected and soft-deleted via admin bulk action."
                )
                item.soft_delete()
            messages.success(request, f'{count} item(s) rejected and removed.')
        else:
            messages.warning(request, 'No items selected.')
    return redirect('items:dashboard')


@login_required
def renew_item(request, pk):
    """Extend an item's expiry date by 30 days."""
    item = get_object_or_404(models.Item, pk=pk)
    if item.owner != request.user and not request.user.is_staff:
        messages.error(request, "You don't have permission to renew this item.")
        return redirect('items:dashboard')

    item.renew(days=30)
    messages.success(request, f'"{item.name}" renewed for another 30 days.')
    return redirect('items:dashboard')


@admin_required
def trash_view(request):
    """View soft-deleted items (admin only)."""
    deleted_items = models.Item.all_objects.filter(is_deleted=True).order_by('-deleted_at')
    return render(request, 'admin/trash.html', {'deleted_items': deleted_items})


@admin_required
def restore_item(request, pk):
    """Restore a soft-deleted item."""
    if request.method == 'POST':
        try:
            item = models.Item.all_objects.get(pk=pk, is_deleted=True)
            item.restore()
            # Audit Log
            models.AuditLog.objects.create(
                user=request.user,
                action="Restored Item",
                item=item,
                details=f"Item restored from trash by @{request.user.username}."
            )
            messages.success(request, f'"{item.name}" has been restored.')
        except models.Item.DoesNotExist:
            messages.error(request, "Item not found in trash.")
    return redirect('items:trash')


# =====================================================
# IN-APP MESSAGING VIEWS (Phase 3)
# =====================================================

@login_required
def inbox(request):
    """View to list all conversations."""
    # Get all unique users the current user has messaged or received from
    sent = models.DirectMessage.objects.filter(sender=request.user).values_list('recipient', flat=True)
    received = models.DirectMessage.objects.filter(recipient=request.user).values_list('sender', flat=True)
    
    unique_user_ids = set(list(sent) + list(received))
    unique_users = User.objects.filter(id__in=unique_user_ids)
    
    # Enrich users with last message and unread count
    conversations = []
    
    # Pre-fetch last messages for all unique users in a optimized way
    for user in unique_users:
        last_msg = models.DirectMessage.objects.filter(
            (Q(sender=request.user) & Q(recipient=user)) |
            (Q(sender=user) & Q(recipient=request.user))
        ).select_related('sender', 'recipient', 'item').last()
        
        unread_count = models.DirectMessage.objects.filter(
            sender=user,
            recipient=request.user,
            is_read=False
        ).count()
        
        conversations.append({
            'user': user,
            'last_message': last_msg,
            'unread_count': unread_count
        })
    
    # Sort by last message time
    conversations.sort(key=lambda x: x['last_message'].created_at if x['last_message'] else timezone.now(), reverse=True)
    
    return render(request, 'user/inbox.html', {'conversations': conversations})


@login_required
def conversation(request, user_id):
    """View a specific back-and-forth chat."""
    other_user = get_object_or_404(User, id=user_id)
    
    # Mark messages as read
    models.DirectMessage.objects.filter(
        sender=other_user,
        recipient=request.user,
        is_read=False
    ).update(is_read=True)
    
    messages_list = models.DirectMessage.objects.filter(
        (Q(sender=request.user) & Q(recipient=other_user)) |
        (Q(sender=other_user) & Q(recipient=request.user))
    ).select_related('sender', 'recipient', 'item')
    
    return render(request, 'user/conversation.html', {
        'other_user': other_user,
        'messages_list': messages_list
    })


@login_required
def send_message_api(request):
    """Simple API for sending messages via JS/Post."""
    if request.method == 'POST':
        recipient_id = request.POST.get('recipient_id')
        item_id = request.POST.get('item_id')
        content = request.POST.get('content')
        
        if not recipient_id or not content:
            return JsonResponse({'status': 'error'}, status=400)
            
        recipient = get_object_or_404(User, id=recipient_id)
        item = None
        if item_id:
            item = models.Item.objects.filter(id=item_id).first()
            
        # SECURITY CHECK (Phase 6):
        # Only allow messaging if:
        # A) User is staff
        # B) User is part of a claim thread for this item
        # C) Recipient is an admin/staff
        if not request.user.is_staff and not recipient.is_staff:
            if not item:
                return JsonResponse({'status': 'error', 'message': 'Explicit item context required for student chats.'}, status=403)
            
            # Check for claim relationship
            is_involved = models.ClaimRequest.objects.filter(
                (Q(claimer=request.user) & Q(item__owner=recipient)) |
                (Q(claimer=recipient) & Q(item__owner=request.user))
            ).filter(item=item).exists()
            
            if not is_involved:
                return JsonResponse({'status': 'error', 'message': 'Messaging restricted to active claim threads.'}, status=403)

        msg = models.DirectMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            item=item,
            content=content
        )
        
        return JsonResponse({
            'status': 'success',
            'message': {
                'id': msg.id,
                'content': msg.content,
                'created_at': msg.created_at.strftime('%H:%M')
            }
        })
        
    return JsonResponse({'status': 'error'}, status=400)
