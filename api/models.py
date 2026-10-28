import uuid
import datetime
import re

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser, Group
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify
from mptt.fields import TreeForeignKey
from mptt.models import MPTTModel
from solo.models import SingletonModel


def year_szekcio_to_str(startYear: int, szekcio: str) -> str:
    current_year = datetime.date.today().year
    current_month = datetime.date.today().month
    school_year = current_year
    if current_month < 9:
        school_year -= 1

    graduation_year = startYear + 4
    if szekcio in ['A', 'E', 'F']:
        graduation_year += 1

    if school_year >= graduation_year:
        return f"{startYear}{szekcio}"
    else:
        years_passed = school_year - startYear
        if szekcio in ['A', 'E', 'F']:
            if years_passed == 0:
                return f"KNY{szekcio}" if szekcio == 'A' else f"NY{szekcio}"
            else:
                # years_passed 1 = 9. F, years_passed 2 = 10. F, etc.
                return f"{8 + years_passed}. {szekcio}"
        else:
            # B, C, D classes: years_passed 0 = 9., years_passed 1 = 10., etc.
            return f"{9 + years_passed}. {szekcio}"

def class_str_to_year_szekcio(class_str: str) -> tuple[int, str]:
    # Smart function that can convert from any typo if there is a valid class: 
    # KNYA, knya, nya, NYA, 0.a, 0.A, 0A, 9.NYA, 9. KNYA -> KNYA
    # 10F, 2023F, 10. F, 10.f -> 10F
    # post-graduate classes, are tricky, drop an error if there are certainly two valid answers (for example 2000A can be a class that either refers to the class starting in 2000 with szekcio A or a class graduated in 2000 with szekcio A)
    class_str = class_str.strip().upper().replace(" ", "")
    if class_str.startswith("KNY"):
        return (0, "A")
    if class_str.startswith("NY"):
        return (0, class_str[-1])
    if "." in class_str:
        parts = class_str.split(".")
        return (int(parts[0]), parts[1])
    if class_str[0].isdigit():
        return (int(class_str[:-1]), class_str[-1])
    if class_str.isdigit():
        return (int(class_str), "")
    # If none of the above conditions are met, we cannot parse the class string.
    raise ValueError(f"Cannot parse class string: {class_str}")

class email_info:
    def __init__(self, email: str, school_domain: str | None = None):
        self.email = email.strip().lower()
        self.school_domain = (
            school_domain if school_domain is not None else get_school_domain()
        )

    @property
    def local_part(self) -> str:
        return self.email.partition("@")[0]

    # E-mail formats:
    # Group: group@szlgbp.hu
    # Teacher/School employee: lastname.firstname@szlgbp.hu
    # Full-time Student: lastname.firstname.23a@szlgbp.hu (23 - start year, a - szekció)
    # Part-time Student: lastname.firstname.23af@szlgbp.hu (23 - start year, a - szekció, f - part-time)
    # Computer test accounts: x.y.12g@szlgbp.hu (if there is any numbering g, it indicates test account)

    @property
    def is_in_school_domain(self) -> bool:
        domain = (self.school_domain or "").strip().lower()
        if not domain:
            return False
        if not domain.startswith("@"):
            domain = "@" + domain.lstrip("@")
        return self.email.endswith(domain)

    @property
    def is_student(self) -> bool:
        match = re.search(r"\.\d{2,4}[a-z](f)?$", self.local_part)
        return self.is_in_school_domain and not self.local_part.startswith("x.") and bool(match and not match.group(1))

    @property
    def is_part_time_student(self) -> bool:
        return (
            self.is_in_school_domain
            and not self.local_part.startswith("x.")
            and bool(re.search(r"\.\d{2,4}[a-z]f$", self.local_part))
        )

    @property
    def class_from_email(self) -> tuple[int, str] | None:
        """Return the student's cohort and section encoded in a school e-mail."""
        if not (self.is_student or self.is_part_time_student):
            return None
        match = re.search(r"\.(\d{2,4})([a-z])f?$", self.local_part)
        if not match:
            return None

        year_text, section = match.groups()
        year = int(year_text)
        current_year = datetime.date.today().year
        if len(year_text) == 2:
            candidates = [century + year for century in (1900, 2000, 2100)]
            plausible = [candidate for candidate in candidates if candidate <= current_year + 5]
            year = min(plausible, key=lambda candidate: abs(candidate - current_year))
        if year < 1900 or year > current_year + 5:
            return None
        return year, section.upper()

    @property
    def is_computer_test_account(self) -> bool:
        return (
            self.is_in_school_domain
            and self.local_part.startswith("x.")
            and any(char.isdigit() for char in self.local_part.split(".")[-1])
        )
    
    @property
    def is_group_email(self) -> bool:
        return (
            self.is_in_school_domain
            and not self.local_part.startswith("x.")
            and "." not in self.local_part
            and not any(char.isdigit() for char in self.local_part)
        )

    @property
    def is_teacher_or_school_employee(self) -> bool:
        return (
            self.is_in_school_domain
            and not self.local_part.startswith("x.")
            and "." in self.local_part
            and not bool(re.search(r"\.\d{2,4}[a-z]f?$", self.local_part))
            and not any(char.isdigit() for char in self.local_part)
        )

    @property
    def what_am_i(self) -> str:

        account_types = [
            (self.is_student, "Nappali tagozatos diák"),
            (self.is_part_time_student, "Esti tagozatos diák"),
            (self.is_computer_test_account, "Számítógéptermi teszt fiók"),
            (self.is_group_email, "Csoportos e-mail"),
            (self.is_teacher_or_school_employee, "Tanár/iskolai alkalmazott"),
        ]

        for attr_value, description in account_types:
            if attr_value   :
                return description
        return "Ismeretlen"


class CustomUserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    privacy_consent_at = models.DateTimeField(
        "adatkezelési hozzájárulás időpontja",
        null=True,
        blank=True,
        editable=False,
    )
    import_sources = models.JSONField(
        "adatimport-források",
        default=list,
        blank=True,
        help_text=(
            "Azon alkalmazások neve és stabil azonosítója, amelyekből a fiók adatait "
            "importáltuk. Az importáló felület bővíti, nem cseréli le a listát."
        ),
    )
    is_group_mailbox = models.BooleanField(
        "csoportos postafiók",
        default=False,
        help_text="A címtár külön csoportos postafiókként jeleníti meg; ezt ne az e-mail-címből következtesd.",
    )
    oidc_subject = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Overrides PermissionsMixin.groups only to give it a clear, Hungarian name.
    groups = models.ManyToManyField(
        Group,
        verbose_name="jogosultsági körök",
        blank=True,
        help_text=(
            "A felhasználó jogosultsági körei: ezek határozzák meg, mit tehet az SZLG+ "
            "adminisztrációs felületén. Az alkalmazásoknak nem kerülnek át."
        ),
        related_name="user_set",
        related_query_name="user",
    )
    manual_groups = models.ManyToManyField(
        "api.ManualGroup",
        verbose_name="iskolai csoportok",
        blank=True,
        help_text=(
            "A felhasználó iskolai csoportjai (osztály, szakkör stb.): ezeket az "
            "alkalmazások az ID tokenben megkapják."
        ),
        related_name="members",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = CustomUserManager()

    @property
    def is_student(self) -> bool:
        """Check if the user has a student profile."""
        if self.is_group_mailbox:
            return False
        if hasattr(self, "student_profile"):
            return True
        if email_info(self.email).is_student:
            return True
        return False

    @property
    def is_part_time_student(self) -> bool:
        """Check if the user has a part-time student profile."""
        if self.is_group_mailbox:
            return False
        if hasattr(self, "part_time_student_profile"):
            return True
        if email_info(self.email).is_part_time_student:
            return True
        return False

    @property
    def is_computer_test_account(self) -> bool:
        """Check if the user has a computer test account profile."""
        if self.is_group_mailbox:
            return False
        if hasattr(self, "computer_test_account_profile"):
            return True
        if email_info(self.email).is_computer_test_account:
            return True
        return False

    @property
    def is_group_email(self) -> bool:
        """Check if the user has a group email profile."""
        return self.is_group_mailbox

    @property
    def is_teacher_or_school_employee(self) -> bool:
        """Check if the user has a teacher or school employee profile."""
        if self.is_group_mailbox:
            return False
        if hasattr(self, "teacher_or_school_employee_profile"):
            return True
        if email_info(self.email).is_teacher_or_school_employee:
            return True
        return False

    @property
    def account_type(self) -> str:
        if self.is_group_mailbox:
            return "Csoportos e-mail"
        account_types = [
            (self.is_student, "Nappali tagozatos diák"),
            (self.is_part_time_student, "Esti tagozatos diák"),
            (self.is_computer_test_account, "Számítógéptermi teszt fiók"),
            (self.is_group_email, "Csoportos e-mail"),
            (self.is_teacher_or_school_employee, "Tanár/iskolai alkalmazott"),
        ]
        for attr_value, description in account_types:
            if attr_value:
                return description
        return "Ismeretlen"

    @property
    def is_teacher(self) -> bool:
        return not self.is_group_mailbox and hasattr(self, "teacher_profile")

    @property
    def smart_groups(self) -> dict[str, bool]:
        return {
            "student": self.is_student,
            "teacher": self.is_teacher,
            "staff": self.is_staff,
            "part_time_student": self.is_part_time_student,
            "computer_test_account": self.is_computer_test_account,
            "group_email": self.is_group_email,
            "teacher_or_school_employee": self.is_teacher_or_school_employee,
        }

    def get_full_name(self) -> str:
        return f"{self.last_name} {self.first_name}".strip()

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


class StudentProfile(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    om_id = models.CharField(max_length=32, blank=True, verbose_name="OM azonosító", help_text="A diák OM azonosítója.")

    kezdes_eve = models.PositiveIntegerField(blank=True, null=True, verbose_name="Kezdés éve", help_text="A diák iskolai tanulmányainak kezdési éve.")

    szekcio = models.CharField(max_length=10, blank=True, verbose_name="Szekció", help_text="A diák iskolai szekciója.")

    tagozat = models.ForeignKey(
        "api.Tagozat",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="Tagozat",
        help_text="A diák iskolai tagozata.",
    )

    @property
    def osztaly(self) -> str:
        return year_szekcio_to_str(self.kezdes_eve, self.szekcio)

    class Meta:
        verbose_name = "diák profil"
        verbose_name_plural = "diák profilok"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self) -> str:
        return f"Student: {self.user.get_full_name() if self.user.get_full_name() else self.user.email}"

class Tagozat(models.Model):
    name = models.CharField(max_length=100, verbose_name="Tagozat", help_text="A diák iskolai tagozata.")
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "tagozat"
        verbose_name_plural = "tagozatok"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)   

    def __str__(self) -> str:
        return self.name

