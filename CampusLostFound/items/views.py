from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from . import models
from .forms import ItemForm, UserUpdateForm

try:
    from .forms import UserProfileForm
except ImportError:
    UserProfileForm = None

@login_required
def dashboard(request):
    total_items = models.Item.objects.count()
    lost_count = models.Item.objects.filter(status='lost').count()
    found_count = models.Item.objects.filter(status='found').count()
    claimed_count = models.Item.objects.filter(status='claimed').count()
    
    # Get recent activity (last 5 items)
    recent_items = models.Item.objects.order_by('-date_reported')[:5]
    
    context = {
        'total_items': total_items,
        'lost_count': lost_count,
        'found_count': found_count,
        'claimed_count': claimed_count,
        'recent_items': recent_items,
    }
    return render(request, 'items/dashboard.html', context)


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
    return render(request, 'items/profile.html', {'user_items': user_items})
@login_required
def edit_profile(request):
    # Get or create user profile
    if hasattr(models, 'UserProfile'):
        profile, created = models.UserProfile.objects.get_or_create(user=request.user)
        has_profile_form = UserProfileForm is not None
    else:
        profile = None
        has_profile_form = False
    
    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=request.user)
        profile_form = None
        if has_profile_form:
            profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)
        
        if has_profile_form:
            if user_form.is_valid() and profile_form.is_valid():
                user_form.save()
                profile_form.save()
                messages.success(request, 'Your profile has been updated.')
                return redirect('items:profile')
        else:
            if user_form.is_valid():
                user_form.save()
                messages.success(request, 'Your profile has been updated.')
                return redirect('items:profile')
    else:
        user_form = UserUpdateForm(instance=request.user)
        profile_form = None
        if has_profile_form:
            profile_form = UserProfileForm(instance=profile)
    
    context = {'form': user_form}
    if has_profile_form:
        context['profile_form'] = profile_form
    return render(request, 'items/edit_profile.html', context)
