from ninja import Schema
from datetime import datetime
from datetime import date as DateType
from typing import Optional, List


# User schemas
class UserSchema(Schema):
    id: int
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    
    class Config:
        from_attributes = True


# Authentication schemas
class LoginRequest(Schema):
    username: str
    password: str


class TokenResponse(Schema):
    token: str
    user_id: int
    username: str
    iat: int
    exp: int


class ErrorResponse(Schema):
    error: str
    detail: str


# Profile schemas
class OsztalySimpleSchema(Schema):
    id: int
    tagozat: str
    kezdes_eve: int
    nev: str
    
    class Config:
        from_attributes = True


class ProfileSchema(Schema):
    id: int
    user: UserSchema
    osztalyom: Optional[OsztalySimpleSchema] = None
    osztalyaim: Optional[List[OsztalySimpleSchema]] = None
    
    class Config:
        from_attributes = True


# Osztaly schemas
class OsztalySchema(Schema):
    id: int
    tagozat: str
    kezdes_eve: int
    nev: str
    tanulok: List[UserSchema]
    osztalyfonokok: List[UserSchema]
    nem_fogadott_igazolas_tipusok: Optional[List['IgazolasTipusSchema']] = None
    
    class Config:
        from_attributes = True


# Mulasztas schemas
class MulasztasSchema(Schema):
    id: int
    datum: datetime  # DateField in model, but datetime works for both date and datetime
    ora: int
    tantargy: str
    tema: str
    tipus: str
    igazolt: bool
    igazolas_tipusa: Optional[str] = None
    rogzites_datuma: datetime  # DateField in model
    
    class Config:
        from_attributes = True


# IgazolasTipus schemas
class IgazolasTipusSchema(Schema):
    id: int
    nev: str
    leiras: Optional[str] = None
    beleszamit: bool
    iskolaerdeku: bool
    nem_fogado_osztalyok: Optional[List[OsztalySimpleSchema]] = None
    # Categorization fields
    category: str
    category_emoji: Optional[str] = None
    has_sub_form: bool
    sub_form_schema: Optional[dict] = None
    display_order: int
    supports_group_absence: bool
    requires_studios: bool
    
    class Config:
        from_attributes = True


# Igazolas schemas
class IgazolasSchema(Schema):
    id: int
    profile: ProfileSchema
    mulasztasok: List[MulasztasSchema]
    eleje: datetime
    vege: datetime
    tipus: IgazolasTipusSchema
    megjegyzes: Optional[str] = None
    rogzites_datuma: DateType  # DateField in model (auto_now_add)
    megjegyzes_diak: Optional[str] = None
    diak: bool
    ftv: bool
    korrigalt: bool
    ftv_hianyzas_id: Optional[int] = None
    ftv_forgatas_id: Optional[int] = None
    ftv_tobbnapos: bool = False
    ftv_korrigalhato: bool = True
    ftv_forgatas_veg_datum: Optional[DateType] = None
    diak_extra_ido_elotte: Optional[int] = None
    diak_extra_ido_utana: Optional[int] = None
    imgDriveURL: Optional[str] = None
    image_url: Optional[str] = None
    bkk_verification: Optional[dict] = None
    sub_form_data: Optional[dict] = None  # New field for sub-form data
    reszletes_idopontok: Optional[list] = None  # Detailed intervals for non-contiguous absences
    allapot: str
    megjegyzes_tanar: Optional[str] = None
    kretaban_rogzitettem: bool
    undoed: bool = False
    
    class Config:
        from_attributes = True


class IgazolasEditRequest(Schema):
    eleje: Optional[datetime] = None
    vege: Optional[datetime] = None
    tipus: Optional[int] = None  # IgazolasTipus ID
    megjegyzes_diak: Optional[str] = None
    imgDriveURL: Optional[str] = None
    bkk_verification: Optional[dict] = None
    sub_form_data: Optional[dict] = None
    reszletes_idopontok: Optional[list] = None


class IgazolasUndoResponse(Schema):
    id: int
    undoed: bool
    message: str


