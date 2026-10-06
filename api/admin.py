from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.utils import timezone
from django import forms
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.contrib import messages
from .models import (
    Profile, Osztaly, Mulasztas, IgazolasTipus, Igazolas, 
    SystemMessage, TanitasiSzunet, Override, APIMetrics,
    ChangeNote, ChangeNoteImage
)
from .admin_utils import generate_strong_password


# ---------------------------------------------------------------------------
# Shared bulk action helpers
# ---------------------------------------------------------------------------

@admin.action(description='✅ Kijelöltek archiválása (archived = True)')
def mark_archived(modeladmin, request, queryset):
    now = timezone.now()
    # Try to set archive_date if the model has it, otherwise skip
    has_archive_date = any(f.name == 'archive_date' for f in queryset.model._meta.get_fields())
    if has_archive_date:
        updated = queryset.filter(archived=False).update(archived=True, archive_date=now)
    else:
        updated = queryset.filter(archived=False).update(archived=True)
    modeladmin.message_user(request, f'{updated} rekord archiválva.')


@admin.action(description='↩️ Kijelöltek visszaállítása (archived = False)')
def mark_unarchived(modeladmin, request, queryset):
    has_archive_date = any(f.name == 'archive_date' for f in queryset.model._meta.get_fields())
    if has_archive_date:
        updated = queryset.filter(archived=True).update(archived=False, archive_date=None)
    else:
        updated = queryset.filter(archived=True).update(archived=False)
    modeladmin.message_user(request, f'{updated} rekord visszaállítva.')


