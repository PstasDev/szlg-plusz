from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from mptt.admin import DraggableMPTTAdmin
from oauth2_provider.admin import application_admin_class
from oauth2_provider.models import get_application_model
from solo.admin import SingletonModelAdmin

from .models import (
    ApplicationProfile,
    CustomUser,
    GlobalConfig,
    ManualGroup,
    Passkey,
    PermissionGroup,
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
            "Személyes adatok",
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
        ("Iskolai csoportok", {"fields": ("manual_groups",)}),
        (
            "Jogosultságok",
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
        ("Fontos dátumok", {"fields": ("last_login", "date_joined")}),
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


# The built-in Group is shown as "Jogosultsági kör" (access-rights circle) so it
# cannot be confused with the school groups (ManualGroup).
admin.site.unregister(Group)


@admin.register(PermissionGroup)
class PermissionGroupAdmin(GroupAdmin):
    pass


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


@admin.register(GlobalConfig)
class GlobalConfigAdmin(SingletonModelAdmin):
    """Single-row settings: no add or delete, the list page opens the form directly."""
