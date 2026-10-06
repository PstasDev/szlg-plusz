from django.db import models
from django.contrib.auth.models import User, Group
from django.utils import timezone
import pyotp
import secrets
from datetime import timedelta, datetime

# User modellek

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    frontendConfig = models.JSONField(default=dict, blank=True)  # Felhasználói frontend beállítások tárolása JSON formátumban, akármit tárolhat benne a frontend, mivel nincs backend logikához kötve
    login_count = models.IntegerField(default=0)  # Track total number of successful logins
    
    # Feature #25: Stúdiós Support
    is_studios = models.BooleanField(default=False, verbose_name="Stúdiós", help_text="A diák stúdiós programban vesz részt")
    
    # Feature #14: Academic Year Archival
    archived = models.BooleanField(default=False, verbose_name="Archivált", help_text="A profil archivált státuszban van")
    archive_date = models.DateTimeField(null=True, blank=True, verbose_name="Archiválás dátuma")
    academic_year = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tanév", help_text="Pl. 2024/2025")

    def osztalyom(self):
        return Osztaly.objects.filter(tanulok=self.user).first() or Osztaly.objects.filter(osztalyfonokok=self.user, archived=False).first()

    def osztalyaim(self):
        """
        Return all currently active (non-archived) classes where this user is
        an osztályfőnök. Supports osztályfőnök assigned to multiple classes.
        """
        return Osztaly.objects.filter(osztalyfonokok=self.user, archived=False)

    def osztalyom_igazolasai(self):
        """
        Return Igazolás records for all active classes where this user is an
        osztályfőnök. Combines students across every assigned class so a
        teacher of multiple classes sees all of their students' records.
        Archived and student-withdrawn (undoed) records are excluded - the
        osztályfőnök must never see records the student withdrew.
        """
        osztalyok = self.osztalyaim()
        if not osztalyok.exists():
            return Igazolas.objects.none()
        return Igazolas.objects.filter(
            profile__user__osztaly__in=osztalyok,
            archived=False,
            undoed=False
        ).distinct()

    def __str__(self):
        return self.user.username
    
    class Meta:
        verbose_name = 'Profil'
        verbose_name_plural = 'Profilok'


class PermissionChangeLog(models.Model):
    """
    Model to track permission changes (superuser promote/demote actions).
    Provides audit trail for administrative permission changes.
    """
    ACTION_PROMOTED = 'promoted'
    ACTION_DEMOTED = 'demoted'
    
    ACTION_CHOICES = [
        (ACTION_PROMOTED, 'Promoted to Superuser'),
        (ACTION_DEMOTED, 'Demoted from Superuser'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permission_changes')
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='permission_changes_made')
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    previous_value = models.BooleanField()
    new_value = models.BooleanField()
    
    def __str__(self):
        return f"{self.user.username} - {self.action} by {self.changed_by.username if self.changed_by else 'System'} at {self.changed_at}"
    
    class Meta:
        verbose_name = 'Permission Change Log'
        verbose_name_plural = 'Permission Change Logs'
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['user', '-changed_at']),
            models.Index(fields=['changed_by', '-changed_at']),
        ]

class Osztaly(models.Model):
    tagozat = models.CharField(max_length=1) # PL. A, B, C
    kezdes_eve = models.IntegerField() # PL. 22, 23, 24

    tanulok = models.ManyToManyField(User, blank=True)
    osztalyfonokok = models.ManyToManyField(User, related_name='osztalyfonokok', blank=True)
    nem_fogadott_igazolas_tipusok = models.ManyToManyField('IgazolasTipus', blank=True, related_name='nem_fogado_osztalyok')

    # Feature #27: Class-Specific Period Configuration
    enabled_periods = models.JSONField(default=list, blank=True, verbose_name="Engedélyezett órák", help_text="Lista az engedélyezett tanórai időszakokról (pl. [1,2,3,4,5,6,7])")
    
    # Feature #14: Academic Year Archival
    archived = models.BooleanField(default=False, verbose_name="Archivált", help_text="Az osztály archivált státuszban van")
    archive_date = models.DateTimeField(null=True, blank=True, verbose_name="Archiválás dátuma")
    academic_year = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tanév", help_text="Pl. 2024/2025")

    def osztaly_igazolasai(self):
        return Igazolas.objects.filter(profile__user__in=self.tanulok.all())
    
    @property
    def nev(self):
        """Property to provide the class name for schema serialization"""
        return f"{self.kezdes_eve}{self.tagozat}" # 23A, 22B

    def __str__(self):
        return self.nev
    
    class Meta:
        verbose_name = 'Osztály'
        verbose_name_plural = 'Osztályok'