# Custom filter for last_login that excludes nulls
class HasLoggedInFilter(admin.SimpleListFilter):
    title = 'bejelentkezés státusz'
    parameter_name = 'has_logged_in'
    
    def lookups(self, request, model_admin):
        return (
            ('yes', 'Bejelentkezett már'),
            ('no', 'Még nem jelentkezett be'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(last_login__isnull=False)
        if self.value() == 'no':
            return queryset.filter(last_login__isnull=True)
        return queryset


# ---------------------------------------------------------------------------
# Forms used by the multi-step import wizard
# ---------------------------------------------------------------------------

class EmailListForm(forms.Form):
    """Step 1 – paste email list and choose target class."""
    email_list = forms.CharField(
        label='E-mail címek (soronként egy)',
        widget=forms.Textarea(attrs={'rows': 12, 'cols': 60,
                                     'placeholder': 'pelda@iskola.hu\nmásik@iskola.hu'}),
        help_text='Minden sorba egy e-mail cím. Már meglévő felhasználók frissítve lesznek.',
    )
    osztaly = forms.ModelChoiceField(
        queryset=Osztaly.objects.filter(archived=False).order_by('kezdes_eve', 'tagozat'),
        label='Osztály',
        help_text='Az összes új tanuló ebbe az osztályba kerül.',
    )


class NamesFormSet(forms.BaseFormSet):
    pass


def make_name_form(email, existing_user=None):
    """Return a Form class pre-populated with existing user data if available."""

    class NameForm(forms.Form):
        email = forms.EmailField(widget=forms.HiddenInput())
        last_name = forms.CharField(label='Vezetéknév', max_length=150)
        first_name = forms.CharField(label='Keresztnév', max_length=150)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not args and not kwargs.get('data'):
                # Pre-populate with existing user data
                self.fields['email'].initial = email
                if existing_user:
                    self.fields['last_name'].initial = existing_user.last_name
                    self.fields['first_name'].initial = existing_user.first_name

    return NameForm


# ---------------------------------------------------------------------------
# Custom User Admin
# ---------------------------------------------------------------------------

class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'last_login', 'is_staff', 'is_active']
    list_filter = BaseUserAdmin.list_filter + (HasLoggedInFilter,)
    actions = ['flip_first_last_name', 'import_via_email_list']

    # ------------------------------------------------------------------
    # Custom URLs for the import wizard
    # ------------------------------------------------------------------

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'import-email-list/',
                self.admin_site.admin_view(self.import_email_list_step1),
                name='auth_user_import_email_list_step1',
            ),
            path(
                'import-email-list/names/',
                self.admin_site.admin_view(self.import_email_list_step2),
                name='auth_user_import_email_list_step2',
            ),
            path(
                'import-email-list/confirm/',
                self.admin_site.admin_view(self.import_email_list_confirm),
                name='auth_user_import_email_list_confirm',
            ),
        ]
        return custom + urls

    # ------------------------------------------------------------------
    # Action – just redirects to step 1
    # ------------------------------------------------------------------

    @admin.action(description='📥 Osztály importálása e-mail lista alapján')
    def import_via_email_list(self, request, queryset):
        url = reverse('admin:auth_user_import_email_list_step1')
        return redirect(url)

    # ------------------------------------------------------------------
    # Step 1 – email list + choose class
    # ------------------------------------------------------------------

    def import_email_list_step1(self, request):
        if request.method == 'POST':
            form = EmailListForm(request.POST)
            if form.is_valid():
                raw = form.cleaned_data['email_list']
                emails = [e.strip() for e in raw.splitlines() if e.strip()]
                if not emails:
                    form.add_error('email_list', 'Legalább egy e-mail cím szükséges.')
                else:
                    # Store in session and move to step 2
                    request.session['import_emails'] = emails
                    request.session['import_osztaly_id'] = form.cleaned_data['osztaly'].pk
                    return redirect(reverse('admin:auth_user_import_email_list_step2'))
        else:
            form = EmailListForm()

        context = {
            **self.admin_site.each_context(request),
            'title': 'Osztály importálása e-mail lista alapján – 1. lépés',
            'form': form,
            'opts': self.model._meta,
            'step': 1,
        }
        return TemplateResponse(request, 'admin/import_email_list_step1.html', context)

    # ------------------------------------------------------------------
    # Step 2 – enter/confirm names for each email
    # ------------------------------------------------------------------

    def import_email_list_step2(self, request):
        emails = request.session.get('import_emails')
        osztaly_id = request.session.get('import_osztaly_id')
        if not emails or not osztaly_id:
            messages.error(request, 'Lejárt a munkamenet. Kezdje elölről.')
            return redirect(reverse('admin:auth_user_import_email_list_step1'))

        try:
            osztaly = Osztaly.objects.get(pk=osztaly_id)
        except Osztaly.DoesNotExist:
            messages.error(request, 'A kiválasztott osztály nem található.')
            return redirect(reverse('admin:auth_user_import_email_list_step1'))

        existing_users = {u.email: u for u in User.objects.filter(email__in=emails)}

        if request.method == 'POST':
            rows = []
            valid = True
            for idx, email in enumerate(emails):
                last = request.POST.get(f'last_name_{idx}', '').strip()
                first = request.POST.get(f'first_name_{idx}', '').strip()
                if not last or not first:
                    valid = False
                rows.append({'email': email, 'last_name': last, 'first_name': first,
                             'exists': email in existing_users})

            if valid:
                # Store names in session and proceed to confirm
                request.session['import_rows'] = rows
                return redirect(reverse('admin:auth_user_import_email_list_confirm'))
            else:
                messages.error(request, 'Minden sorban meg kell adni a nevet.')
                # Fall through to re-render with submitted values

        else:
            rows = []
            for email in emails:
                u = existing_users.get(email)
                rows.append({
                    'email': email,
                    'last_name': u.last_name if u else '',
                    'first_name': u.first_name if u else '',
                    'exists': bool(u),
                })

        context = {
            **self.admin_site.each_context(request),
            'title': 'Osztály importálása e-mail lista alapján – 2. lépés',
            'rows': rows,
            'osztaly': osztaly,
            'opts': self.model._meta,
            'step': 2,
        }
        return TemplateResponse(request, 'admin/import_email_list_step2.html', context)

    # ------------------------------------------------------------------
    # Step 3 – do the actual import
    # ------------------------------------------------------------------

    def import_email_list_confirm(self, request):
        rows = request.session.get('import_rows')
        osztaly_id = request.session.get('import_osztaly_id')
        if not rows or not osztaly_id:
            messages.error(request, 'Lejárt a munkamenet. Kezdje elölről.')
            return redirect(reverse('admin:auth_user_import_email_list_step1'))

        try:
            osztaly = Osztaly.objects.get(pk=osztaly_id)
        except Osztaly.DoesNotExist:
            messages.error(request, 'A kiválasztott osztály nem található.')
            return redirect(reverse('admin:auth_user_import_email_list_step1'))

        if request.method == 'POST':
            created_count = 0
            updated_count = 0
            passwords = []
            for row in rows:
                email = row['email']
                last_name = row['last_name']
                first_name = row['first_name']

                # Look up by email first to avoid matching a different user with the same username
                existing_user = User.objects.filter(email=email).first()
                if existing_user:
                    user = existing_user
                    created = False
                else:
                    # Derive a unique username from the local-part of the email
                    base_username = email.split('@')[0]
                    username = base_username
                    suffix = 1
                    while User.objects.filter(username=username).exists():
                        username = f'{base_username}_{suffix}'
                        suffix += 1
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        last_name=last_name,
                        first_name=first_name,
                    )
                    created = True
                if created:
                    raw_password = generate_strong_password()
                    user.set_password(raw_password)
                    user.save()
                    passwords.append({'email': email, 'name': f'{last_name} {first_name}', 'password': raw_password})
                    created_count += 1
                else:
                    # Update name if changed
                    changed = False
                    if last_name and user.last_name != last_name:
                        user.last_name = last_name
                        changed = True
                    if first_name and user.first_name != first_name:
                        user.first_name = first_name
                        changed = True
                    if changed:
                        user.save()
                    updated_count += 1

                # Ensure profile exists
                Profile.objects.get_or_create(user=user)
                # Add to class
                osztaly.tanulok.add(user)

            # Clean up session
            request.session.pop('import_emails', None)
            request.session.pop('import_osztaly_id', None)
            request.session.pop('import_rows', None)

            messages.success(
                request,
                f'{created_count} új felhasználó létrehozva, {updated_count} meglévő frissítve. '
                f'Mind hozzáadva: {osztaly}.',
            )

            context = {
                **self.admin_site.each_context(request),
                'title': 'Import sikeres',
                'passwords': passwords,
                'osztaly': osztaly,
                'created_count': created_count,
                'updated_count': updated_count,
                'opts': self.model._meta,
                'step': 'done',
            }
            return TemplateResponse(request, 'admin/import_email_list_done.html', context)

        # GET – show confirmation table
        existing = {u.email for u in User.objects.filter(email__in=[r['email'] for r in rows])}
        annotated_rows = [dict(r, exists=r['email'] in existing) for r in rows]

        context = {
            **self.admin_site.each_context(request),
            'title': 'Osztály importálása e-mail lista alapján – Megerősítés',
            'rows': annotated_rows,
            'osztaly': osztaly,
            'opts': self.model._meta,
            'step': 3,
        }
        return TemplateResponse(request, 'admin/import_email_list_confirm.html', context)

    # ------------------------------------------------------------------
    # Existing action
    # ------------------------------------------------------------------

    @admin.action(description='Keresztnév és vezetéknév felcserélése')
    def flip_first_last_name(self, request, queryset):
        """Flip first_name and last_name for selected users"""
        updated_count = 0
        for user in queryset:
            user.first_name, user.last_name = user.last_name, user.first_name
            user.save()
            updated_count += 1
        self.message_user(request, f'{updated_count} felhasználó neve felcserélve.')