class IgazolasCreateRequest(Schema):
    eleje: datetime
    vege: datetime
    tipus: int  # IgazolasTipus ID
    megjegyzes_diak: Optional[str] = None
    diak: Optional[bool] = True
    korrigalt: Optional[bool] = False
    diak_extra_ido_elotte: Optional[int] = None
    diak_extra_ido_utana: Optional[int] = None
    imgDriveURL: Optional[str] = None
    bkk_verification: Optional[dict] = None
    sub_form_data: Optional[dict] = None  # New field for sub-form data
    reszletes_idopontok: Optional[list] = None  # Detailed intervals for non-contiguous absences


# Quick action schemas
class QuickActionRequest(Schema):
    action: str  # 'Elfogadva', 'Elutasítva', 'Függőben' or 'Hiánypótlásra visszaküldve'
    megjegyzes_tanar: Optional[str] = None  # Optional teacher comment, e.g. hiánypótlás reason


class BulkQuickActionRequest(Schema):
    action: str  # 'Elfogadva' or 'Elutasítva'
    ids: List[int]  # List of igazolas IDs


class QuickActionResponse(Schema):
    id: int
    allapot: str
    message: str


class BulkQuickActionResponse(Schema):
    updated_count: int
    failed_ids: List[int]
    message: str


# Teacher comment edit schemas
class TeacherCommentUpdateRequest(Schema):
    megjegyzes_tanar: Optional[str] = None


class TeacherCommentUpdateResponse(Schema):
    id: int
    megjegyzes_tanar: Optional[str] = None
    message: str


# Diakjaim schemas  
class IgazolasSimpleSchema(Schema):
    id: int
    eleje: datetime
    vege: datetime
    tipus: IgazolasTipusSchema
    allapot: str
    rogzites_datuma: DateType
    megjegyzes_diak: Optional[str] = None
    bkk_verification: Optional[dict] = None
    reszletes_idopontok: Optional[list] = None  # Detailed intervals for non-contiguous absences
    undoed: bool = False


class DiakjaSignleSchema(Schema):
    id: int
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    last_action: Optional[datetime] = None
    igazolasok: List[IgazolasSimpleSchema]


class DiakjaCreateRequest(Schema):
    last_name: str
    first_name: str
    email: str


class DiakjaCreateResponse(Schema):
    created_count: int
    failed_users: List[str]
    message: str


# Password Reset / OTP schemas
class ForgotPasswordRequest(Schema):
    username: str


class ForgotPasswordResponse(Schema):
    message: str
    email_sent: bool


class CheckOTPRequest(Schema):
    username: str
    otp_code: str


class CheckOTPResponse(Schema):
    message: str
    reset_token: str
    expires_in_minutes: int


class ChangePasswordOTPRequest(Schema):
    username: str
    reset_token: str
    new_password: str


class ChangePasswordOTPResponse(Schema):
    message: str
    success: bool


# Osztaly Igazolas Tipus Management schemas
class ToggleIgazolasTipusRequest(Schema):
    tipus_id: int
    enabled: bool  # True to enable (allow), False to disable (not accept)
    osztaly_id: Optional[int] = None  # Optional: apply to a single class. If omitted, applies to ALL active classes where the requester is osztályfőnök.


class ToggleIgazolasTipusResponse(Schema):
    message: str
    success: bool
    tipus_id: int
    enabled: bool
    osztaly_ids: Optional[List[int]] = None  # IDs of classes that were updated


# Change Note schemas
class ChangeNoteSchema(Schema):
    id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    is_published: bool
    show_to_students: bool
    show_to_teachers: bool
    target_class_ids: List[int] = []
    target_class_names: List[str] = []
    created_by_username: Optional[str] = None


class ChangeNoteCreateRequest(Schema):
    title: str
    content: str
    published_at: Optional[datetime] = None
    show_to_students: bool = True
    show_to_teachers: bool = True
    target_class_ids: List[int] = []


