import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CampusLostFound.settings')
django.setup()

from items.models import Item, MatchSuggestion
from items.services.item_service import ItemService

def run_match_resync():
    # We target all active items for a fresh match scan
    items = Item.objects.filter(lifecycle_status='active', verification_status='approved')
    print(f"Scanning matches for {items.count()} items...")
    
    for item in items:
        try:
            # 1. Force AI Tagging if missing
            if item.image and not item.ai_tags:
                from items import ai_service
                print(f"  [AI SCAN] Generating tags for {item.name}...")
                try:
                    tags = ai_service.extract_image_tags(item.image.path)
                    if tags:
                        item.ai_tags = tags
                        item.save(update_fields=['ai_tags'])
                        print(f"    --> Tags: {tags[:50]}...")
                except Exception as e:
                    print(f"    --> [AI ERROR] {e}")

            # 2. Re-trigger matcher
            matches = ItemService._find_potential_matches(item)
            if matches:
                 print(f"  [MATCH] {item.name}: {len(matches)} suggestions created/updated.")
        except Exception as e:
            print(f"  [ERROR] {item.name}: {e}")

    print("--- Match Sync Complete ---")
    print(f"Current Dashboard Count: {MatchSuggestion.objects.filter(status='pending').count()}")

if __name__ == "__main__":
    run_match_resync()
