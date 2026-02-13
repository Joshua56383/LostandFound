from django import forms
from .models import Item

class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'description', 'category', 'location', 'status', 'contact_name', 'contact_email', 'image_url']