class ChangeNoteUpdateRequest(Schema):
    title: Optional[str] = None
    content: Optional[str] = None
    published_at: Optional[datetime] = None
    show_to_students: Optional[bool] = None
    show_to_teachers: Optional[bool] = None
    target_class_ids: Optional[List[int]] = None


class ChangeNoteImageUploadResponse(Schema):
    id: int
    url: str


# System Message schemas
class SystemMessageSchema(Schema):
    id: int
    title: str
    message: str
    severity: str
    messageType: str
    showFrom: datetime
    showTo: datetime
    created_at: datetime
    updated_at: datetime
    is_active: bool


# Tanítási Szünet schemas
class TanitasiSzunetSchema(Schema):
    id: int
    type: str
    name: Optional[str] = None
    from_date: DateType
    to_date: DateType
    description: Optional[str] = None


# Override schemas
class OverrideSchema(Schema):
    id: int
    date: DateType
    is_required: bool
    class_id: Optional[int] = None
    class_name: Optional[str] = None  # For convenience in response
    reason: Optional[str] = None


# Tanév Rendje combined schema
class TanevRendjeSchema(Schema):
    tanitasi_szunetek: List[TanitasiSzunetSchema]
    overrides: List[OverrideSchema]


# Create/Update request schemas
class TanitasiSzunetCreateRequest(Schema):
    type: str
    name: Optional[str] = None
    from_date: DateType
    to_date: DateType
    description: Optional[str] = None


class TanitasiSzunetUpdateRequest(Schema):
    type: Optional[str] = None
    name: Optional[str] = None
    from_date: Optional[DateType] = None
    to_date: Optional[DateType] = None
    description: Optional[str] = None


class OverrideCreateRequest(Schema):
    date: DateType
    is_required: bool
    class_id: Optional[int] = None
    reason: Optional[str] = None


class OverrideUpdateRequest(Schema):
    date: Optional[DateType] = None
    is_required: Optional[bool] = None
    class_id: Optional[int] = None
    reason: Optional[str] = None


# Superuser check schema
class SuperuserCheckResponse(Schema):
    is_superuser: bool
    username: str


# ============================================================================
# Admin Phase 1 Schemas
# ============================================================================

# Feature #1: Password Management
class GeneratePasswordResponse(Schema):
    password: Optional[str] = None  # Only returned if send_email=false
    message: str
    email_sent: bool


class ResetPasswordRequest(Schema):
    new_password: str
    send_email: bool = False


class ResetPasswordResponse(Schema):
    message: str
    email_sent: bool


# Feature #3: Teacher Assignment
class TeacherAssignmentRequest(Schema):
    teacher_id: int


class TeacherInfo(Schema):
    id: int
    username: str
    name: str
    is_superuser: bool = False


class ClassInfo(Schema):
    id: int
    name: str


class AssignTeacherResponse(Schema):
    message: str
    teacher: TeacherInfo
    class_info: ClassInfo


class RemoveTeacherResponse(Schema):
    message: str
    removed: bool


class MoveOsztalyfonokRequest(Schema):
    class_id: int


class MoveOsztalyfonokResponse(Schema):
    message: str
    previous_class: Optional[ClassInfo] = None
    new_class: ClassInfo


class TeacherWithAssignmentDate(Schema):
    id: int
    username: str
    name: str
    is_superuser: bool
    assigned_date: Optional[datetime] = None


class GetTeachersResponse(Schema):
    teachers: List[TeacherWithAssignmentDate]


# Feature #6: Permissions Management
class UserPermissionInfo(Schema):
    id: int
    username: str
    is_superuser: bool


class PromoteDemoteResponse(Schema):
    message: str
    user: UserPermissionInfo


class PermissionChangeHistory(Schema):
    changed_by: str
    changed_at: datetime
    action: str  # 'promoted' or 'demoted'
    previous_value: bool
    new_value: bool


class UserPermissionsResponse(Schema):
    user_id: int
    username: str
    is_superuser: bool
    is_staff: bool
    permissions: List[str] = []
    change_history: List[PermissionChangeHistory]