# Unregister the default User admin and register the custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# Profile Admin
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'get_osztaly', 'is_studios', 'archived', 'login_count']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    list_filter = ['is_studios', 'archived']
    raw_id_fields = ['user']
    actions = [mark_archived, mark_unarchived]
    
    fieldsets = (
        ('Alapadatok', {
            'fields': ('user', 'login_count')
        }),
        ('Stúdiós & Speciális', {
            'fields': ('is_studios',)
        }),
        ('Archiválás', {
            'fields': ('archived', 'archive_date', 'academic_year'),
            'classes': ('collapse',)
        }),
        ('Frontend konfiguráció', {
            'fields': ('frontendConfig',),
            'classes': ('collapse',)
        }),
    )
    
    def get_osztaly(self, obj):
        osztaly = obj.osztalyom()
        return str(osztaly) if osztaly else '-'
    get_osztaly.short_description = 'Osztály'


# Osztaly Admin
@admin.register(Osztaly)
class OsztalyAdmin(admin.ModelAdmin):
    list_display = ['id', '__str__', 'tagozat', 'kezdes_eve', 'get_tanulok_count', 'get_osztalyfonokok_count', 'archived']
    list_filter = ['tagozat', 'kezdes_eve', 'archived']
    search_fields = ['tagozat']
    filter_horizontal = ['tanulok', 'osztalyfonokok', 'nem_fogadott_igazolas_tipusok']
    actions = [mark_archived, mark_unarchived]
    
    fieldsets = (
        ('Alapadatok', {
            'fields': ('tagozat', 'kezdes_eve')
        }),
        ('Tanulók és Tanárok', {
            'fields': ('tanulok', 'osztalyfonokok')
        }),
        ('Igazolás beállítások', {
            'fields': ('nem_fogadott_igazolas_tipusok',)
        }),
        ('Órarend konfiguráció', {
            'fields': ('enabled_periods',),
            'description': 'JSON lista az engedélyezett tanórai időszakokról (pl. [1,2,3,4,5,6,7])'
        }),
        ('Archiválás', {
            'fields': ('archived', 'archive_date', 'academic_year'),
            'classes': ('collapse',)
        }),
    )
    
    def get_tanulok_count(self, obj):
        return obj.tanulok.count()
    get_tanulok_count.short_description = 'Tanulók száma'
    
    def get_osztalyfonokok_count(self, obj):
        return obj.osztalyfonokok.count()
    get_osztalyfonokok_count.short_description = 'Osztályfőnökök száma'


