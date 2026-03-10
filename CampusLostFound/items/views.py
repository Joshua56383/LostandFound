from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.db.models import Q
from . import models
from . import ai_service
from .forms import ItemForm, UserUpdateForm, UserProfileForm

def create_notification(recipient, item, status_trigger):
    """Call Gemini to generate a message and save a Notification."""
    message = ai_service.generate_notification_message(item, status_trigger)
    models.Notification.objects.create(
        recipient=recipient,
        message=message,
        related_item=item,
        status_trigger=status_trigger
    )

@login_required
def dashboard(request):
    # Admin stats
    total_items = models.Item.objects.count()
    lost_count = models.Item.objects.filter(status='lost').count()
    found_count = models.Item.objects.filter(status='found').count()
    claimed_count = models.Item.objects.filter(status='claimed').count()
    
    # Calculate System-wide Success Rate
    success_rate = 0
    if total_items > 0:
        success_rate = int((claimed_count / total_items) * 100)

    # Filtering logic
    q = request.GET.get('q', '')
    status_filter = request.GET.get('status', 'all')
    category_filter = request.GET.get('category', 'all')
    
    if request.user.is_staff:
        # Admin View: All items
        items_query = models.Item.objects.all().order_by('-date_reported')
    else:
        # User View: Only their own items
        items_query = models.Item.objects.filter(owner=request.user).order_by('-date_reported')
    
    if q:
        items_query = items_query.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
        
    if status_filter != 'all':
        items_query = items_query.filter(status=status_filter)
        
    if category_filter != 'all':
        items_query = items_query.filter(category=category_filter)
        
    # Pagination
    paginator = Paginator(items_query, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Categories for filter
    categories = models.Item.objects.values_list('category', flat=True).distinct()
    categories = [c for c in categories if c]
    
    # User-specific stats
    user_total = models.Item.objects.filter(owner=request.user).count()
    user_resolved = models.Item.objects.filter(owner=request.user, status='claimed').count()
    
    context = {
        'total_items': total_items,
        'lost_count': lost_count,
        'found_count': found_count,
        'claimed_count': claimed_count,
        'success_rate': success_rate,
        'items': page_obj,
        'q': q,
        'status_filter': status_filter,
        'category': category_filter,
        'categories': categories,
        'user_total': user_total,
        'user_resolved': user_resolved,
    }
    
    if request.user.is_staff:
        template = 'items/dashboard.html'
    else:
        template = 'items/user_dashboard.html'
        
    return render(request, template, context)


def item_list(request):
    # query params
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', 'all')
    location = request.GET.get('location', 'all')
    tab = request.GET.get('tab', 'all')

    items = models.Item.objects.all()

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

    # counts and distinct filter options
    # Optimization: Combining counts could be better, but separate queries are clear for now.
    # We could use .aggregate() but let's stick to basic optimization first (pagination).
    total_count = models.Item.objects.count()
    lost_count = models.Item.objects.filter(status='lost').count()
    found_count = models.Item.objects.filter(status='found').count()

    categories = models.Item.objects.exclude(category='').order_by('category').values_list('category', flat=True).distinct()
    locations = models.Item.objects.exclude(location='').order_by('location').values_list('location', flat=True).distinct()

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

    return render(request, 'items/item_list.html', context)


@login_required
def add_item(request):
    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            item.save()
            messages.success(request, f'"{item.name}" reported successfully.')
            return redirect('items:item_list')
    else:
        form = ItemForm()
    return render(request, 'items/add_item.html', {'form': form})


@login_required
def report_item(request, status):
    # status should be 'lost' or 'found'
    status = status if status in ['lost', 'found'] else 'lost'
    if request.method == 'POST':
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            item.save()
            
            # Send Notification to all Admins
            trigger = 'lost_reported' if item.status == 'lost' else 'found_reported'
            for admin_user in User.objects.filter(is_staff=True):
                create_notification(admin_user, item, trigger)
                
            messages.success(request, f'"{item.name}" reported as {item.status}.')
            return redirect('items:item_list')
    else:
        form = ItemForm(initial={'status': status})
    return render(request, 'items/add_item.html', {'form': form, 'report_type': status})


def item_detail(request, pk):
    item = get_object_or_404(models.Item, pk=pk)
    return render(request, 'items/item_detail.html', {'item': item})

@login_required
def profile(request):
    user_items = models.Item.objects.filter(owner=request.user).order_by('-date_reported')
    user_items_resolved_count = user_items.filter(status='claimed').count()
    return render(request, 'items/profile.html', {
        'user_items': user_items,
        'user_items_resolved_count': user_items_resolved_count
    })


@login_required
def claim_item(request, item_id):
    """Allow owners or finders to mark an item as claimed/resolved."""
    item = get_object_property(models.Item, item_id)
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
    return render(request, 'items/edit_profile.html', context)

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
    item = get_object_or_404(models.Item, pk=pk)
    if request.method == 'POST':
        item_name = item.name
        item.delete()
        messages.success(request, f'Item "{item_name}" deleted successfully.')
    return redirect('items:dashboard')


@login_required
def user_directory(request):
    if not request.user.is_staff:
        return redirect('items:item_list')
    
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
    return render(request, 'items/user_directory.html', context)


@login_required
def admin_analytics(request):
    if not request.user.is_staff:
        return redirect('items:item_list')
    
    # Placeholder for analytics logic
    total_items = models.Item.objects.count()
    lost_items = models.Item.objects.filter(status='lost').count()
    found_items = models.Item.objects.filter(status='found').count()
    resolved_items = models.Item.objects.filter(status='claimed').count()
    
    success_rate = 0
    if total_items > 0:
        success_rate = (resolved_items / total_items) * 100
    
    context = {
        'total_items': total_items,
        'lost_items': lost_items,
        'found_items': found_items,
        'resolved_items': resolved_items,
        'success_rate': success_rate,
    }
    return render(request, 'items/admin_analytics.html', context)


@login_required
def audit_logs(request):
    if not request.user.is_staff:
        return redirect('items:item_list')
    
    # Use UserLoginLog model for actual data
    logs = models.UserLoginLog.objects.all().order_by('-timestamp')[:50]
    
    context = {
        'logs': logs,
    }
    return render(request, 'items/audit_logs.html', context)


@login_required
def toggle_user_active(request, user_id):
    if not request.user.is_staff:
        return redirect('items:item_list')
    user_to_toggle = get_object_or_404(User, id=user_id)
    if user_to_toggle != request.user: # Prevent self-deactivation
        user_to_toggle.is_active = not user_to_toggle.is_active
        user_to_toggle.save()
        status = "activated" if user_to_toggle.is_active else "deactivated"
        messages.success(request, f'User {user_to_toggle.username} has been {status}.')
    else:
        messages.error(request, "You cannot deactivate your own account.")
    return redirect('items:user_directory')

@login_required
def toggle_user_role(request, user_id):
    if not request.user.is_staff:
        return redirect('items:item_list')
    user_to_toggle = get_object_or_404(User, id=user_id)
    if user_to_toggle != request.user:
        user_to_toggle.is_staff = not user_to_toggle.is_staff
        user_to_toggle.save()
        role = "Admin" if user_to_toggle.is_staff else "Standard"
        messages.success(request, f'User {user_to_toggle.username} role updated to {role}.')
    else:
        messages.error(request, "You cannot change your own role.")
    return redirect('items:user_directory')

@login_required
def delete_user_admin(request, user_id):
    if not request.user.is_staff:
        return redirect('items:item_list')
    user_to_delete = get_object_or_404(User, id=user_id)
    if user_to_delete != request.user:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f'User {username} has been permanently deleted.')
    else:
        messages.error(request, "You cannot delete your own account.")
    return redirect('items:user_directory')

@login_required
def reset_user_password(request, user_id):
    if not request.user.is_staff:
        return redirect('items:item_list')
    user_to_reset = get_object_or_404(User, id=user_id)
    # Generic temporary password for demonstration
    temp_pass = "Campus2026!"
    user_to_reset.set_password(temp_pass)
    user_to_reset.save()
    messages.success(request, f'Password for {user_to_reset.username} reset to: {temp_pass}')
    return redirect('items:user_directory')

from django.http import JsonResponse

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