# Feature #4: Student Login Statistics
class StudentLoginInfo(Schema):
    id: int
    name: str
    last_login: Optional[datetime] = None
    login_count: int


class ClassLoginStats(Schema):
    class_id: int
    class_name: str
    total: int
    logged_in: int
    never_logged_in: int
    students: List[StudentLoginInfo]


class LoginStatsSummary(Schema):
    total: int
    logged_in: int
    never_logged_in: int


class LoginStatsResponse(Schema):
    summary: LoginStatsSummary
    per_class: List[ClassLoginStats]


# ============================================================================
# Mulasztás (eKréta Upload) Schemas - EXPERIMENTAL
# ============================================================================

class MulasztasUploadSchema(Schema):
    """Extended Mulasztas schema with analysis fields for student uploads"""
    id: int
    datum: DateType
    ora: int
    tantargy: str
    tema: str
    tipus: str
    igazolt: bool
    tanorai_celu_mulasztas: bool
    igazolas_tipusa: Optional[str] = None
    rogzites_datuma: DateType
    mulasztas_ok: Optional[str] = None
    mulasztas_statusz: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    # Analysis fields
    matched_igazolas_id: Optional[int] = None
    is_covered: Optional[bool] = None


class MulasztasAnalysisResult(Schema):
    total_mulasztasok: int
    igazolt_count: int
    nem_igazolt_count: int
    covered_by_igazolas: int
    not_covered: int
    mulasztasok: List[MulasztasUploadSchema]


class UploadMulasztasResponse(Schema):
    success: bool
    message: str
    total_processed: int
    created_count: int
    updated_count: int
    error_count: int
    errors: List[str]
    analysis: Optional[MulasztasAnalysisResult] = None


# ============================================================================
# Admin Phase 2 Schemas - Analytics & Monitoring
# ============================================================================

# Feature #2: Class Activity Heatmap
class ActivityDataPoint(Schema):
    date: DateType
    value: int
    intensity: int  # 0-5 scale for visualization


class ClassActivityData(Schema):
    id: int
    name: str
    data: List[ActivityDataPoint]


class ActivityHeatmapResponse(Schema):
    dates: List[DateType]
    classes: List[ClassActivityData]


class ClassOverviewStats(Schema):
    id: int
    name: str
    total_students: int
    active_students: int
    pending_count: int
    approval_rate: float
    last_activity: Optional[datetime] = None


class ClassesOverviewResponse(Schema):
    classes: List[ClassOverviewStats]


# Feature #5: Teacher Workload Dashboard
class TeacherWorkloadInfo(Schema):
    id: int
    name: str
    classes: List[str]
    total_students: int
    pending_count: int
    approved_today: int
    rejected_today: int
    avg_response_time_hours: Optional[float] = None


class TeacherWorkloadResponse(Schema):
    teachers: List[TeacherWorkloadInfo]


# Feature #7: Teacher Activity Monitoring
class ActivityTimelinePoint(Schema):
    date: DateType
    action_type: str
    count: int


class ActionsBreakdown(Schema):
    approved: int
    rejected: int
    commented: int


class TeacherActivityResponse(Schema):
    user: UserSchema
    login_count: int
    total_actions: int
    actions_breakdown: ActionsBreakdown
    activity_timeline: List[ActivityTimelinePoint]


# Feature #20: Approval Rate Analysis
class ApprovalRateByTeacher(Schema):
    teacher_id: int
    teacher_name: str
    total: int
    approved: int
    rejected: int
    approval_rate: float


class ApprovalRateByType(Schema):
    type_id: int
    type_name: str
    total: int
    approved: int
    rejected: int
    approval_rate: float


class ApprovalRateByClass(Schema):
    class_id: int
    class_name: str
    total: int
    approved: int
    rejected: int
    approval_rate: float


class TrendDataPoint(Schema):
    date: DateType
    approval_rate: float
    total: int


