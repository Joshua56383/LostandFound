import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'CampusLostFound.settings')
django.setup()

from django.contrib.auth.models import User
from items.models import Item, UserProfile
from items.services.item_service import ItemService

def test_student_submission():
    print("--- INITIATING STUDENT SUBMISSION PROBE ---")
    
    # 1. Setup Mock User
    username = "debug_student_2"
    user, created = User.objects.get_or_create(username=username, email="debug@test.com")
    if created:
        user.set_password("password123")
        user.save()
        UserProfile.objects.get_or_create(user=user, user_type='student')
    
    print(f"Profile Detected: {hasattr(user, 'userprofile')}")
    
    # 2. Setup Mock Form Data (Simulating a saved model instance for ItemService)
    item = Item(
        name="Debug Umbrella",
        description="A black heavy umbrella for testing.",
        location="Main Library",
        category="General",
        report_type="lost"
    )
    
    # Mock a form that returns this item
    class MockForm:
        def save(self, commit=False):
            return item
    
    print("Executing ItemService.report_item...")
    try:
        result_item, success, error = ItemService.report_item(user, MockForm())
        print(f"Result Status: Success={success}, Error={error}")
        print(f"Item State: Verification={result_item.verification_status}, Lifecycle={result_item.lifecycle_status}")
    except Exception as e:
        print("!!! CRITICAL FAILURE DETECTED !!!")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_student_submission()