# Mulasztas Admin
@admin.register(Mulasztas)
class MulasztasAdmin(admin.ModelAdmin):
    list_display = ['id', 'datum', 'ora', 'tantargy', 'tipus', 'igazolt', 'igazolas_tipusa', 'archived', 'academic_year', 'rogzites_datuma']
    list_filter = ['tipus', 'igazolt', 'archived', 'datum', 'rogzites_datuma', 'tantargy']
    search_fields = ['tantargy', 'tema', 'igazolas_tipusa']
    date_hierarchy = 'datum'
    ordering = ['-datum', 'ora']
    actions = [mark_archived, mark_unarchived]


# IgazolasTipus Admin
@admin.register(IgazolasTipus)
class IgazolasTipusAdmin(admin.ModelAdmin):
    list_display = ['id', 'nev', 'beleszamit', 'iskolaerdeku', 'supports_group_absence', 'requires_studios']
    list_filter = ['beleszamit', 'iskolaerdeku', 'supports_group_absence', 'requires_studios']
    search_fields = ['nev', 'leiras']
    
    fieldsets = (
        ('Alapadatok', {
            'fields': ('nev', 'leiras')
        }),
        ('Beállítások', {
            'fields': ('beleszamit', 'iskolaerdeku')
        }),
        ('Csoportos & Speciális', {
            'fields': ('supports_group_absence', 'requires_studios'),
            'description': 'Csoportos hiányzás támogatás és stúdiós követelmények'
        }),
    )