class TeacherProfile(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
    )
    employee_number = models.CharField(max_length=32, blank=True)

    def __str__(self) -> str:
        return f"Teacher: {self.user.get_full_name() if self.user.get_full_name() else self.user.email}"


class ManualGroup(MPTTModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(
        "közérdekű",
        default=False,
        help_text="A közérdekű csoport megjelenik a böngészhető csoportlistában.",
    )
    created_by = models.ForeignKey(
        "api.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_manual_groups",
        verbose_name="létrehozó",
    )
    managers = models.ManyToManyField(
        "api.CustomUser",
        blank=True,
        related_name="managed_manual_groups",
        verbose_name="csoportkezelők",
    )
    parent = TreeForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        ordering = ["tree_id", "lft"]
        verbose_name = "iskolai csoport"
        verbose_name_plural = "iskolai csoportok"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def full_path(self) -> str:
        return "/".join(
            self.get_ancestors(include_self=True).values_list("slug", flat=True)
        )

    @property
    def directory_key(self) -> str:
        return f"manual-{self.slug}"

    def __str__(self) -> str:
        return self.full_path


class SchoolClass(models.Model):
    """An administrable class record; student membership is derived from profiles."""

    start_year = models.PositiveIntegerField("kezdés éve")
    section = models.CharField("szekció", max_length=10)
    homeroom_teacher = models.ForeignKey(
        "api.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homeroom_classes",
        verbose_name="osztályfőnök",
    )
    deputy_teacher = models.ForeignKey(
        "api.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deputy_classes",
        verbose_name="osztályfőnök-helyettes",
    )

    class Meta:
        ordering = ["start_year", "section"]
        constraints = [
            models.UniqueConstraint(
                fields=("start_year", "section"), name="api_unique_school_class"
            )
        ]
        verbose_name = "osztály"
        verbose_name_plural = "osztályok"

    @property
    def name(self) -> str:
        return year_szekcio_to_str(self.start_year, self.section)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.section = self.section.strip().upper()
        super().save(*args, **kwargs)

    def clean(self):
        self.section = self.section.strip().upper()
        errors = {}
        for field, label in (
            ("homeroom_teacher", "Osztályfőnök"),
            ("deputy_teacher", "Osztályfőnök-helyettes"),
        ):
            user_id = getattr(self, f"{field}_id", None)
            if user_id and not CustomUser.objects.filter(
                pk=user_id,
                is_group_mailbox=False,
                teacher_profile__isnull=False,
            ).exists():
                errors[field] = f"{label} csak tanári profillal rendelkező fiók lehet."
        if errors:
            raise ValidationError(errors)


class InstitutionalRole(models.Model):
    """A school-level role and its holders, independent of SZLG+ permissions."""

    slug = models.SlugField("azonosító", max_length=80, unique=True)
    name = models.CharField("szerepkör neve", max_length=120)
    description = models.TextField("leírás", blank=True)
    is_required = models.BooleanField(
        "kötelezően kitöltendő",
        default=True,
        help_text="A hiányzó szerepkör megjelenik az adminisztrátori teendőlistában.",
    )
    members = models.ManyToManyField(
        "api.CustomUser",
        blank=True,
        related_name="institutional_roles",
        verbose_name="betöltők",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "iskolai szerepkör"
        verbose_name_plural = "iskolai szerepkörök"

    def __str__(self) -> str:
        return self.name


class GroupMailboxAssociation(models.Model):
    """Connects an explicitly marked mailbox account to a directory group key."""

    mailbox = models.ForeignKey(
        "api.CustomUser",
        on_delete=models.CASCADE,
        related_name="group_mailbox_associations",
        verbose_name="csoportos postafiók",
    )
    group_key = models.CharField("címtárcsoport", max_length=180)

    class Meta:
        ordering = ["group_key", "mailbox__email"]
        constraints = [
            models.UniqueConstraint(
                fields=("mailbox", "group_key"), name="api_unique_group_mailbox_link"
            )
        ]
        verbose_name = "csoportos postafiók-kapcsolat"
        verbose_name_plural = "csoportos postafiók-kapcsolatok"

    def __str__(self) -> str:
        return f"{self.mailbox.email} → {self.group_key}"

    def clean(self):
        if self.mailbox_id and not self.mailbox.is_group_mailbox:
            raise ValidationError(
                {"mailbox": "Csak csoportos postafiókként megjelölt fiók kapcsolható csoporthoz."}
            )


class PermissionGroup(Group):
    """Django's built-in Group, shown in the admin as an access-rights circle."""

    class Meta:
        proxy = True
        verbose_name = "jogosultsági kör"
        verbose_name_plural = "jogosultsági körök"


class Passkey(models.Model):
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="passkeys",
    )
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    transports = models.CharField(max_length=200, blank=True, default="")
    name = models.CharField("név", max_length=80, blank=True, default="Jelkulcs")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "jelkulcs"
        verbose_name_plural = "jelkulcsok"

    def __str__(self) -> str:
        return f"Jelkulcs: {self.name} ({self.user.get_full_name() or self.user.email})"


class WebAuthnChallenge(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    challenge = models.CharField(max_length=512)
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="webauthn_challenges",
        null=True,
        blank=True,
    )
    account_hint_provided = models.BooleanField(default=False)
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self) -> str:
        return f"WebAuthnChallenge: {self.key} for {self.user.get_full_name() if self.user.get_full_name() else self.user.email}"

