from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django import forms
from django.contrib.auth.models import User
from .models import Item, UserProfile, ClaimRequest

class BaseStyledForm(forms.BaseForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if 'class' not in field.widget.attrs:
                field.widget.attrs.update({'class': 'input-field'})

class ItemForm(BaseStyledForm, forms.ModelForm):
    amount = forms.DecimalField(required=False, initial=0.00, decimal_places=2, max_digits=10)
    
    class Meta:
        model = Item
        fields = ['name', 'description', 'category', 'location', 'report_type', 'amount', 'denominations', 'contact_name', 'contact_email', 'image', 'discovery_date']
        labels = {
            'report_type': 'Type of Report',
            'denominations': 'Denominations (Optional)',
            'discovery_date': 'Estimated Date/Time',
        }
        widgets = {
            'denominations': forms.Textarea(attrs={'rows': 2, 'placeholder': 'e.g. 2x$50, 1x$20. For found money, this helps verify the real owner.'}),
            'discovery_date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'input-field'}),
        }

class ClaimForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = ClaimRequest
        fields = ['message', 'proof_file', 'contact_phone']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Provide proof of ownership (e.g., unique marks, what\'s inside, or where exactly you lost it).'}),
            'contact_phone': forms.TextInput(attrs={'placeholder': 'e.g., +1 234 567 890'}),
        }

    def clean_proof_file(self):
        file = self.cleaned_data.get('proof_file')
        if file:
            # Validate size (5MB)
            if file.size > 5 * 1024 * 1024:
                raise forms.ValidationError("File size must be under 5MB.")
            
            # Validate extension
            ext = file.name.split('.')[-1].lower()
            if ext not in ['jpg', 'jpeg', 'png', 'pdf']:
                raise forms.ValidationError("Only Images (JPG, PNG) or PDF files are allowed.")
        return file

class MoneyClaimForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = ClaimRequest
        fields = ['claimed_amount', 'claimed_denominations', 'message', 'proof_file', 'contact_phone']
        labels = {
            'claimed_amount': 'Estimated Amount ($)',
            'claimed_denominations': 'Describe the Denominations',
        }
        widgets = {
            'claimed_amount': forms.NumberInput(attrs={'placeholder': '0.00'}),
            'claimed_denominations': forms.Textarea(attrs={'rows': 3, 'placeholder': 'e.g. "It was mostly $20s" or "All $100 bills"'}),
            'message': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Any other unique details (e.g., an envelope or rubber band)'}),
        }

    def clean_claimed_amount(self):
        amount = self.cleaned_data.get('claimed_amount')
        if amount is None or amount < 0:
            raise forms.ValidationError("Please provide a valid estimated amount.")
        return amount

class UserUpdateForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(
                "This email is already registered. Please log in or use a different email."
            )
        return email

class UserProfileForm(BaseStyledForm, forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['bio', 'avatar']

from django.contrib.auth.models import User
from django.core.validators import RegexValidator

# Relax default username validator to allow spaces on the form
relaxed_username_validator = RegexValidator(
    r'^[\w.@+\- ]+$',
    'Enter a valid username. You can use letters, numbers, spaces, and @ . + - _ characters.',
    'invalid'
)


class CustomUserCreationForm(BaseStyledForm, UserCreationForm):
    username = forms.CharField(
        max_length=150,
        help_text="Choose a username (letters, numbers, and spaces allowed).",
        validators=[relaxed_username_validator],
    )
    email = forms.EmailField(required=True, help_text="We'll use this to email you about items.")
    
    # New custom fields for UserProfile
    student_staff_id = forms.CharField(
        max_length=50,
        required=False,
        help_text="Optional. Enter your Student or Staff ID if you have one.",
        label="Student ID / ID Number"
    )
    user_type = forms.ChoiceField(
        choices=[('student', 'Student'), ('staff', 'Staff')],
        required=True,
        initial='student',
        label="Are you a student or staff?"
    )

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                "This email is already registered. Please log in or use a different email."
            )
        return email

    def clean_student_staff_id(self):
        student_staff_id = self.cleaned_data.get('student_staff_id')
        if student_staff_id:
            if UserProfile.objects.filter(student_staff_id=student_staff_id).exists():
                raise forms.ValidationError("This ID is already in use.")
        return student_staff_id

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            # Profile is created by signals, we just update it
            try:
                profile = user.userprofile
            except UserProfile.DoesNotExist:
                profile = UserProfile.objects.create(user=user)
            
            profile.student_staff_id = self.cleaned_data.get('student_staff_id')
            profile.user_type = self.cleaned_data.get('user_type')
            profile.save()
        return user

class CustomAuthenticationForm(AuthenticationForm, BaseStyledForm):
    pass