# Hiányzás modellek

# Mulasztás - Krétából importált hiányzás
# Mulasztás - Krétából importált hiányzás VAGY diák által feltöltött (EXPERIMENTAL)
class Mulasztas(models.Model):
    datum = models.DateField()
    ora = models.IntegerField() # 0-8
    tantargy = models.CharField(max_length=100)
    tema = models.CharField(max_length=200)
    
    tipusok = [
        ('KE', 'Késés'),
        ('HI', 'Hiányzás'),
    ]

    tipus = models.CharField(max_length=50) # Hiányzás, késés
    igazolt = models.BooleanField(default=False)
    igazolas_tipusa = models.CharField(max_length=100, null=True, blank=True) # Pl. orvosi igazolás
    rogzites_datuma = models.DateField() # Mikor lett a KRÉTÁBA rögzítve a mulasztás?
    
    # EXPERIMENTAL: Student-uploaded data from eKréta
    uploaded_by_student = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, 
                                           related_name='uploaded_mulasztasok',
                                           verbose_name="Feltöltő diák",
                                           help_text="Ha diák töltötte fel eKrétából (EXPERIMENTAL)")
    tanorai_celu_mulasztas = models.BooleanField(default=False, verbose_name="Tanórai célú mulasztás")
    mulasztas_ok = models.CharField(max_length=300, blank=True, null=True, verbose_name="Mulasztás oka")
    mulasztas_statusz = models.CharField(max_length=200, blank=True, null=True, verbose_name="Mulasztás státusz")
    uploaded_at = models.DateTimeField(null=True, blank=True, verbose_name="Feltöltve (eKréta)")
    
    # Feature #24: Mulasztas Import & Comparison
    matched_igazolas = models.ForeignKey('Igazolas', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='matched_mulasztasok',
                                        verbose_name="Párosított igazolás",
                                        help_text="Az igazolás ami fedezi ezt a mulasztást")

    def __str__(self):
        student = self.uploaded_by_student.username if self.uploaded_by_student else "System"
        return f"{student} - {self.datum} - {self.tantargy}"
    
    class Meta:
        verbose_name = 'Mulasztás'
        verbose_name_plural = 'Mulasztások'
        indexes = [
            models.Index(fields=['uploaded_by_student', '-datum']),
        ]

    # Feature #14: Academic Year Archival
    archived = models.BooleanField(default=False, verbose_name="Archivált", help_text="A mulasztás archivált státuszban van")
    academic_year = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tanév")

class IgazolasTipus(models.Model):
    nev = models.CharField(max_length=100) # Pl. orvosi igazolás
    # beleszámít-e a bizonyítványba?
    leiras = models.TextField(null=True, blank=True, max_length=500)
    beleszamit = models.BooleanField(default=True)

    # Iskolaérdekű-e? - Ha a tanár el akarná utasítani az igazolást, de iskolaérdekű, akkor popup, hogy biztosan elutasítja-e
    iskolaerdeku = models.BooleanField(default=False)
    
    # Feature #25: Group Absences Support
    supports_group_absence = models.BooleanField(default=False, verbose_name="Csoportos hiányzást támogat", 
                                                 help_text="Lehetővé teszi több diák párhuzamos igazolását ugyanarra az eseményre")
    requires_studios = models.BooleanField(default=False, verbose_name="Stúdiós szükséges", 
                                          help_text="Csak stúdiós diákok használhatják ezt az igazolás típust")
    
    # Categorization and sub-forms
    category = models.CharField(
        max_length=50,
        choices=[
            ('egeszsegugy', 'Egészségügyi'),
            ('verseny', 'Verseny'),
            ('kulturalis', 'Kulturális/Művészeti'),
            ('kozlekedes', 'Közlekedés'),
            ('tanulmanyi', 'Tanulmányi'),
            ('csaladi', 'Családi'),
            ('egyeb', 'Egyéb'),
        ],
        default='egyeb',
        verbose_name='Kategória'
    )
    category_emoji = models.CharField(max_length=10, null=True, blank=True, verbose_name='Kategória emoji')
    has_sub_form = models.BooleanField(default=False, verbose_name='Van alkérdőív',
                                       help_text='A típus további adatokat kér (pl. verseny részletek)')
    sub_form_schema = models.JSONField(null=True, blank=True, verbose_name='Alkérdőív séma',
                                       help_text='JSON séma a további mezőkhöz')
    display_order = models.IntegerField(default=0, verbose_name='Megjelenítési sorrend',
                                       help_text='Kategórián belüli sorrend (alacsonyabb = előrébb)')

    def __str__(self):
        return self.nev
    
    class Meta:
        verbose_name = 'Igazolás Típus'
        verbose_name_plural = 'Igazolás Típusok'
        ordering = ['category', 'display_order', 'nev']

