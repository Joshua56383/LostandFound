import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CampusLostFound.settings")
django.setup()

from django.contrib.auth.models import User
from items.models import Item, Notification
from items.services.claim_service import ClaimService
from items.forms import ClaimForm

def test_claim_notification():
    owner, _ = User.objects.get_or_create(username='test_owner', email='owner@example.com')
    claimer, _ = User.objects.get_or_create(username='test_claimer', email='claimer@example.com')
    
    item = Item.objects.create(
        name='Test Claim Item',
        description='Something to claim',
        location='Library',
        owner=owner,
        verification_status='approved',
        lifecycle_status='active'
    )
    
    print(f"Created item: {item.name}")
    
    # Check notifications for claimer before
    prior_notifs = Notification.objects.filter(recipient=claimer, status_trigger='claim_confirmation').count()
    print(f"Prior 'claim_confirmation' notifications for claimer: {prior_notifs}")
    
    # Submit claim
    form = ClaimForm(data={'message': 'This is mine because I said so.'})
    if form.is_valid():
        claim = ClaimService.submit_claim(claimer, item, form)
        print(f"Claim submitted with ID: {claim.id}")
        
        # Check notifications for claimer after
        after_notifs = Notification.objects.filter(recipient=claimer, status_trigger='claim_confirmation').count()
        print(f"After 'claim_confirmation' notifications for claimer: {after_notifs}")
        
        if after_notifs > prior_notifs:
            print("SUCCESS: Notification was sent to claimer.")
        else:
            print("FAILURE: Notification was NOT sent to claimer.")
    else:
        print(f"Form errors: {form.errors}")
        
if __name__ == '__main__':
    test_claim_notification()
