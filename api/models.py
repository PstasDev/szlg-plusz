import uuid
import datetime

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify
from mptt.fields import TreeForeignKey
from mptt.models import MPTTModel

def year_tagozat_to_str(startYear: int, tagozat: str) -> str:
    current_year = datetime.date.today().year
    current_month = datetime.date.today().month
    school_year = current_year
    if current_month < 9:
        school_year -= 1

    graduation_year = startYear + 4
    if tagozat in ['A', 'E', 'F']:
        graduation_year += 1

    if school_year >= graduation_year:
        return f"{startYear}{tagozat}"
    else:
        years_passed = school_year - startYear
        if tagozat in ['A', 'E', 'F']:
            if years_passed == 0:
                return f"KNY{tagozat}" if tagozat == 'A' else f"NY{tagozat}"
            else:
                # years_passed 1 = 9. F, years_passed 2 = 10. F, etc.
                return f"{8 + years_passed}. {tagozat}"
        else:
            # B, C, D classes: years_passed 0 = 9., years_passed 1 = 10., etc.
            return f"{9 + years_passed}. {tagozat}"

def class_str_to_year_tagozat(class_str: str) -> tuple[int, str]:
    # Smart function that can convert from any typo if there is a valid class: 
    # KNYA, knya, nya, NYA, 0.a, 0.A, 0A, 9.NYA, 9. KNYA -> KNYA
    # 10F, 2023F, 10. F, 10.f -> 10F
    # post-graduate classes, are tricky, drop an error if there are certainly two valid answers (for example 2000A can be a class that either refers to the class starting in 2000 with tagozat A or a class graduated in 2000 with tagozat A)
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
    oidc_subject = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    manual_groups = models.ManyToManyField(
        "api.ManualGroup",
        blank=True,
        related_name="members",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = CustomUserManager()

    @property
    def is_student(self) -> bool:
        return hasattr(self, "student_profile")

    @property
    def is_teacher(self) -> bool:
        return hasattr(self, "teacher_profile")

    @property
    def smart_groups(self) -> dict[str, bool]:
        return {
            "student": self.is_student,
            "teacher": self.is_teacher,
            "staff": self.is_staff,
        }

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
    student_number = models.CharField(max_length=32, blank=True)

    def __str__(self) -> str:
        return f"Student: {self.user.email}"


class TeacherProfile(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
    )
    employee_number = models.CharField(max_length=32, blank=True)

    def __str__(self) -> str:
        return f"Teacher: {self.user.email}"


class ManualGroup(MPTTModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
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
        verbose_name = "manual group"
        verbose_name_plural = "manual groups"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def full_path(self) -> str:
        return "/".join(
            self.get_ancestors(include_self=True).values_list("slug", flat=True)
        )

    def __str__(self) -> str:
        return self.full_path


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
    name = models.CharField(max_length=80, blank=True, default="Passkey")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.email} - {self.name}"


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

class ApplicationProfile(models.Model):
    """Public details about an OAuth application, shown on the consent screen."""

    application = models.OneToOneField(
        "oauth2_provider.Application",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    developer = models.CharField("fejlesztő", max_length=120)
    short_description = models.CharField("rövid leírás", max_length=160)
    logo = models.ImageField(
        "logó",
        upload_to="app-logos/",
        blank=True,
        help_text="Négyzet alakú PNG, JPEG vagy WebP kép (SVG nem engedélyezett).",
    )

    class Meta:
        verbose_name = "alkalmazásprofil"
        verbose_name_plural = "alkalmazásprofilok"

    def __str__(self) -> str:
        return f"{self.application.name} ({self.developer})"