# Igazolás - Új Igazolás form response
class Igazolas(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    mulasztasok = models.ManyToManyField(Mulasztas, blank=True)

    eleje = models.DateTimeField()
    vege = models.DateTimeField()

    tipus = models.ForeignKey(IgazolasTipus, on_delete=models.CASCADE)

    rogzites_datuma = models.DateField(auto_now_add=True)

    megjegyzes_diak = models.TextField(max_length=500, null=True, blank=True)

    # Forrás
    diak = models.BooleanField(default=True)  # True ha Form repsonse
    ftv = models.BooleanField(default=False)  # True ha FTV-ből lett importálva
    korrigalt = models.BooleanField(default=False)  # FTVből importált igazolás, diák által korrigált változata
    ftv_hianyzas_id = models.IntegerField(null=True, blank=True, unique=True)  # FTV hiányzás ID for sync tracking

    # Többnapos FTV forgatások támogatása: egy forgatáshoz (ftv_forgatas_id) több
    # napi Absence/Igazolas rekord is tartozhat, mindegyik saját ftv_hianyzas_id-vel.
    ftv_forgatas_id = models.IntegerField(null=True, blank=True)  # FTV forgatás ID (nem egyedi - több napi rekord is hivatkozhat rá)
    ftv_tobbnapos = models.BooleanField(default=False)  # FTV is_multi_day - a forgatás több naptári napon átnyúlik
    ftv_korrigalhato = models.BooleanField(default=True)  # FTV can_be_corrected - False többnapos hiányzásnál, a diák nem korrigálhatja
    ftv_forgatas_veg_datum = models.DateField(null=True, blank=True)  # forgatas_details.end_date - a forgatás befejezésének dátuma

    # Korrekció
    diak_extra_ido_elotte = models.IntegerField(null=True, blank=True)  
    diak_extra_ido_utana = models.IntegerField(null=True, blank=True)


    # URL amire feltölti a diák a fényképet, nem Image repsonse -> Google Drive
    imgDriveURL = models.URLField(max_length=300, null=True, blank=True)

    # Compressed image stored on this server (replaces / complements imgDriveURL)
    image = models.ImageField(upload_to='igazolas_images/', null=True, blank=True,
                              verbose_name='Kép',
                              help_text='Igazoláshoz csatolt, tömörített kép')

    # BKK Verification - JSON field for BKK related data
    bkk_verification = models.JSONField(null=True, blank=True)

    # Detailed intervals: list of {eleje, vege} pairs for non-contiguous absences.
    # Null means the student was absent for the full eleje–vege span.
    # Example: [{"eleje": "2024-01-15T08:00:00Z", "vege": "2024-01-15T09:00:00Z"}, ...]
    reszletes_idopontok = models.JSONField(null=True, blank=True, verbose_name='Részletes időpontok',
                                           help_text='Nem összefüggő hiányzás esetén az egyes részintervallumok listája')
    
    # Sub-form data for competition types, etc.
    sub_form_data = models.JSONField(null=True, blank=True, verbose_name='Alkérdőív adatok',
                                     help_text='Típus-specifikus további adatok JSON formátumban')
    
    # Feature #25: Group Absences Support
    group_id = models.UUIDField(null=True, blank=True, verbose_name="Csoport azonosító", 
                                help_text="UUID amely összeköti a csoportos igazolásokat")
    is_group_leader = models.BooleanField(default=False, verbose_name="Csoport vezető", 
                                         help_text="Az igazolást létrehozó diák")
    group_member_count = models.IntegerField(default=1, verbose_name="Csoport létszám")
    created_by_group_leader = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                               related_name='created_group_igazolasok',
                                               verbose_name="Létrehozta (csoport vezető)",
                                               help_text="A csoportos igazolást létrehozó felhasználó")
    
    # Feature #14: Academic Year Archival
    archived = models.BooleanField(default=False, verbose_name="Archivált", help_text="Az igazolás archivált státuszban van")
    academic_year = models.CharField(max_length=20, null=True, blank=True, verbose_name="Tanév", help_text="Pl. 2024/2025")

    # Visszavonás: a diák visszavonja az igazolást (nem törlődik, csak nem látszik)
    undoed = models.BooleanField(default=False, verbose_name="Visszavont", help_text="A diák visszavonta az igazolást")

    # Tanár tölti ki

    allapotok = [
        ('Függőben', 'Függőben'),
        ('Elfogadva', 'Elfogadva'),
        ('Elutasítva', 'Elutasítva'),
        ('Hiánypótlásra visszaküldve', 'Hiánypótlásra visszaküldve'),
    ]

    allapot = models.CharField(max_length=50, default='Függőben', choices=allapotok)

    megjegyzes_tanar = models.TextField(max_length=500, null=True, blank=True) # diák nem láthatja

    kretaban_rogzitettem = models.BooleanField(default=False)

    def __str__(self):
        return f"Igazolás #{self.id} - {self.profile.user.username}"
    
    class Meta:
        verbose_name = 'Igazolás'
        verbose_name_plural = 'Igazolások'