# Igazolas Admin
@admin.register(Igazolas)
class IgazolasAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_student', 'get_osztaly', 'eleje', 'vege', 'reszletes_idopontok','tipus', 'allapot', 'get_megjegyzes_diak', 'diak', 'ftv', 'korrigalt', 'is_group_leader', 'archived', 'rogzites_datuma', 'undoed']
    list_filter = ['allapot', 'diak', 'ftv', 'korrigalt', 'kretaban_rogzitettem', 'tipus', 'is_group_leader', 'archived', 'rogzites_datuma']
    search_fields = ['profile__user__username', 'profile__user__first_name', 'profile__user__last_name', 'megjegyzes_diak', 'megjegyzes_tanar', 'group_id']
    date_hierarchy = 'rogzites_datuma'
    raw_id_fields = ['profile', 'created_by_group_leader']
    filter_horizontal = ['mulasztasok']
    readonly_fields = ['rogzites_datuma', 'group_id', 'image_preview']
    ordering = ['-rogzites_datuma']
    actions = [mark_archived, mark_unarchived]
    
    fieldsets = (
        ('Alapadatok', {
            'fields': ('profile', 'eleje', 'vege', 'reszletes_idopontok', 'tipus')
        }),
        ('Mulasztások', {
            'fields': ('mulasztasok',)
        }),
        ('Diák adatok', {
            'fields': ('megjegyzes_diak', 'diak_extra_ido_elotte', 'diak_extra_ido_utana')
        }),
        ('Csatolt kép', {
            'fields': ('image', 'image_preview', 'imgDriveURL'),
            'description': 'A kép megtekintése csak az igazolás beadójának és osztályfőnökének engedélyezett. '
                           'Az "imgDriveURL" mező a régi Google Drive alapú tároláshoz tartozik.'
        }),
        ('Forrás és típus', {
            'fields': ('diak', 'ftv', 'korrigalt', 'bkk_verification')
        }),
        ('Csoportos igazolás', {
            'fields': ('group_id', 'is_group_leader', 'group_member_count', 'created_by_group_leader'),
            'classes': ('collapse',)
        }),
        ('Tanári kezelés', {
            'fields': ('allapot', 'megjegyzes_tanar', 'kretaban_rogzitettem')
        }),
        ('Archiválás', {
            'fields': ('archived', 'academic_year'),
            'classes': ('collapse',)
        }),
        ('Egyéb', {
            'fields': ('rogzites_datuma', 'undoed'),
        }),
    )
    
    def get_student(self, obj):
        return obj.profile.user.get_full_name() or obj.profile.user.username
    get_student.short_description = 'Diák'
    get_student.admin_order_field = 'profile__user__last_name'
    
    def get_osztaly(self, obj):
        osztaly = obj.profile.osztalyom()
        return str(osztaly) if osztaly else '-'
    get_osztaly.short_description = 'Osztály'
    
    def get_megjegyzes_diak(self, obj):
        if obj.megjegyzes_diak:
            # Truncate to 50 chars for table display
            return obj.megjegyzes_diak[:50] + '...' if len(obj.megjegyzes_diak) > 50 else obj.megjegyzes_diak
        return '-'
    get_megjegyzes_diak.short_description = 'Indoklás'

    def image_preview(self, obj):
        """
        Show a permission-aware preview of the attached image.
        Superusers who are not the submitter student or an osztályfőnök of the student's
        class see an informational message instead of the image.
        """
        if not obj.image:
            return '—'
        # Check whether the current admin user is permitted to view the image.
        # `self.current_request` is set in `change_view` / `changeform_view`.
        admin_user = getattr(self, '_current_request', None)
        if admin_user is None:
            return format_html('<span>⚠️ Kép kezelése elérhető, de előnézet nem jeleníthető meg.</span>')

        user = admin_user.user
        # Is this admin the student who submitted?
        if obj.profile.user == user:
            permitted = True
        else:
            osztaly = obj.profile.osztalyom()
            permitted = bool(osztaly and user in osztaly.osztalyfonokok.all())

        if not permitted:
            return format_html(
                '<span style="color:#c0392b;">⛔ Nincs jogosultságod a kép megtekintéséhez '
                '(csak a diák és az osztályfőnök láthatja).</span>'
            )
        # Build a link to the protected API endpoint
        url = f'/api/igazolas/{obj.pk}/image'
        return format_html('<a href="{}" target="_blank">🖼 Kép megtekintése (védett link)</a>', url)

    image_preview.short_description = 'Kép előnézet'

    def changeform_view(self, request, *args, **kwargs):
        self._current_request = request
        return super().changeform_view(request, *args, **kwargs)


# ChangeNote Admin
class ChangeNoteImageInline(admin.TabularInline):
    model = ChangeNoteImage
    extra = 0
    readonly_fields = ['uploaded_by', 'uploaded_at']


