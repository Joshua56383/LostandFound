import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CampusLostFound.settings')
django.setup()

from items.models import Item
from django.db.models import Count

def cleanup_duplicates():
    dups = Item.objects.values('name', 'category').annotate(count=Count('id')).filter(count__gt=1)
    
    deleted_count = 0
    for entry in dups:
        name = entry['name']
        category = entry['category']
        
        # Get all records for this name/category pair
        items = Item.objects.filter(name=name, category=category).order_by('-date_reported')
        
        if items.count() > 1:
            # We want to keep the "best" one:
            # 1. Prefer Resolved
            # 2. Prefer Claimed
            # 3. Prefer most recent
            
            resolved_items = items.filter(lifecycle_status='resolved')
            claimed_items = items.filter(lifecycle_status='claimed')
            
            if resolved_items.exists():
                keep_id = resolved_items.first().id
            elif claimed_items.exists():
                keep_id = claimed_items.first().id
            else:
                keep_id = items.first().id
            
            # Delete others
            to_delete = items.exclude(id=keep_id)
            d_count = to_delete.count()
            to_delete.delete()
            
            print(f"Deleted {d_count} duplicates for '{name}' (Kept ID: {keep_id})")
            deleted_count += d_count
            
    print(f"Total duplicates removed: {deleted_count}")

if __name__ == "__main__":
    cleanup_duplicates()
