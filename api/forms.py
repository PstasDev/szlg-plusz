from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from oauth2_provider.models import Application

from .models import (
    ApplicationProfile,
    CustomUser,
    ManualReviewRequest,
    SchoolClass,
    StudentProfile,
    Tagozat,
    TeacherProfile,
    email_info,
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.school_domain_attempted = False

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if email_info(email).is_in_school_domain:
            self.school_domain_attempted = True
            raise forms.ValidationError(
                "Iskolai e-mail-címmel az iskolai fiók létrehozására szolgáló folyamatot használd."
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


class SchoolAccountEmailForm(forms.Form):
    email = forms.EmailField(
        label="Iskolai e-mail-cím",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": " "}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class SchoolAccountOTPForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        label="E-mailben kapott ellenőrző kód",
        error_messages={"invalid": "Hatjegyű kódot adj meg."},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]{6}",
                "maxlength": "6",
                "placeholder": " ",
            }
        ),
    )


class SchoolAccountRegistrationForm(forms.Form):
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
    phone = forms.CharField(
        label="Telefonszám",
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "tel", "placeholder": " "}),
    )
    date_of_birth = forms.DateField(
        label="Születési dátum",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "autocomplete": "bday"}),
    )
    om_id = forms.CharField(
        label="OM azonosító",
        max_length=32,
        required=False,
        help_text="Diákoknak; ha kéznél van, add meg.",
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": " "}),
    )
    tagozat = forms.ModelChoiceField(
        label="Tagozat",
        queryset=Tagozat.objects.none(),
        required=False,
        empty_label="Nincs megadva",
    )
    applicant_type = forms.ChoiceField(
        label="Iskolai szerepkör",
        choices=(
            (ManualReviewRequest.ApplicantType.TEACHER, "Tanár"),
            (ManualReviewRequest.ApplicantType.SCHOOL_EMPLOYEE, "Egyéb iskolai munkatárs"),
        ),
    )
    position = forms.CharField(
        label="Beosztás / munkakör",
        max_length=120,
        help_text="Például tantárgy, munkakör vagy iskolai feladatkör.",
        widget=forms.TextInput(attrs={"autocomplete": "organization-title", "placeholder": " "}),
    )
    employee_number = forms.CharField(
        label="Munkatársi azonosító",
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": " "}),
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

    def __init__(self, *args, email: str, registration_kind: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email
        self.registration_kind = registration_kind
        self.fields["tagozat"].queryset = Tagozat.objects.order_by("name")
        if registration_kind == "student":
            self.fields.pop("applicant_type")
            self.fields.pop("position")
            self.fields.pop("employee_number")
        else:
            self.fields.pop("om_id")
            self.fields.pop("tagozat")

    def clean(self):
        cleaned_data = super().clean()
        if not email_info(self.email).is_in_school_domain:
            raise forms.ValidationError("Az iskolai e-mail-címed már nem tartozik a beállított domainhez.")
        if CustomUser.objects.filter(email__iexact=self.email).exists():
            raise forms.ValidationError(
                "Ehhez az e-mail-címhez már tartozik fiók. Indítsd újra az iskolai fiók folyamatát."
            )

        password = cleaned_data.get("password1")
        password_confirmation = cleaned_data.get("password2")
        if password and password_confirmation and password != password_confirmation:
            self.add_error("password2", "A két jelszó nem egyezik.")
        elif password and password_confirmation:
            user = CustomUser(
                email=self.email,
                first_name=cleaned_data.get("first_name", ""),
                last_name=cleaned_data.get("last_name", ""),
            )
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                self.add_error("password2", exc)
        return cleaned_data


class ManualReviewForm(forms.Form):
    first_name = forms.CharField(label="Keresztnév", max_length=150)
    last_name = forms.CharField(label="Vezetéknév", max_length=150)
    phone = forms.CharField(label="Telefonszám", max_length=32, required=False)
    date_of_birth = forms.DateField(
        label="Születési dátum",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    applicant_type = forms.ChoiceField(
        label="Jelentkező típusa", choices=ManualReviewRequest.ApplicantType.choices
    )
    position = forms.CharField(label="Beosztás / munkakör", max_length=120, required=False)
    employee_number = forms.CharField(
        label="Munkatársi azonosító", max_length=32, required=False
    )
    om_id = forms.CharField(label="OM azonosító", max_length=32, required=False)
    tagozat = forms.ModelChoiceField(
        label="Tagozat", queryset=Tagozat.objects.none(), required=False
    )
    kezdes_eve = forms.IntegerField(
        label="Osztály kezdési éve", required=False, min_value=1900, max_value=2200
    )
    szekcio = forms.CharField(label="Osztály szekciója", max_length=10, required=False)
    reviewer_note = forms.CharField(
        label="Adminisztrátori megjegyzés",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, user: CustomUser, review_request: ManualReviewRequest, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.review_request = review_request
        self.fields["tagozat"].queryset = Tagozat.objects.order_by("name")
        student_profile = getattr(user, "student_profile", None)
        teacher_profile = getattr(user, "teacher_profile", None)
        self.initial.update(
            {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "date_of_birth": user.date_of_birth,
                "applicant_type": review_request.applicant_type,
                "position": review_request.position,
                "employee_number": review_request.employee_number
                or (teacher_profile.employee_number if teacher_profile else ""),
                "om_id": student_profile.om_id if student_profile else "",
                "tagozat": student_profile.tagozat_id if student_profile else None,
                "kezdes_eve": student_profile.kezdes_eve if student_profile else None,
                "szekcio": student_profile.szekcio if student_profile else "",
                "reviewer_note": review_request.reviewer_note,
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        applicant_type = cleaned_data.get("applicant_type")
        if applicant_type in {
            ManualReviewRequest.ApplicantType.TEACHER,
            ManualReviewRequest.ApplicantType.SCHOOL_EMPLOYEE,
        } and not (cleaned_data.get("position") or "").strip():
            self.add_error("position", "Tanárnál vagy munkatársnál add meg a beosztást.")

        start_year = cleaned_data.get("kezdes_eve")
        section = (cleaned_data.get("szekcio") or "").strip()
        if applicant_type == ManualReviewRequest.ApplicantType.STUDENT and (
            (start_year is None) != (not section)
        ):
            self.add_error(
                "szekcio" if start_year is not None else "kezdes_eve",
                "Az osztályhoz a kezdési évet és a szekciót is add meg.",
            )
        elif applicant_type != ManualReviewRequest.ApplicantType.STUDENT:
            cleaned_data["kezdes_eve"] = None
            section = ""
        cleaned_data["szekcio"] = section.upper()
        return cleaned_data

    def save_review_details(self):
        if not self.is_valid():
            raise ValueError("A felülvizsgálati űrlap érvénytelen.")

        data = self.cleaned_data
        user = self.user
        user.first_name = data["first_name"].strip()
        user.last_name = data["last_name"].strip()
        user.phone = data["phone"].strip()
        user.date_of_birth = data["date_of_birth"]
        user.save(
            update_fields=["first_name", "last_name", "phone", "date_of_birth"]
        )

        review_request = self.review_request
        review_request.applicant_type = data["applicant_type"]
        review_request.position = (data.get("position") or "").strip()
        review_request.employee_number = (data.get("employee_number") or "").strip()
        review_request.reviewer_note = data["reviewer_note"].strip()
        review_request.save(
            update_fields=(
                "applicant_type",
                "position",
                "employee_number",
                "reviewer_note",
            )
        )

        if review_request.applicant_type == ManualReviewRequest.ApplicantType.STUDENT:
            StudentProfile.objects.update_or_create(
                user=user,
                defaults={
                    "om_id": (data.get("om_id") or "").strip(),
                    "tagozat": data.get("tagozat"),
                    "kezdes_eve": data.get("kezdes_eve"),
                    "szekcio": data.get("szekcio", ""),
                },
            )
            TeacherProfile.objects.filter(user=user).delete()
            if data.get("kezdes_eve") and data.get("szekcio"):
                SchoolClass.objects.get_or_create(
                    start_year=data["kezdes_eve"], section=data["szekcio"]
                )
        else:
            StudentProfile.objects.filter(user=user).delete()
            if review_request.applicant_type == ManualReviewRequest.ApplicantType.TEACHER:
                TeacherProfile.objects.update_or_create(
                    user=user,
                    defaults={"employee_number": review_request.employee_number},
                )
            else:
                TeacherProfile.objects.filter(user=user).delete()

        return user, review_request


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
