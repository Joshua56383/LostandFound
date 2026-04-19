import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CampusLostFound.settings")
django.setup()

from django.contrib.auth.models import User
from items.models import Item, MatchSuggestion, ClaimRequest
from items.services.claim_service import ClaimService
from django.utils import timezone

def test_match_turnover():
    user1, _ = User.objects.get_or_create(username='u1', email='u1@ex.com')
    user2, _ = User.objects.get_or_create(username='u2', email='u2@ex.com')
    admin, _ = User.objects.get_or_create(username='a1', email='a1@ex.com', is_staff=True)
    
    # Create Lost & Found Items
    lost = Item.objects.create(name='Lost Keys', report_type='lost', lifecycle_status='active', owner=user1)
    found = Item.objects.create(name='Found Keys', report_type='found', lifecycle_status='active', owner=user2)
    
    # Create Match
    match = MatchSuggestion.objects.create(lost_item=lost, found_item=found, status='linked')
    
    # Create Claim on Lost Item (someone returns it)
    claim = ClaimRequest.objects.create(item=lost, claimer=user2, status='approved')
    
    # Admin completes claim
    print(f"Before Turnover: Lost status = {lost.lifecycle_status}, Found status = {found.lifecycle_status}")
    
    ClaimService.complete_claim(claim, admin)
    
    # Refresh from DB
    lost.refresh_from_db()
    found.refresh_from_db()
    
    print(f"After Turnover: Lost status = {lost.lifecycle_status}, Found status = {found.lifecycle_status}")
    if lost.lifecycle_status == 'resolved' and found.lifecycle_status == 'resolved':
        print("SUCCESS! Both items were resolved.")
    else:
        print("FAILURE! Items were not both resolved.")

if __name__ == '__main__':
    test_match_turnover()
