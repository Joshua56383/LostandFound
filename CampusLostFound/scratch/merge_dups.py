from items.models import Item
from django.db.models import Count

dups = Item.objects.values('name', 'category').annotate(count=Count('id')).filter(count__gt=1)
deleted_count = 0

for d in dups:
    items = Item.objects.filter(name=d['name'], category=d['category']).order_by('-date_reported')
    
    # Selection criteria
    keep_item = items.filter(lifecycle_status='resolved').first()
    if not keep_item:
        keep_item = items.filter(lifecycle_status='claimed').first()
    if not keep_item:
        keep_item = items.first()
        
    to_delete = items.exclude(id=keep_item.id)
    count = to_delete.count()
    to_delete.delete()
    print(f"Merged duplicates for '{d['name']}': Kept {keep_item.lifecycle_status} (ID:{keep_item.id}), Deleted {count}")
    deleted_count += count

print(f"Total entries removed: {deleted_count}")