@admin.register(ChangeNote)
class ChangeNoteAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'is_currently_published', 'show_to_students', 'show_to_teachers', 'published_at', 'created_by', 'updated_at']
    list_filter = ['show_to_students', 'show_to_teachers', 'published_at']
    search_fields = ['title', 'content']
    filter_horizontal = ['target_classes']
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    inlines = [ChangeNoteImageInline]

    fieldsets = (
        ('Tartalom', {
            'fields': ('title', 'content')
        }),
        ('Célközönség', {
            'fields': ('show_to_students', 'show_to_teachers', 'target_classes')
        }),
        ('Közzététel', {
            'fields': ('published_at',)
        }),
        ('Metaadatok', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def is_currently_published(self, obj):
        return obj.is_published()
    is_currently_published.boolean = True
    is_currently_published.short_description = 'Közzétett'

    def save_model(self, request, obj, form, change):
        if not change or not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# SystemMessage Admin
@admin.register(SystemMessage)
class SystemMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'severity', 'messageType', 'showFrom', 'showTo', 'is_currently_active', 'created_at']
    list_filter = ['severity', 'messageType', 'showFrom', 'showTo', 'created_at']
    search_fields = ['title', 'message']
    date_hierarchy = 'showFrom'
    ordering = ['-showFrom']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Üzenet tartalma', {
            'fields': ('title', 'message', 'severity', 'messageType')
        }),
        ('Megjelenítés időzítése', {
            'fields': ('showFrom', 'showTo')
        }),
        ('Metaadatok', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def is_currently_active(self, obj):
        return obj.is_active()
    is_currently_active.boolean = True
    is_currently_active.short_description = 'Aktív'


# TanitasiSzunet Admin
@admin.register(TanitasiSzunet)
class TanitasiSzunetAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_display_name', 'type', 'from_date', 'to_date', 'get_duration_days']
    list_filter = ['type', 'from_date', 'to_date']
    search_fields = ['name', 'description', 'type']
    date_hierarchy = 'from_date'
    ordering = ['from_date']
    
    fieldsets = (
        ('Alapadatok', {
            'fields': ('type', 'name', 'from_date', 'to_date')
        }),
        ('További információk', {
            'fields': ('description',)
        }),
    )
    
    def get_display_name(self, obj):
        return obj.name if obj.name else obj.get_type_display()
    get_display_name.short_description = 'Név'
    
    def get_duration_days(self, obj):
        duration = (obj.to_date - obj.from_date).days + 1
        return f"{duration} nap"
    get_duration_days.short_description = 'Időtartam'


# Override Admin
@admin.register(Override)
class OverrideAdmin(admin.ModelAdmin):
    list_display = ['id', 'date', 'is_required', 'get_scope', 'get_reason_short']
    list_filter = ['is_required', 'date', 'class_id']
    search_fields = ['reason', 'class_id__tagozat']
    date_hierarchy = 'date'
    ordering = ['date']
    raw_id_fields = ['class_id']
    
    fieldsets = (
        ('Kivétel részletei', {
            'fields': ('date', 'is_required', 'class_id')
        }),
        ('Indoklás', {
            'fields': ('reason',)
        }),
    )
    
    def get_scope(self, obj):
        return str(obj.class_id) if obj.class_id else 'Minden osztály'
    get_scope.short_description = 'Hatókör'
    
    def get_reason_short(self, obj):
        if obj.reason:
            return obj.reason[:50] + '...' if len(obj.reason) > 50 else obj.reason
        return '-'
    get_reason_short.short_description = 'Indoklás'


# APIMetrics Admin
@admin.register(APIMetrics)
class APIMetricsAdmin(admin.ModelAdmin):
    list_display = ['id', 'endpoint_path', 'http_method', 'request_count', 'avg_response_ms', 'error_count', 'recorded_at']
    list_filter = ['http_method', 'recorded_at']
    search_fields = ['endpoint_path']
    date_hierarchy = 'recorded_at'
    ordering = ['-recorded_at']
    readonly_fields = ['recorded_at']
    
    fieldsets = (
        ('Endpoint Information', {
            'fields': ('endpoint_path', 'http_method', 'recorded_at')
        }),
        ('Performance Metrics', {
            'fields': ('avg_response_ms', 'p95_response_ms', 'request_count', 'error_count')
        }),
        ('Detailed Data', {
            'fields': ('detailed_metrics',),
            'classes': ('collapse',)
        }),
    )