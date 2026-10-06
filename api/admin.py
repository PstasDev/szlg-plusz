from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from mptt.admin import DraggableMPTTAdmin
from oauth2_provider.admin import application_admin_class
from oauth2_provider.models import get_application_model

from .models import (
    ApplicationProfile,
    CustomUser,
    ManualGroup,
    Passkey,
    StudentProfile,
    TeacherProfile,
)

Application = get_application_model()


class ApplicationProfileInline(admin.StackedInline):
    model = ApplicationProfile
    extra = 0
    max_num = 1
    can_delete = False


admin.site.unregister(Application)


@admin.register(Application)
class SZLGApplicationAdmin(application_admin_class):
    inlines = (ApplicationProfileInline,)


class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    extra = 0


class TeacherProfileInline(admin.StackedInline):
    model = TeacherProfile
    extra = 0


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    filter_horizontal = ("groups", "user_permissions", "manual_groups")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "phone",
                    "date_of_birth",
                    "email_verified",
                )
            },
        ),
        ("Membership", {"fields": ("manual_groups",)}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )
    inlines = (StudentProfileInline, TeacherProfileInline)


@admin.register(ManualGroup)
class ManualGroupAdmin(DraggableMPTTAdmin):
    mptt_indent_field = "name"
    list_display = ("tree_actions", "indented_title", "slug")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "description")


@admin.register(Passkey)
class PasskeyAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created_at", "last_used_at")
    search_fields = ("name", "user__email")
    readonly_fields = ("credential_id", "public_key", "sign_count")