# Password Reset Models

class PasswordResetOTP(models.Model):
    """
    Model to store OTP codes for password reset functionality.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    secret_key = models.CharField(max_length=32)  # TOTP secret key
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)  # Track failed attempts
    
    def generate_otp(self):
        """Generate a new 6-digit OTP code"""
        totp = pyotp.TOTP(self.secret_key, interval=300)  # 5 minutes validity
        return totp.now()
    
    def verify_otp(self, otp_code):
        """Verify the OTP code"""
        totp = pyotp.TOTP(self.secret_key, interval=300)
        return totp.verify(otp_code, valid_window=1)  # Allow 1 window tolerance
    
    def is_expired(self):
        """Check if OTP has expired (15 minutes from creation)"""
        return timezone.now() > self.created_at + timedelta(minutes=15)
    
    def can_attempt(self):
        """Check if user can still attempt OTP verification (max 5 attempts)"""
        return self.attempts < 5
    
    @classmethod
    def create_for_user(cls, user):
        """Create a new OTP for user, invalidating previous ones"""
        # Invalidate existing OTPs
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        
        # Create new OTP
        secret_key = pyotp.random_base32()
        return cls.objects.create(user=user, secret_key=secret_key)
    
    def __str__(self):
        return f"OTP for {self.user.username} - {self.created_at}"
    
    class Meta:
        verbose_name = 'Password Reset OTP'
        verbose_name_plural = 'Password Reset OTPs'
        ordering = ['-created_at']


class ForgotPasswordToken(models.Model):
    """
    Model to store temporary tokens for password reset after OTP verification.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True)  # Secure random token
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    
    def is_expired(self):
        """Check if token has expired (10 minutes from creation)"""
        return timezone.now() > self.created_at + timedelta(minutes=10)
    
    @classmethod
    def create_for_user(cls, user):
        """Create a new token for user, invalidating previous ones"""
        # Invalidate existing tokens
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        
        # Create new token
        token = secrets.token_urlsafe(48)
        return cls.objects.create(user=user, token=token)
    
    def __str__(self):
        return f"Reset Token for {self.user.username} - {self.created_at}"
    
    class Meta:
        verbose_name = 'Forgot Password Token'
        verbose_name_plural = 'Forgot Password Tokens'
        ordering = ['-created_at']


