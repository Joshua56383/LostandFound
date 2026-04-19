import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "CampusLostFound.settings")
django.setup()

from django.contrib.auth.models import User
from items.services.item_service import ItemService
from items.forms import ItemForm
from django.core.files.uploadedfile import SimpleUploadedFile

def test_report():
    user, _ = User.objects.get_or_create(username='testreporter', email='tr@ex.com')
    data = {
        'name': 'Test Item Submission',
        'description': 'Description details',
        'location': 'Canteen',
        'report_type': 'lost',
        'category': 'Electronics',
        'contact_email': 'test@test.com',
        'discovery_date': '2026-04-18 10:00:00'
    }
    
    # Simulate a POST request with this data
    form = ItemForm(data=data)
    if form.is_valid():
        try:
            item, success, error = ItemService.report_item(user, form)
            print(f"Success: {success}, Error: {error}, Item: {item}")
        except Exception as e:
            print(f"Exception raised during ItemService.report_item: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"Form validation failed: {form.errors}")

if __name__ == '__main__':
    test_report()
