from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django import forms
from django.contrib.auth.models import User
from .models import Item, UserProfile

class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'description', 'category', 'location', 'status', 'contact_name', 'contact_email', 'image']

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'input'})


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['bio', 'avatar']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'input'})

from django.contrib.auth.models import User
from django.core.validators import RegexValidator

# Relax default username validator to allow spaces
relaxed_username_validator = RegexValidator(
    r'^[\w.@+\- ]+$',
    'Enter a valid username. This value may contain only letters, numbers, spaces, and @/./+/-/_ characters.',
    'invalid'
)
# Patch the User model
username_field = User._meta.get_field('username')
if username_field.validators:
    username_field.validators[0] = relaxed_username_validator
username_field.help_text = "Required. 150 characters or fewer. Letters, digits, spaces, and @/./+/-/_ only."


class CustomUserCreationForm(UserCreationForm):
    username = forms.CharField(
        max_length=150,
        help_text="Required. 150 characters or fewer. You may use spaces.",
        validators=[relaxed_username_validator],
    )
    email = forms.EmailField(required=True, help_text="Required for communication regarding items.")
    
    # New custom fields for UserProfile
    student_staff_id = forms.CharField(
        max_length=50,
        required=False,
        help_text="Optional. Provide your Student or Staff ID for a 'Verified' badge.",
        label="Student/Staff ID"
    )
    user_type = forms.ChoiceField(
        choices=[('student', 'Student'), ('staff', 'Staff')],
        required=True,
        initial='student',
        label="Account Type"
    )

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'input'})
            
    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            from items.models import UserProfile
            # Check if UserProfile already created via signals, otherwise create new
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.student_staff_id = self.cleaned_data.get('student_staff_id')
            profile.user_type = self.cleaned_data.get('user_type')
            profile.save()
        return user
class CustomAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'input'})