class ApprovalRatesResponse(Schema):
    overall_rate: float
    by_teacher: List[ApprovalRateByTeacher]
    by_type: List[ApprovalRateByType]
    by_class: List[ApprovalRateByClass]
    trend: List[TrendDataPoint]


# ============================================================================
# System Management Features (Phase 1)
# ============================================================================

# Feature #10: Database Statistics
class TableStats(Schema):
    name: str
    count: int
    percentage: float


class GrowthRate(Schema):
    daily: int
    weekly: int
    monthly: int


class DatabaseStatsResponse(Schema):
    total_users: int
    total_classes: int
    total_igazolasok: int
    total_mulasztasok: int
    growth_rate: GrowthRate
    db_size_mb: Optional[float] = None
    largest_tables: List[TableStats]


# Feature #12: Storage Usage Monitoring
class LargestFile(Schema):
    name: str
    size_mb: float
    type: str
    uploaded_date: Optional[datetime] = None


class StorageTrendPoint(Schema):
    date: DateType
    total_mb: float


class StorageStatsResponse(Schema):
    total_mb: float
    images_mb: float
    documents_mb: float
    other_mb: float
    largest_files: List[LargestFile]
    trend: List[StorageTrendPoint]


# Feature #19: Maintenance Mode
class MaintenanceStatusResponse(Schema):
    is_active: bool
    message: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    allowed_users: List[str]


class MaintenanceToggleRequest(Schema):
    enabled: bool
    message: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None


# ============================================================================
# Student & Teacher Features
# ============================================================================

# Feature #25: Group Absences Support
class EligibleStudent(Schema):
    id: int
    username: str
    first_name: str
    last_name: str
    full_name: str
    is_studios: bool


class EligibleStudentsResponse(Schema):
    eligible_students: List[EligibleStudent]
    total_count: int


class GroupIgazolasCreateRequest(Schema):
    eleje: datetime
    vege: datetime
    tipus: int
    megjegyzes_diak: Optional[str] = None
    imgDriveURL: Optional[str] = None
    bkk_verification: Optional[dict] = None
    sub_form_data: Optional[dict] = None  # New field for sub-form data
    reszletes_idopontok: Optional[list] = None  # Detailed intervals for non-contiguous absences
    additional_student_ids: List[int]  # List of student IDs to include in group


class GroupMemberInfo(Schema):
    id: int
    profile_id: int
    student_name: str
    status: str
    is_group_leader: bool


class GroupIgazolasCreateResponse(Schema):
    created_count: int
    group_id: str
    igazolasok: List[dict]
    message: str


class GroupMembersResponse(Schema):
    group_leader: Optional[GroupMemberInfo] = None
    members: List[GroupMemberInfo]
    group_id: str
    total_members: int


# Feature #27: Class Period Configuration
class PeriodUsageInfo(Schema):
    ora: int
    usage_count: int
    has_lessons: bool


class PeriodConfigResponse(Schema):
    class_id: int
    class_name: str
    enabled_periods: List[int]
    disabled_periods: List[int]


class UpdatePeriodConfigRequest(Schema):
    enabled_periods: List[int]


class PeriodUsageAnalysisResponse(Schema):
    class_id: int
    class_name: str
    periods: List[PeriodUsageInfo]
    recommendations: List[int]  # Periods that could be disabled


# ============================================================================
# Academic Year & Bulk Operations
# ============================================================================

# Feature #14: Academic Year Archival
class ArchivedYearInfo(Schema):
    year: str
    class_count: int
    student_count: int
    igazolasok_count: int


class ArchiveRequest(Schema):
    year_start: int
    archive_classes: bool = True
    archive_igazolasok: bool = True


class ArchiveResponse(Schema):
    archived_count: dict
    message: str


class ArchivedDataResponse(Schema):
    year: str
    classes: List[dict]
    students: List[dict]
    igazolasok: List[dict]


# Feature #9: Bulk Assignment
class StudentCreationData(Schema):
    id: int
    email: str
    username: str
    password: str
    first_login_url: str


class BulkCreateStudentsRequest(Schema):
    emails: List[str]
    class_id: int