class FTVSyncMetadata(models.Model):
    """
    Model to store FTV sync metadata for tracking sync status.
    Each sync type (base, user_{id}, class_{id}) has its own record.
    """
    sync_type = models.CharField(max_length=100, unique=True)  # 'base', 'user_{id}', 'class_{id}'
    last_sync_time = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, default='never')  # 'success', 'failed', 'never'
    last_sync_stats = models.JSONField(null=True, blank=True)  # Store sync statistics
    
    @classmethod
    def get_or_create_metadata(cls, sync_type: str):
        """Get or create metadata for a sync type"""
        obj, created = cls.objects.get_or_create(sync_type=sync_type)
        return obj
    
    @classmethod
    def update_sync(cls, sync_type: str, status: str, stats: dict = None):
        """Update sync metadata"""
        obj = cls.get_or_create_metadata(sync_type)
        obj.last_sync_time = timezone.now()
        obj.last_sync_status = status
        if stats:
            obj.last_sync_stats = stats
        obj.save()
        return obj
    
    @classmethod
    def get_metadata(cls, sync_type: str) -> dict:
        """Get metadata as dictionary"""
        obj = cls.get_or_create_metadata(sync_type)
        result = {
            'last_sync_time': obj.last_sync_time.isoformat() if obj.last_sync_time else None,
            'last_sync_status': obj.last_sync_status,
            'last_sync_stats': obj.last_sync_stats
        }
        
        # Calculate age
        if obj.last_sync_time:
            age_seconds = (timezone.now() - obj.last_sync_time).total_seconds()
            result['sync_age_seconds'] = int(age_seconds)
            result['sync_age_minutes'] = round(age_seconds / 60, 1)
        else:
            result['sync_age_seconds'] = None
            result['sync_age_minutes'] = None
        
        return result
    
    def __str__(self):
        return f"FTV Sync Metadata [{self.sync_type}] - Last sync: {self.last_sync_time or 'Never'}"
    
    class Meta:
        verbose_name = 'FTV Sync Metadata'
        verbose_name_plural = 'FTV Sync Metadata'


class SystemMessage(models.Model):
    """
    Model to store system messages for displaying announcements, warnings, and errors to users.
    """
    # Severity choices
    SEVERITY_INFO = 'info'
    SEVERITY_WARNING = 'warning'
    SEVERITY_ERROR = 'error'
    
    SEVERITY_CHOICES = [
        (SEVERITY_INFO, 'Információ'),
        (SEVERITY_WARNING, 'Figyelmeztetés'),
        (SEVERITY_ERROR, 'Hiba'),
    ]
    
    # Message type choices
    MESSAGE_TYPE_USER = 'user'
    MESSAGE_TYPE_DEVELOPER = 'developer'
    MESSAGE_TYPE_OPERATOR = 'operator'
    MESSAGE_TYPE_SUPPORT = 'support'
    
    MESSAGE_TYPE_CHOICES = [
        (MESSAGE_TYPE_USER, 'Felhasználó'),
        (MESSAGE_TYPE_DEVELOPER, 'Fejlesztő'),
        (MESSAGE_TYPE_OPERATOR, 'Operátor'),
        (MESSAGE_TYPE_SUPPORT, 'Támogatás'),
    ]
    
    title = models.CharField(max_length=200, blank=False, null=False, verbose_name='Cím', 
                            help_text='A rendszerüzenet címe (maximum 200 karakter)')
    message = models.TextField(max_length=2000, blank=False, null=False, verbose_name='Üzenet', 
                              help_text='A rendszerüzenet tartalma (maximum 2000 karakter)')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_INFO, 
                               verbose_name='Súlyosság', 
                               help_text='Az üzenet súlyossága (info/warning/error)')
    messageType = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default=MESSAGE_TYPE_USER,
                                  verbose_name='Üzenet típusa',
                                  help_text='Az üzenet célközönsége (user/developer/operator/support)')
    showFrom = models.DateTimeField(blank=False, null=False, verbose_name='Megjelenítés kezdete', 
                                   help_text='Az üzenet megjelenítésének kezdő időpontja')
    showTo = models.DateTimeField(blank=False, null=False, verbose_name='Megjelenítés vége', 
                                 help_text='Az üzenet megjelenítésének záró időpontja')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Létrehozva', 
                                     help_text='A rendszerüzenet létrehozásának időpontja')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Módosítva', 
                                     help_text='A rendszerüzenet utolsó módosításának időpontja')

    def __str__(self):
        return self.title
    
    @classmethod
    def get_active_messages(cls, check_datetime=None):
        """Get all system messages that should be displayed at the given datetime (default: now)"""
        if check_datetime is None:
            check_datetime = datetime.now()
        
        return cls.objects.filter(
            showFrom__lte=check_datetime,
            showTo__gte=check_datetime
        ).order_by('showFrom')
    
    def is_active(self, check_datetime=None):
        """Check if this message should be displayed at the given datetime (default: now)"""
        if check_datetime is None:
            check_datetime = datetime.now()
        
        return self.showFrom <= check_datetime <= self.showTo
    
    class Meta:
        verbose_name = "Rendszerüzenet"
        verbose_name_plural = "Rendszerüzenetek"
        ordering = ['-showFrom']