class ApplicationProfile(models.Model):
    """Public details about an OAuth application, shown on the consent screen."""

    application = models.OneToOneField(
        "oauth2_provider.Application",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    developer = models.CharField("fejlesztő", max_length=120)
    short_description = models.CharField("rövid leírás", max_length=160)
    required_group_keys = models.JSONField(
        "alkalmazáshoz szükséges csoportok",
        default=list,
        blank=True,
        help_text="Ha meg van adva, legalább egy csoporttagság szükséges az alkalmazás-hozzáféréshez.",
    )
    launch_url = models.URLField(
        "indítási URL",
        blank=True,
        help_text="Az alkalmazás kezdőlapja, ahová a felhasználó az appcsempéről továbblép.",
    )
    logo = models.ImageField(
        "logó",
        upload_to="app-logos/",
        blank=True,
        help_text="Négyzet alakú PNG, JPEG vagy WebP kép (SVG nem engedélyezett).",
    )
    verified = models.BooleanField(
        "ellenőrzött",
        default=False,
        help_text="Az iskola által ellenőrzött alkalmazás. Csak adminisztrátor állíthatja.",
    )

    class Meta:
        verbose_name = "alkalmazásprofil"
        verbose_name_plural = "alkalmazásprofilok"

    def __str__(self) -> str:
        return f"{self.application.name} ({self.developer})"


class UserAppConnection(models.Model):
    """A user's durable consent and sign-in preference for one OAuth app."""

    class InteractionMode(models.TextChoices):
        AUTOMATIC = "auto", "Automatikus átirányítás"
        CONFIRM = "confirm", "Megerősítés és fiókváltás"

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="app_connections",
        verbose_name="felhasználó",
    )
    application = models.ForeignKey(
        "oauth2_provider.Application",
        on_delete=models.CASCADE,
        related_name="user_connections",
        verbose_name="alkalmazás",
    )
    scopes = models.JSONField(
        default=list,
        verbose_name="engedélyezett jogosultságok",
        help_text="Az alkalmazás által korábban jóváhagyott OAuth-jogosultságok.",
    )
    interaction_mode = models.CharField(
        "belépési mód",
        max_length=8,
        choices=InteractionMode.choices,
        default=InteractionMode.CONFIRM,
        help_text=(
            "Automatikus módban a korábban engedélyezett alkalmazás azonnal továbbirányít; "
            "megerősítésnél belépés előtt egy fiókválasztó oldal jelenik meg."
        ),
    )
    created_at = models.DateTimeField("első engedélyezés", auto_now_add=True)
    last_used_at = models.DateTimeField("utolsó belépés", null=True, blank=True)

    class Meta:
        verbose_name = "alkalmazáskapcsolat"
        verbose_name_plural = "alkalmazáskapcsolatok"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "application"),
                name="api_unique_user_app_connection",
            )
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.user.email} · {self.application.name}"


