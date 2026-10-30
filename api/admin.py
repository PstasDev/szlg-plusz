from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from mptt.admin import DraggableMPTTAdmin
from oauth2_provider.admin import application_admin_class
from oauth2_provider.models import get_application_model
from solo.admin import SingletonModelAdmin

from .directory import SMART_DIRECTORY_GROUPS
from .models import (
    AccountReviewStatus,
    ApplicationProfile,
    CustomUser,
    GlobalConfig,
    ManualReviewRequest,
    ManualGroup,
    Passkey,
    PermissionGroup,
    StudentProfile,
    TeacherProfile,
    Tagozat,
)

Application = get_application_model()


class BulkMoveManualGroupsForm(forms.Form):
    parent = forms.ModelChoiceField(
        label="Új szülőcsoport",
        queryset=ManualGroup.objects.none(),
        required=False,
        empty_label="Gyökérszint (nincs szülő)",
        help_text="A kijelölt csoportok a kiválasztott szülő alá kerülnek.",
    )

    def __init__(self, *args, excluded_parent_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = ManualGroup.objects.exclude(
            pk__in=excluded_parent_ids
        )


def smart_group_summaries():
    """Build the admin-only, read-only summary of calculated SmartGroups."""
    groups = SMART_DIRECTORY_GROUPS
    member_counts = {key: 0 for key, _name, _description in groups}
    users = CustomUser.objects.filter(is_active=True).select_related(
        "student_profile", "teacher_profile"
    )
    for user in users:
        for key, enabled in user.smart_groups.items():
            if enabled and key in member_counts:
                member_counts[key] += 1

    return [
        {
            "key": f"smart-{key}",
            "name": name,
            "description": description,
            "member_count": member_counts[key],
        }
        for key, name, description in groups
    ]


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
    list_display = (
        "email",
        "last_name",
        "first_name",
        "is_active",
        "is_staff",
        "account_review_badge",
    )
    list_filter = ("is_active", "is_staff", "account_review_status")
    search_fields = ("email", "last_name", "first_name")
    filter_horizontal = ("groups", "user_permissions", "manual_groups")
    readonly_fields = ("privacy_consent_at", "import_sources", "account_review_status")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Manuális felülvizsgálat", {"fields": ("account_review_status",)}),
        (
            "Személyes adatok",
            {
                "fields": (
                    "last_name",
                    "first_name",
                    "phone",
                    "date_of_birth",
                    "email_verified",
                    "privacy_consent_at",
                )
            },
        ),
        ("Importálási előzmények", {"fields": ("import_sources",)}),
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
                    "last_name",
                    "first_name",
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

    @admin.display(description="Felülvizsgálati állapot", ordering="account_review_status")
    def account_review_badge(self, user):
        labels = {
            AccountReviewStatus.PENDING: ("#805600", "◷ Felülvizsgálatra vár"),
            AccountReviewStatus.APPROVED: ("#146c2e", "✓ Jóváhagyva"),
            AccountReviewStatus.REJECTED: ("#b3261e", "✕ Elutasítva"),
        }
        color, label = labels.get(
            user.account_review_status,
            ("#5f6a6c", "— Nincs szükség felülvizsgálatra"),
        )
        return format_html('<span style="color: {}; font-weight: 600">{}</span>', color, label)


# The built-in Group is shown as "Jogosultsági kör" (access-rights circle) so it
# cannot be confused with the school groups (ManualGroup).
admin.site.unregister(Group)


@admin.register(PermissionGroup)
class PermissionGroupAdmin(GroupAdmin):
    pass


@admin.register(ManualGroup)
class ManualGroupAdmin(DraggableMPTTAdmin):
    mptt_indent_field = "name"
    change_list_template = "admin/api/manualgroup/change_list.html"
    list_display = ("tree_actions", "indented_title", "slug", "is_public")
    list_filter = ("is_public",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "description")
    actions = (
        "make_selected_groups_public",
        "make_selected_groups_private",
        "move_selected_groups_under_parent",
        "delete_selected",
    )

    def changelist_view(self, request, extra_context=None):
        extra_context = {
            **(extra_context or {}),
            "smart_groups": smart_group_summaries(),
        }
        return super().changelist_view(request, extra_context=extra_context)

    @admin.action(
        description="Kijelölt csoportok közérdekűvé tétele",
        permissions=("change",),
    )
    def make_selected_groups_public(self, request, queryset):
        updated = queryset.update(is_public=True)
        self.message_user(
            request, f"{updated} kijelölt csoport közérdekűvé téve.", messages.SUCCESS
        )

    @admin.action(
        description="Kijelölt csoportok közérdekű jelzőjének kikapcsolása",
        permissions=("change",),
    )
    def make_selected_groups_private(self, request, queryset):
        updated = queryset.update(is_public=False)
        self.message_user(
            request,
            f"{updated} kijelölt csoport közérdekű jelzője kikapcsolva.",
            messages.SUCCESS,
        )

    @admin.action(
        description="Kijelölt csoportok áthelyezése szülő alá…",
        permissions=("change",),
    )
    def move_selected_groups_under_parent(self, request, queryset):
        groups = list(queryset)
        excluded_parent_ids = self._excluded_parent_ids(groups)
        return render(
            request,
            "admin/api/manualgroup/bulk_move.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Kijelölt csoportok áthelyezése",
                "groups": groups,
                "selected_ids": [str(group.pk) for group in groups],
                "form": BulkMoveManualGroupsForm(
                    excluded_parent_ids=excluded_parent_ids
                ),
                "cancel_url": reverse("admin:api_manualgroup_changelist"),
            },
        )

    def _excluded_parent_ids(self, groups):
        excluded_ids = set()
        for group in groups:
            excluded_ids.add(group.pk)
            excluded_ids.update(
                group.get_descendants().values_list("pk", flat=True)
            )
        return excluded_ids

    def get_urls(self):
        custom_urls = [
            path(
                "bulk-move/",
                self.admin_site.admin_view(self.bulk_move_view),
                name="api_manualgroup_bulk_move",
            ),
        ]
        return custom_urls + super().get_urls()

    def bulk_move_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:api_manualgroup_changelist"))

        try:
            requested_ids = {
                int(group_id)
                for group_id in request.POST.getlist(ACTION_CHECKBOX_NAME)
            }
        except (TypeError, ValueError):
            requested_ids = set()
        groups = list(self.get_queryset(request).filter(pk__in=requested_ids))
        if not groups or {group.pk for group in groups} != requested_ids:
            self.message_user(
                request,
                "A kijelölt csoportok nem találhatók; az áthelyezés nem történt meg.",
                messages.ERROR,
            )
            return HttpResponseRedirect(reverse("admin:api_manualgroup_changelist"))

        excluded_parent_ids = self._excluded_parent_ids(groups)
        form = BulkMoveManualGroupsForm(
            request.POST, excluded_parent_ids=excluded_parent_ids
        )
        if form.is_valid():
            selected_ids = {group.pk for group in groups}
            roots = [
                group
                for group in groups
                if not any(
                    ancestor.pk in selected_ids
                    for ancestor in group.get_ancestors()
                )
            ]
            parent = form.cleaned_data["parent"]
            with transaction.atomic():
                for group in roots:
                    group.move_to(parent, position="last-child")

            self.message_user(
                request,
                f"{len(roots)} csoport áthelyezve; "
                "a kijelölt csoportok alatti hierarchia megmaradt.",
                messages.SUCCESS,
            )
            return HttpResponseRedirect(reverse("admin:api_manualgroup_changelist"))

        return render(
            request,
            "admin/api/manualgroup/bulk_move.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Kijelölt csoportok áthelyezése",
                "groups": groups,
                "selected_ids": [str(group.pk) for group in groups],
                "form": form,
                "cancel_url": reverse("admin:api_manualgroup_changelist"),
            },
        )


@admin.register(Passkey)
class PasskeyAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created_at", "last_used_at")
    search_fields = ("name", "user__email")
    readonly_fields = ("credential_id", "public_key", "sign_count")


@admin.register(ManualReviewRequest)
class ManualReviewRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "applicant_type", "review_status", "submitted_at", "reviewed_at")
    list_filter = ("applicant_type", "user__account_review_status")
    search_fields = ("user__email", "user__first_name", "user__last_name", "position")
    readonly_fields = ("submitted_at", "reviewed_at", "reviewed_by")

    @admin.display(description="Állapot", ordering="user__account_review_status")
    def review_status(self, review_request):
        return review_request.user.get_account_review_status_display()


@admin.register(GlobalConfig)
class GlobalConfigAdmin(SingletonModelAdmin):
    """Single-row settings: no add or delete, the list page opens the form directly."""

    filter_horizontal = ("administrator_contacts",)

@admin.register(Tagozat)
class TagozatAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")