class ChangeNote(models.Model):
    """
    "Change note" (changelog / announcement) entry shown to users as an
    almost full-screen dismissable popup. Authored in Markdown (images
    supported via standard Markdown image syntax and the dedicated image
    upload endpoint). Dismissal is tracked client-side in the user's
    Profile.frontendConfig, not on the backend.
    """
    title = models.CharField(max_length=200, verbose_name='Cím',
                            help_text='A bejegyzés címe (maximum 200 karakter)')
    content = models.TextField(verbose_name='Tartalom',
                              help_text='Markdown formázott tartalom (képek is beágyazhatók)')

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='created_change_notes', verbose_name='Létrehozta')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Létrehozva')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Módosítva')
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='Közzététel időpontja',
                                       help_text='Ha üres, a bejegyzés vázlat és senkinek sem jelenik meg')

    show_to_students = models.BooleanField(default=True, verbose_name='Diákoknak mutatva')
    show_to_teachers = models.BooleanField(default=True, verbose_name='Tanároknak mutatva')
    target_classes = models.ManyToManyField('Osztaly', blank=True, related_name='change_notes',
                                           verbose_name='Célosztályok',
                                           help_text='Ha üres, minden osztály látja (a fenti kapcsolóknak megfelelően)')

    def __str__(self):
        return self.title

    def is_published(self, check_datetime=None):
        """Check whether this change note is currently published."""
        if self.published_at is None:
            return False
        if check_datetime is None:
            check_datetime = timezone.now()
        return self.published_at <= check_datetime

    def is_visible_to(self, user):
        """Check whether this change note should be shown to the given user."""
        if not self.is_published():
            return False

        teacher_classes = Osztaly.objects.filter(osztalyfonokok=user)
        is_teacher = teacher_classes.exists()

        if is_teacher:
            if not self.show_to_teachers:
                return False
            if self.target_classes.exists():
                return self.target_classes.filter(id__in=teacher_classes.values_list('id', flat=True)).exists()
            return True

        if not self.show_to_students:
            return False
        if self.target_classes.exists():
            profile = getattr(user, 'profile', None)
            student_class = profile.osztalyom() if profile else None
            if not student_class:
                return False
            return self.target_classes.filter(id=student_class.id).exists()
        return True

    class Meta:
        verbose_name = 'Változás bejegyzés'
        verbose_name_plural = 'Változás bejegyzések'
        ordering = ['-published_at', '-created_at']


class ChangeNoteImage(models.Model):
    """
    Image uploaded for use inside a ChangeNote's Markdown content.
    Kept as a standalone model (not required to belong to a note yet) so
    images can be uploaded from the editor before the note itself is saved.
    """
    change_note = models.ForeignKey(ChangeNote, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='images', verbose_name='Változás bejegyzés')
    image = models.ImageField(upload_to='change_note_images/', verbose_name='Kép')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name='Feltöltötte')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='Feltöltve')

    def __str__(self):
        return f'Kép #{self.id}'

    class Meta:
        verbose_name = 'Változás bejegyzés kép'
        verbose_name_plural = 'Változás bejegyzés képek'


