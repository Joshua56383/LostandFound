from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django import forms
from django.contrib.auth.models import User
from .models import Item, UserProfile, ClaimRequest

class BaseStyledForm(forms.BaseForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if 'class' not in field.widget.attrs:
                field.widget.attrs.update({'class': 'input'})

class ItemForm(forms.ModelForm, BaseStyledForm):
    class Meta:
        model = Item
        fields = ['name', 'description', 'category', 'location', 'status', 'contact_name', 'contact_email', 'image']

class ClaimForm(forms.ModelForm, BaseStyledForm):
    class Meta:
        model = ClaimRequest
        fields = ['message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Provide proof of ownership (e.g., unique marks, what\'s inside, or where exactly you lost it).'}),
        }

class UserUpdateForm(forms.ModelForm, BaseStyledForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

class UserProfileForm(forms.ModelForm, BaseStyledForm):
    class Meta:
        model = UserProfile
        fields = ['bio', 'avatar']

from django.contrib.auth.models import User
from django.core.validators import RegexValidator

# Relax default username validator to allow spaces on the form
relaxed_username_validator = RegexValidator(
    r'^[\w.@+\- ]+$',
    'Enter a valid username. This value may contain only letters, numbers, spaces, and @/./+/-/_ characters.',
    'invalid'
)


class CustomUserCreationForm(UserCreationForm, BaseStyledForm):
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

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            # Profile is created by signals, we just update it
            profile = user.userprofile
            profile.student_staff_id = self.cleaned_data.get('student_staff_id')
            profile.user_type = self.cleaned_data.get('user_type')
            profile.save()
        return user

class CustomAuthenticationForm(AuthenticationForm, BaseStyledForm):
    pass