class GlobalConfig(SingletonModel):
    """Site-wide settings. Exactly one row exists; it is created by a migration."""

    promote_passkey = models.BooleanField(
        "jelkulcs ajánlása",
        default=True,
        help_text=(
            "Ha be van kapcsolva, a jelszavas bejelentkezés után egy képernyő felajánlja "
            "a jelkulcs gyors beállítását azoknak, akiknek még nincs, illetve azoknak, "
            "akik jelszóval léptek be egy olyan eszközön, ahol még nincs jelkulcsuk."
        ),
    )

    school_domain = models.CharField(
        "iskolai domain",
        max_length=255,
        default="@szlgbp.hu",
        help_text="Az iskola által használt e-mail domain.",
        blank=True,
        null=True,
    )

    administrator_contacts = models.ManyToManyField(
        "api.CustomUser",
        verbose_name="SZLG+ kapcsolattartók",
        blank=True,
        related_name="administrator_contact_for",
        help_text=(
            "Az itt kiválasztott felhasználók elérhetősége megjelenik az adatkezelési "
            "tájékoztatóban és az iskolai címmel regisztrálóknak szóló üzenetben."
        ),
    )

    class Meta:
        verbose_name = "globális beállítások"

    def delete(self, *args, **kwargs):
        # The single configuration row must always exist.
        return 0, {}

    def __str__(self) -> str:
        return "Globális beállítások"


def get_school_domain() -> str:
    config = GlobalConfig.objects.only("school_domain").first()
    return config.school_domain if config and config.school_domain else "@szlgbp.hu"
