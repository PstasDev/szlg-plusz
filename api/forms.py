from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from oauth2_provider.models import Application

from .models import ApplicationProfile

MAX_LOGO_BYTES = 1024 * 1024
MAX_LOGO_PIXELS = 2048
ALLOWED_LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}


class SZLGPasswordResetForm(PasswordResetForm):
    """Also lets accounts without a usable password (e.g. passkey-only) set one."""

    def get_users(self, email):
        return get_user_model()._default_manager.filter(email__iexact=email, is_active=True)


class ApplicationForm(forms.ModelForm):
    """Self-service OAuth client registration with fixed, safe protocol settings."""

    developer = forms.CharField(label="Fejlesztő", max_length=120)
    short_description = forms.CharField(
        label="Rövid leírás",
        max_length=160,
        help_text="Egy mondat arról, hogy mit csinál az alkalmazás. Ezt látják a felhasználók az engedélyezéskor.",
    )
    logo = forms.ImageField(
        label="Logó",
        required=False,
        help_text="Négyzet alakú PNG, JPEG vagy WebP, legfeljebb 1 MB.",
    )

    class Meta:
        model = Application
        fields = ("name", "client_type", "redirect_uris")
        labels = {
            "name": "Alkalmazás neve",
            "client_type": "Típus",
            "redirect_uris": "Átirányítási URI-k",
        }
        help_texts = {
            "client_type": (
                "Bizalmas: szerveroldali alkalmazás, ami titokban tudja tartani a kliensjelszót. "
                "Nyilvános: böngészős vagy mobilalkalmazás (PKCE-vel, jelszó nélkül)."
            ),
            "redirect_uris": "Soronként egy; pontosan egyezniük kell azzal, amit az alkalmazás használ.",
        }
        widgets = {"redirect_uris": forms.Textarea(attrs={"rows": 3, "spellcheck": "false"})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["client_type"] = forms.ChoiceField(
            label="Típus",
            choices=[
                (Application.CLIENT_CONFIDENTIAL, "Bizalmas (szerveroldali)"),
                (Application.CLIENT_PUBLIC, "Nyilvános (böngésző / mobil)"),
            ],
            initial=Application.CLIENT_CONFIDENTIAL,
            help_text=self.Meta.help_texts["client_type"],
        )
        # Protocol settings are not user-selectable.
        self.instance.user = user
        self.instance.authorization_grant_type = Application.GRANT_AUTHORIZATION_CODE
        self.instance.algorithm = Application.RS256_ALGORITHM
        self.instance.skip_authorization = False

        profile = getattr(self.instance, "profile", None) if self.instance.pk else None
        if profile is not None:
            self.fields["developer"].initial = profile.developer
            self.fields["short_description"].initial = profile.short_description
            self.fields["logo"].initial = profile.logo
        else:
            self.fields["developer"].initial = user.get_full_name() or user.email
        self.order_fields(
            ["name", "short_description", "developer", "logo", "client_type", "redirect_uris"]
        )

    def clean_redirect_uris(self):
        uris = self.cleaned_data["redirect_uris"].split()
        if not uris:
            raise forms.ValidationError("Legalább egy átirányítási URI kötelező.")
        return " ".join(dict.fromkeys(uris))

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if not logo or logo is False:
            return logo
        if logo.size > MAX_LOGO_BYTES:
            raise forms.ValidationError("A logó legfeljebb 1 MB lehet.")
        image = getattr(logo, "image", None)
        if image is not None:
            if image.format not in ALLOWED_LOGO_FORMATS:
                raise forms.ValidationError("Csak PNG, JPEG vagy WebP logó tölthető fel.")
            if max(image.size) > MAX_LOGO_PIXELS:
                raise forms.ValidationError(
                    f"A logó legfeljebb {MAX_LOGO_PIXELS}×{MAX_LOGO_PIXELS} képpont lehet."
                )
        return logo

    def save(self, commit=True):
        application = super().save(commit=commit)
        if not commit:
            return application

        profile = getattr(application, "profile", None) or ApplicationProfile(
            application=application,
            verified=self.user.is_staff,
        )
        profile.developer = self.cleaned_data["developer"]
        profile.short_description = self.cleaned_data["short_description"]
        logo = self.cleaned_data.get("logo")
        if logo is False:
            profile.logo.delete(save=False)
        elif logo:
            profile.logo = logo
        profile.save()
        return application