class TanitasiSzunet(models.Model):
    """
    Model to store school breaks that apply to all students globally.
    
    Examples: Őszi szünet, Téli szünet, Tavaszi szünet, Nyári szünet, etc.
    """
    # Type choices
    TYPE_OSZI = 'oszi'
    TYPE_TELI = 'teli'
    TYPE_TAVASZI = 'tavaszi'
    TYPE_NYARI = 'nyari'
    TYPE_ERETTSEGI = 'erettsegi'
    TYPE_DIGITALIS = 'digitalis'
    TYPE_EGYEB = 'egyeb'
    
    TYPE_CHOICES = [
        (TYPE_OSZI, 'Őszi szünet'),
        (TYPE_TELI, 'Téli szünet'),
        (TYPE_TAVASZI, 'Tavaszi szünet'),
        (TYPE_NYARI, 'Nyári szünet'),
        (TYPE_ERETTSEGI, 'Érettségi időszak'),
        (TYPE_DIGITALIS, 'Digitális oktatás'),
        (TYPE_EGYEB, 'Egyéb'),
    ]
    
    type = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES, 
        verbose_name='Típus',
        help_text='A tanítási szünet típusa'
    )
    name = models.CharField(
        max_length=200, 
        blank=True, 
        null=True, 
        verbose_name='Név',
        help_text='Egyedi név a szünetnek (opcionális)'
    )
    from_date = models.DateField(
        verbose_name='Kezdő dátum',
        help_text='A tanítási szünet kezdő dátuma'
    )
    to_date = models.DateField(
        verbose_name='Záró dátum',
        help_text='A tanítási szünet záró dátuma'
    )
    description = models.TextField(
        max_length=1000, 
        blank=True, 
        null=True, 
        verbose_name='Leírás',
        help_text='Megjegyzések vagy további információk a szünetről'
    )
    
    def __str__(self):
        display_name = self.name if self.name else self.get_type_display()
        return f"{display_name} ({self.from_date} - {self.to_date})"
    
    class Meta:
        verbose_name = "Tanítási Szünet"
        verbose_name_plural = "Tanítási Szünetek"
        ordering = ['from_date']


class Override(models.Model):
    """
    Model to store exceptions to the default attendance rule.
    
    Default rule: weekday = attendance required, weekend = not required
    This model allows overriding this rule for specific dates.
    
    Examples:
    - Saturday classes (is_required=True)
    - Holiday on a weekday (is_required=False)
    - Class-specific exceptions
    """
    date = models.DateField(
        verbose_name='Dátum',
        help_text='A kivétel dátuma'
    )
    is_required = models.BooleanField(
        verbose_name='Jelenléti kötelezettség',
        help_text='True = jelenlét kötelező, False = jelenlét nem kötelező'
    )
    class_id = models.ForeignKey(
        Osztaly,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name='Osztály',
        help_text='Ha megadva, csak erre az osztályra vonatkozik. Ha üres, minden osztályra vonatkozik.',
        related_name='overrides'
    )
    reason = models.TextField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name='Indoklás',
        help_text='A kivétel indoklása vagy megjegyzések'
    )
    
    def __str__(self):
        scope = f"{self.class_id}" if self.class_id else "Minden osztály"
        requirement = "Kötelező" if self.is_required else "Nem kötelező"
        return f"{self.date} - {scope} - {requirement}"
    
    class Meta:
        verbose_name = "Kivétel (Override)"
        verbose_name_plural = "Kivételek (Overrides)"
        ordering = ['date']


class APIMetrics(models.Model):
    """
    Model to store API performance metrics.
    Tracks endpoint usage, response times, and error rates.
    """
    endpoint_path = models.CharField(max_length=500, verbose_name="Endpoint Path")
    http_method = models.CharField(max_length=10, verbose_name="HTTP Method")
    avg_response_ms = models.FloatField(verbose_name="Average Response Time (ms)")
    request_count = models.IntegerField(default=0, verbose_name="Request Count")
    error_count = models.IntegerField(default=0, verbose_name="Error Count")
    p95_response_ms = models.FloatField(null=True, blank=True, verbose_name="95th Percentile Response Time (ms)")
    recorded_at = models.DateTimeField(auto_now_add=True, verbose_name="Recorded At")
    
    # Store detailed metrics as JSON
    detailed_metrics = models.JSONField(
        default=dict, 
        blank=True,
        verbose_name="Detailed Metrics",
        help_text="Additional metrics data in JSON format"
    )
    
    def __str__(self):
        return f"{self.http_method} {self.endpoint_path} - {self.request_count} requests"
    
    class Meta:
        verbose_name = "API Metrika"
        verbose_name_plural = "API Metrikák"
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['endpoint_path', 'http_method']),
            models.Index(fields=['-recorded_at']),
        ]



class Passkey(models.Model):
    """
    WebAuthn credential (passkey) belonging to a user.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    transports = models.CharField(max_length=200, blank=True, default="")
    name = models.CharField(max_length=80, blank=True, default="Passkey")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.name}"

    class Meta:
        verbose_name = "Jelkulcs"
        verbose_name_plural = "Jelkulcsok"
        ordering = ["-created_at"]