class BulkCreateStudentsResponse(Schema):
    created: List[StudentCreationData]
    failed: List[str]
    message: str


class CreateClassRequest(Schema):
    tagozat: str
    kezdes_eve: int
    teacher_email: str
    student_emails: List[str]


class CreateClassResponse(Schema):
    class_id: int
    created_students: List[StudentCreationData]
    teacher_assigned: bool
    message: str


# Feature #26: Teacher-Created Igazolások
class TeacherCreateIgazolasRequest(Schema):
    student_id: int
    eleje: datetime
    vege: datetime
    tipus: int
    megjegyzes_diak: Optional[str] = None
    reszletes_idopontok: Optional[list] = None  # Detailed intervals for non-contiguous absences


class TeacherBulkCreateIgazolasRequest(Schema):
    student_ids: List[int]
    eleje: datetime
    vege: datetime
    tipus: int
    megjegyzes_diak: Optional[str] = None
    reszletes_idopontok: Optional[list] = None  # Detailed intervals for non-contiguous absences


class EligibleStudentForTeacher(Schema):
    id: int
    username: str
    full_name: str
    class_name: str
    recent_absences: int


# Feature #11: API Performance Metrics
class APIMetricsEndpoint(Schema):
    path: str
    method: str
    avg_response_ms: float
    request_count: int
    error_count: int
    p95_response_ms: Optional[float] = None
    error_rate: float  # percentage


class APIMetricsResponse(Schema):
    endpoints: List[APIMetricsEndpoint]
    slowest_endpoints: List[APIMetricsEndpoint]
    most_used: List[APIMetricsEndpoint]
    total_requests: int
    average_response_time: float
    from_date: Optional[str] = None
    to_date: Optional[str] = None


class APIMetricsRefreshResponse(Schema):
    message: str
    recorded_count: int


# Feature #15: Manual Attendance Management
class AttendanceCreateRequest(Schema):
    student_id: int
    datum: str  # Date in YYYY-MM-DD format
    ora: int
    tantargy: str
    tema: str
    tipus: str
    igazolt: bool
    igazolas_id: Optional[int] = None


class AttendanceUpdateRequest(Schema):
    datum: Optional[str] = None
    ora: Optional[int] = None
    tantargy: Optional[str] = None
    tema: Optional[str] = None
    tipus: Optional[str] = None
    igazolt: Optional[bool] = None
    igazolas_id: Optional[int] = None


class AttendanceResponse(Schema):
    id: int
    student_id: int
    student_name: str
    datum: str
    ora: int
    tantargy: str
    tema: str
    tipus: str
    igazolt: bool
    igazolas_id: Optional[int] = None
    igazolas_tipusa: Optional[str] = None
    rogzites_datuma: str


class StudentAttendanceResponse(Schema):
    student_id: int
    student_name: str
    attendance_records: List[AttendanceResponse]
    total_count: int
    igazolt_count: int
    igazolatlan_count: int


# Feature #28: Permission Matrix
class PermissionMatrixResponse(Schema):
    classes: List[OsztalySimpleSchema]
    types: List[IgazolasTipusSchema]
    matrix: dict  # { class_id: { type_id: boolean } }


class UpdatePermissionRequest(Schema):
    class_id: int
    type_id: int
    allowed: bool


class UpdatePermissionResponse(Schema):
    updated: bool
    message: str


class BulkUpdatePermissionsRequest(Schema):
    updates: List[UpdatePermissionRequest]


class BulkUpdatePermissionsResponse(Schema):
    updated_count: int
    failed_count: int
    message: str


# Feature #8: Multiple Class Support
class ClassAssignment(Schema):
    id: int
    class_id: int
    class_name: str
    is_primary: bool
    assigned_date: str
    delegation_end_date: Optional[str] = None


class AssignClassesRequest(Schema):
    class_ids: List[int]
    is_primary: bool
    delegation_end_date: Optional[str] = None


class TeacherClassesResponse(Schema):
    teacher_id: int
    teacher_name: str
    classes: List[ClassAssignment]
