from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth.forms import PasswordResetForm
from django.db.models import Q
from django.utils.text import slugify
from oauth2_provider.models import Application

from .directory import group_choices, people_queryset
from .models import (
    ApplicationProfile,
    CustomUser,
    email_info,
    GroupMailboxAssociation,
    InstitutionalRole,
    ManualGroup,
    SchoolClass,
)

MAX_LOGO_BYTES = 1024 * 1024
MAX_LOGO_PIXELS = 2048
ALLOWED_LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}


class RegistrationForm(forms.Form):
    email = forms.EmailField(
        label="E-mail-cím",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": " "}),
    )
    first_name = forms.CharField(
        label="Keresztnév",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "given-name", "placeholder": " "}),
    )
    last_name = forms.CharField(
        label="Vezetéknév",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "family-name", "placeholder": " "}),
    )
    password1 = forms.CharField(
        label="Jelszó",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": " "}),
    )
    password2 = forms.CharField(
        label="Jelszó ismét",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": " "}),
    )
    privacy_consent = forms.BooleanField(
        label="Elolvastam az Adatkezelési Tájékoztatót, és hozzájárulok a regisztrációhoz szükséges adatkezeléshez.",
        required=True,
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if email_info(email).is_in_school_domain:
            raise forms.ValidationError(
                "Iskolai e-mail-címmel nem lehet önállóan regisztrálni. Kérjük, fordulj az SZLG+ rendszergazdáihoz."
            )
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Ehhez az e-mail-címhez már tartozik fiók. Jelentkezz be, vagy kérj jelszó-visszaállítást."
            )
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password1")
        password_confirmation = cleaned_data.get("password2")
        if password and password_confirmation and password != password_confirmation:
            self.add_error("password2", "A két jelszó nem egyezik.")
        elif password and password_confirmation:
            user = CustomUser(
                email=cleaned_data.get("email", ""),
                first_name=cleaned_data.get("first_name", ""),
                last_name=cleaned_data.get("last_name", ""),
            )
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                self.add_error("password2", exc)
        return cleaned_data


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
    required_group_keys = forms.MultipleChoiceField(
        label="Alkalmazáshoz szükséges csoportok",
        required=False,
        help_text=(
            "Ha több csoportot választasz, legalább az egyik tagság elegendő. "
            "Az alkalmazásnak a groups scope-ot kell kérnie és az application_group_access claimet ellenőriznie."
        ),
        widget=forms.SelectMultiple(attrs={"size": 8}),
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
        self.fields["required_group_keys"].choices = group_choices()
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
            self.fields["required_group_keys"].initial = profile.required_group_keys
        else:
            self.fields["developer"].initial = user.get_full_name() or user.email
        self.order_fields(
            [
                "name",
                "short_description",
                "developer",
                "logo",
                "required_group_keys",
                "client_type",
                "redirect_uris",
            ]
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
        profile.required_group_keys = self.cleaned_data.get("required_group_keys", [])
        logo = self.cleaned_data.get("logo")
        if logo is False:
            profile.logo.delete(save=False)
        elif logo:
            profile.logo = logo
        profile.save()
        return application


class ManualGroupForm(forms.ModelForm):
    """Create or edit a manual school group without granting Django permissions."""

    members = forms.ModelMultipleChoiceField(
        label="Tagok",
        required=False,
        queryset=CustomUser.objects.none(),
        help_text="A tagokat a csoportkezelők állítják be; önálló csatlakozás nincs.",
        widget=forms.SelectMultiple(attrs={"size": 10}),
    )
    managers = forms.ModelMultipleChoiceField(
        label="Csoportkezelők",
        required=False,
        queryset=CustomUser.objects.none(),
        widget=forms.SelectMultiple(attrs={"size": 6}),
    )

    class Meta:
        model = ManualGroup
        fields = ("name", "description", "parent", "is_public")
        labels = {
            "name": "Csoport neve",
            "description": "Leírás / kontextus",
            "parent": "Szülőcsoport",
            "is_public": "Közérdekű",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        help_texts = {
            "is_public": "A közérdekű csoport megjelenik a böngészhető listában; a keresés nem közérdekű csoportot is megtalálhat.",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        users = people_queryset(user)
        current_members = self.instance.members.values_list("pk", flat=True) if self.instance.pk else []
        current_managers = self.instance.managers.values_list("pk", flat=True) if self.instance.pk else []
        selectable_ids = set(
            users.filter(is_group_mailbox=False).values_list("pk", flat=True)
        )
        self.fields["members"].queryset = CustomUser.objects.filter(
            pk__in=selectable_ids | set(current_members)
        )
        self.fields["managers"].queryset = CustomUser.objects.filter(
            pk__in=selectable_ids | set(current_managers)
        )
        self.fields["members"].initial = current_members
        self.fields["managers"].initial = current_managers
        for field_name in ("members", "managers"):
            self.fields[field_name].label_from_instance = lambda account: (
                f"{account.get_full_name() or account.email} · {account.email}"
            )
        if not user.is_staff and not user.is_superuser:
            self.fields["parent"].queryset = ManualGroup.objects.filter(
                Q(created_by=user) | Q(managers=user) | Q(pk=self.instance.parent_id)
            ).distinct()
        if self.instance.pk:
            descendants = self.instance.get_descendants(include_self=True)
            self.fields["parent"].queryset = self.fields["parent"].queryset.exclude(
                pk__in=descendants.values_list("pk", flat=True)
            )

    def save(self, commit=True):
        group = super().save(commit=False)
        if not group.slug:
            base = slugify(group.name)[:120] or "csoport"
            candidate = base
            suffix = 2
            while ManualGroup.objects.filter(slug=candidate).exclude(pk=group.pk).exists():
                tail = f"-{suffix}"
                candidate = f"{base[: 120 - len(tail)]}{tail}"
                suffix += 1
            group.slug = candidate
        if commit:
            group.save()
            self.save_m2m()
            group.members.set(self.cleaned_data.get("members", []))
            group.managers.set(self.cleaned_data.get("managers", []))
        return group


class SchoolClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ("homeroom_teacher", "deputy_teacher")
        labels = {
            "homeroom_teacher": "Osztályfőnök",
            "deputy_teacher": "Osztályfőnök-helyettes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        teachers = CustomUser.objects.filter(
            is_active=True, is_group_mailbox=False, teacher_profile__isnull=False
        ).order_by("last_name", "first_name", "email")
        for field in self.fields.values():
            field.queryset = teachers


class SchoolClassCreateForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ("start_year", "section")
        labels = {"start_year": "Kezdés éve", "section": "Szekció"}

    def clean_section(self):
        return self.cleaned_data["section"].strip().upper()


class InstitutionalRoleForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        label="Betöltők",
        required=False,
        queryset=CustomUser.objects.none(),
        widget=forms.SelectMultiple(attrs={"size": 8}),
    )

    class Meta:
        model = InstitutionalRole
        fields = ("name", "description", "is_required")
        labels = {
            "name": "Szerepkör neve",
            "description": "Leírás",
            "is_required": "Kötelezően kitöltendő",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["members"].queryset = (
            user_queryset if user_queryset is not None else CustomUser.objects.none()
        )
        self.fields["members"].label_from_instance = lambda account: (
            f"{account.get_full_name() or account.email} · {account.email}"
        )
        if self.instance.pk:
            self.fields["members"].initial = self.instance.members.values_list("pk", flat=True)

    def save(self, commit=True):
        role = super().save(commit=False)
        if not role.slug:
            base = slugify(role.name)[:80] or "szerepkor"
            candidate = base
            suffix = 2
            while InstitutionalRole.objects.filter(slug=candidate).exclude(pk=role.pk).exists():
                tail = f"-{suffix}"
                candidate = f"{base[: 80 - len(tail)]}{tail}"
                suffix += 1
            role.slug = candidate
        if commit:
            role.save()
            self.save_m2m()
            role.members.set(self.cleaned_data.get("members", []))
        return role


class GroupMailboxAssociationForm(forms.ModelForm):
    class Meta:
        model = GroupMailboxAssociation
        fields = ("mailbox", "group_key")
        labels = {"mailbox": "Csoportos postafiók", "group_key": "Csoport"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mailbox"].queryset = CustomUser.objects.filter(
            is_active=True, is_group_mailbox=True
        ).order_by("email")
        self.fields["group_key"].choices = [("", "Válassz csoportot")] + group_choices()


class GroupMailboxFlagForm(forms.Form):
    mailbox = forms.ModelChoiceField(
        label="Meglévő felhasználói fiók",
        queryset=CustomUser.objects.none(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mailbox"].queryset = CustomUser.objects.filter(
            is_active=True, is_group_mailbox=False
        ).order_by("email")
