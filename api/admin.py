from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from mptt.admin import DraggableMPTTAdmin

from .models import CustomUser, ManualGroup, Passkey, StudentProfile, TeacherProfile


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
