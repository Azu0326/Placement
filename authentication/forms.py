from django import forms


class LoginForm(forms.Form):
    """Credentials for either provider.

    ``username`` is labelled for humans as "Username or email" because Cognito
    accepts either, and the bootstrap account is a plain username. Validation
    messages here are about the *form*, never about whether an account exists.
    """

    username = forms.CharField(
        max_length=150,
        strip=True,
        error_messages={"required": "Enter your username or email address."},
    )
    password = forms.CharField(
        max_length=256,
        strip=False,
        widget=forms.PasswordInput,
        error_messages={"required": "Enter your password."},
    )
