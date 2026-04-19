import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CampusLostFound.settings')
django.setup()

from items.models import Item, MatchSuggestion
from items import ai_service
from items.services.item_service import ItemService

def run_resync():
    items = Item.objects.filter(image__isnull=False, ai_tags='')
    print(f"Syncing {items.count()} items...")
    
    for item in items:
        try:
            print(f"Targeting: {item.name}...")
            tags = ai_service.extract_image_tags(item.image.path)
            if tags:
                item.ai_tags = tags
                item.save()
                print(f"  [SUCCESS] Tagged: {tags}")
                
                # Immediately check for matches
                matches = ItemService._find_potential_matches(item)
                print(f"  [MATCHES] Found {len(matches)} suggestions.")
            else:
                print(f"  [FAIL] No tags generated for {item.name}")
        except Exception as e:
            print(f"  [ERROR] {item.name}: {e}")

    print("--- Sync Complete ---")
    print(f"Total Pending Matches: {MatchSuggestion.objects.filter(status='pending').count()}")

if __name__ == "__main__":
    run_resync()
