from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from .models import Item
from .forms import ItemForm


def item_list(request):
    # query params
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', 'all')
    location = request.GET.get('location', 'all')
    tab = request.GET.get('tab', 'all')

    items = Item.objects.all()

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

    # counts and distinct filter options
    total_count = Item.objects.count()
    lost_count = Item.objects.filter(status='lost').count()
    found_count = Item.objects.filter(status='found').count()

    categories = Item.objects.exclude(category='').order_by('category').values_list('category', flat=True).distinct()
    locations = Item.objects.exclude(location='').order_by('location').values_list('location', flat=True).distinct()

    context = {
        'items': items,
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


def add_item(request):
    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'"{item.name}" reported successfully.')
            return redirect('items:item_list')
    else:
        form = ItemForm()
    return render(request, 'items/add_item.html', {'form': form})


def report_item(request, status):
    # status should be 'lost' or 'found'
    status = status if status in ['lost', 'found'] else 'lost'
    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f'"{item.name}" reported as {item.status}.')
            return redirect('items:item_list')
    else:
        form = ItemForm(initial={'status': status})
    return render(request, 'items/add_item.html', {'form': form, 'report_type': status})


def item_detail(request, pk):
    item = get_object_or_404(Item, pk=pk)
    return render(request, 'items/item_detail.html', {'item': item})
