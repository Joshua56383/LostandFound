from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

UserModel = get_user_model()

class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authentication backend which allows users to authenticate using either their
    username or email address.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        
        try:
            # Check if the user exists based on username or email
            user = UserModel.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except UserModel.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a nonexistent user.
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            # In the rare case multiple users have the same email address,
            # we try to get the first one that matches
            user = UserModel.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            ).order_by('id').first()
            
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
            
        return None
