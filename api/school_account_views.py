import logging
import secrets
import uuid
from datetime import timedelta
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from .forms import (
    ManualReviewForm,
    SchoolAccountEmailForm,
    SchoolAccountOTPForm,
    SchoolAccountRegistrationForm,
)
from .models import (
    AccountReviewStatus,
    ApplicationVerificationRequest,
    CustomUser,
    ManualReviewRequest,
    SchoolAccountOTP,
    StudentProfile,
    TeacherProfile,
    email_info,
)
from .privacy import get_administrator_contacts, privacy_context

logger = logging.getLogger(__name__)

OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_SESSION_KEY = "school_account_setup_challenge"
SIGNUP_SESSION_KEY = "school_account_signup"
PREFILL_SESSION_KEY = "school_account_prefill_email"
SUBMITTED_SESSION_KEY = "school_account_submitted_email"


def _clear_school_account_session(request):
    for key in (OTP_SESSION_KEY, SIGNUP_SESSION_KEY):
        request.session.pop(key, None)


def _status_page(request, user, status):
    return render(
        request,
        "registration/school_account_status.html",
        {
            "email": user.email,
            "review_status": status,
            **privacy_context(),
        },
    )


def _send_setup_otp(user, code):
    body = (
        f"Kedves {user.get_full_name() or user.email}!\n\n"
        "A SZLG+ fiókodhoz tartozó e-mail-cím ellenőrzéséhez és a jelszó beállításához "
        "használd ezt az egyszer használatos kódot:\n\n"
        f"{code}\n\n"
        "A kód 10 percig és legfeljebb 5 próbálkozásig érvényes. Ha nem te kérted, "
        "hagyd figyelmen kívül ezt a levelet.\n"
    )
    try:
        return bool(
            send_mail(
                "SZLG+ – e-mail-ellenőrző kód",
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception("Could not send a school-account setup OTP for user %s", user.pk)
        return False


def _otp_digest(challenge_id, code):
    return salted_hmac(
        "api.school-account-setup-otp",
        f"{challenge_id}:{code}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def _send_admin_review_notification(request, user, review_request):
    admins = CustomUser.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(is_superuser=True)
    )
    recipients = list(dict.fromkeys(admins.values_list("email", flat=True)))
    if not recipients:
        logger.warning("No active SZLG+ administrator could be notified about review %s", review_request.pk)
        return False

    review_url = request.build_absolute_uri(reverse("manual-review-list"))
    body = (
        "Új SZLG+ fiók vár manuális felülvizsgálatra.\n\n"
        f"Név: {user.get_full_name() or 'Nincs megadva'}\n"
        f"Iskolai e-mail-cím: {user.email}\n"
        f"Jelentkező típusa: {review_request.get_applicant_type_display()}\n\n"
        "A fiók a jóváhagyásig nem fér hozzá az SZLG+ szolgáltatásaihoz. "
        "Kérjük, ellenőrizd a jelentkezést a dashboard Manuális Felülvizsgálat részén:\n"
        f"{review_url}\n"
    )
    try:
        return bool(
            send_mail(
                "[SZLG+] Új fiók vár manuális felülvizsgálatra",
                body,
                settings.DEFAULT_FROM_EMAIL,
                recipients,
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception("Could not notify administrators about review %s", review_request.pk)
        return False


def _send_review_decision(request, user, approved, reviewer_note=""):
    if approved:
        subject = "Az SZLG+ fiókodat jóváhagytuk"
        body = (
            f"Kedves {user.get_full_name() or user.email}!\n\n"
            "Az SZLG+ fiókodat az adminisztrátorok jóváhagyták. Most már bejelentkezhetsz:\n"
            f"{request.build_absolute_uri(reverse('login'))}\n"
        )
    else:
        subject = "Az SZLG+ fiókodat nem hagytuk jóvá"
        body = (
            f"Kedves {user.get_full_name() or user.email}!\n\n"
            "Az SZLG+ fiókodat az adminisztrátorok nem hagyták jóvá. "
            "Ha kérdésed van, keresd az alábbi SZLG+ kapcsolattartók egyikét:\n"
        )
        contacts = get_administrator_contacts()
        contact_lines = [
            f"{contact.get_full_name() or contact.email} · {contact.email}"
            for contact in contacts
        ]
        body += "\n".join(contact_lines) if contact_lines else "Az iskola adminisztrációját."
        body += "\n"
        if reviewer_note:
            body += f"\nAz adminisztrátor megjegyzése: {reviewer_note}\n"
    try:
        return bool(
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception("Could not send a review decision to user %s", user.pk)
        return False


def _school_email_rate_limit_key(_group, request):
    return request.POST.get("email", "").strip().lower()


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
@ratelimit(key=_school_email_rate_limit_key, rate="3/h", method="POST", block=True)
def school_account_setup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    initial = {"email": request.session.get(PREFILL_SESSION_KEY, "")}
    form = SchoolAccountEmailForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        info = email_info(email)
        if not info.is_in_school_domain:
            form.add_error("email", "Ehhez a folyamathoz az iskola e-mail-domainjét használd.")
        else:
            request.session.pop(PREFILL_SESSION_KEY, None)
            request.session.pop(SUBMITTED_SESSION_KEY, None)
            _clear_school_account_session(request)
            user = CustomUser.objects.filter(email__iexact=email).first()

            if user is not None:
                if user.account_review_status == AccountReviewStatus.PENDING:
                    return _status_page(request, user, AccountReviewStatus.PENDING)
                if user.account_review_status == AccountReviewStatus.REJECTED:
                    return _status_page(request, user, AccountReviewStatus.REJECTED)
                if not user.is_active:
                    return _status_page(request, user, "inactive")

                code = f"{secrets.randbelow(1_000_000):06d}"
                challenge_id = uuid.uuid4()
                now = timezone.now()
                SchoolAccountOTP.objects.update_or_create(
                    user=user,
                    defaults={
                        "challenge_id": challenge_id,
                        "code_hash": _otp_digest(challenge_id, code),
                        "expires_at": now + OTP_TTL,
                        "attempts": 0,
                        "verified_at": None,
                    },
                )
                if not _send_setup_otp(user, code):
                    SchoolAccountOTP.objects.filter(
                        user=user, challenge_id=challenge_id
                    ).delete()
                    form.add_error(
                        None,
                        "Most nem sikerült elküldeni az ellenőrző kódot. Próbáld meg később újra.",
                    )
                else:
                    request.session[OTP_SESSION_KEY] = str(challenge_id)
                    return redirect("school-account-otp")
            else:
                registration_kind = (
                    "student"
                    if info.is_student or info.is_part_time_student
                    else "employee"
                )
                request.session[SIGNUP_SESSION_KEY] = {
                    "email": email,
                    "registration_kind": registration_kind,
                }
                return redirect("school-account-register")

    return render(
        request,
        "registration/school_account_setup.html",
        {"form": form, **privacy_context()},
    )


def _session_otp_challenge(request):
    raw_challenge_id = request.session.get(OTP_SESSION_KEY)
    if not raw_challenge_id:
        return None
    try:
        challenge_id = uuid.UUID(str(raw_challenge_id))
    except (TypeError, ValueError, AttributeError):
        request.session.pop(OTP_SESSION_KEY, None)
        return None

    challenge = (
        SchoolAccountOTP.objects.select_related("user")
        .filter(challenge_id=challenge_id)
        .first()
    )
    if challenge is None:
        request.session.pop(OTP_SESSION_KEY, None)
        return None
    if challenge.expires_at <= timezone.now():
        challenge.delete()
        request.session.pop(OTP_SESSION_KEY, None)
        return None
    if (
        not challenge.user.is_active
        or challenge.user.account_review_status
        in {AccountReviewStatus.PENDING, AccountReviewStatus.REJECTED}
    ):
        challenge.delete()
        request.session.pop(OTP_SESSION_KEY, None)
        return None
    return challenge


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate="20/h", method="POST", block=True)
def school_account_otp(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    challenge = _session_otp_challenge(request)
    if challenge is None:
        messages.error(request, "A kódkérés lejárt. Add meg újra az iskolai e-mail-címedet.")
        return redirect("school-account-setup")
    if challenge.verified_at:
        return redirect("school-account-password")

    form = SchoolAccountOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        locked = None
        challenge_invalid = False
        with transaction.atomic():
            locked = (
                SchoolAccountOTP.objects.select_for_update()
                .filter(user=challenge.user)
                .first()
            )
            if (
                locked is None
                or locked.challenge_id != challenge.challenge_id
                or locked.expires_at <= timezone.now()
                or locked.attempts >= OTP_MAX_ATTEMPTS
            ):
                challenge_invalid = True
                if locked is not None and (
                    locked.expires_at <= timezone.now()
                    or locked.attempts >= OTP_MAX_ATTEMPTS
                ):
                    locked.delete()
                request.session.pop(OTP_SESSION_KEY, None)
            elif constant_time_compare(
                _otp_digest(locked.challenge_id, form.cleaned_data["code"]),
                locked.code_hash,
            ):
                locked.verified_at = timezone.now()
                locked.save(update_fields=["verified_at"])
                return redirect("school-account-password")
            else:
                locked.attempts += 1
                if locked.attempts >= OTP_MAX_ATTEMPTS:
                    locked.delete()
                    request.session.pop(OTP_SESSION_KEY, None)
                else:
                    locked.save(update_fields=["attempts"])

        if challenge_invalid or locked is None or locked.challenge_id != challenge.challenge_id:
            messages.error(request, "A kódkérés lejárt vagy lecserélődött. Kérj új kódot.")
            return redirect("school-account-setup")
        if locked.attempts >= OTP_MAX_ATTEMPTS:
            messages.error(request, "Túl sok hibás próbálkozás. Kérj új ellenőrző kódot.")
            return redirect("school-account-setup")
        form.add_error("code", "A kód nem megfelelő. Ellenőrizd a levelet, vagy kérj új kódot.")

    return render(
        request,
        "registration/school_account_otp.html",
        {"form": form, "email": challenge.user.email, **privacy_context()},
    )


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
def school_account_password(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    challenge = _session_otp_challenge(request)
    if challenge is None or not challenge.verified_at:
        messages.error(request, "Előbb igazold az e-mail-címedet az elküldött kóddal.")
        return redirect("school-account-setup")

    form = SetPasswordForm(challenge.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        completed = False
        with transaction.atomic():
            locked = (
                SchoolAccountOTP.objects.select_for_update()
                .filter(user=challenge.user)
                .first()
            )
            user = CustomUser.objects.select_for_update().filter(pk=challenge.user_id).first()
            if (
                locked is not None
                and locked.challenge_id == challenge.challenge_id
                and locked.verified_at is not None
                and locked.expires_at > timezone.now()
                and user is not None
                and user.is_active
                and user.account_review_status
                not in {AccountReviewStatus.PENDING, AccountReviewStatus.REJECTED}
            ):
                form.user = user
                form.save()
                locked.delete()
                completed = True
            elif locked is not None:
                locked.delete()

        request.session.pop(OTP_SESSION_KEY, None)
        if completed:
            messages.success(request, "A jelszavadat beállítottuk. Most már bejelentkezhetsz.")
            return redirect("password-reset-complete")
        form.add_error(None, "A kódkérés lejárt vagy a fiók állapota megváltozott. Kezdd újra a folyamatot.")

    return render(
        request,
        "registration/school_account_password.html",
        {"form": form, **privacy_context()},
    )


def _registration_state(request):
    state = request.session.get(SIGNUP_SESSION_KEY)
    if not isinstance(state, dict):
        return None
    email = state.get("email")
    registration_kind = state.get("registration_kind")
    if not isinstance(email, str) or registration_kind not in {"student", "employee"}:
        return None
    info = email_info(email)
    if not info.is_in_school_domain:
        return None
    if registration_kind == "student" and not (info.is_student or info.is_part_time_student):
        return None
    if registration_kind == "employee" and (info.is_student or info.is_part_time_student):
        return None
    return email, registration_kind, info


def _render_school_account_registration(request, form, email, registration_kind, info):
    class_year_section = info.class_from_email
    class_display = None
    if class_year_section:
        start_year, section = class_year_section
        class_display = f"{start_year}{section}"
    return render(
        request,
        "registration/school_account_register.html",
        {
            "form": form,
            "school_email": email,
            "registration_kind": registration_kind,
            "class_display": class_display,
            **privacy_context(),
        },
    )


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
def school_account_register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    registration_state = _registration_state(request)
    if registration_state is None:
        request.session.pop(SIGNUP_SESSION_KEY, None)
        messages.error(request, "Kezdd újra az iskolai fiók regisztrációját.")
        return redirect("school-account-setup")

    email, registration_kind, info = registration_state
    if CustomUser.objects.filter(email__iexact=email).exists():
        request.session[PREFILL_SESSION_KEY] = email
        request.session.pop(SIGNUP_SESSION_KEY, None)
        messages.info(request, "Ehhez az e-mail-címhez már fiók tartozik. Ellenőrizd az e-mail-címedet.")
        return redirect("school-account-setup")

    form = SchoolAccountRegistrationForm(
        request.POST or None,
        email=email,
        registration_kind=registration_kind,
    )
    if request.method == "POST" and form.is_valid():
        applicant_type = (
            ManualReviewRequest.ApplicantType.STUDENT
            if registration_kind == "student"
            else form.cleaned_data["applicant_type"]
        )
        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    email=email,
                    password=form.cleaned_data["password1"],
                    first_name=form.cleaned_data["first_name"].strip(),
                    last_name=form.cleaned_data["last_name"].strip(),
                    phone=form.cleaned_data["phone"].strip(),
                    date_of_birth=form.cleaned_data["date_of_birth"],
                    is_active=False,
                    email_verified=False,
                    account_review_status=AccountReviewStatus.PENDING,
                    privacy_consent_at=timezone.now(),
                )
                if applicant_type == ManualReviewRequest.ApplicantType.STUDENT:
                    class_year_section = info.class_from_email
                    StudentProfile.objects.create(
                        user=user,
                        om_id=(form.cleaned_data.get("om_id") or "").strip(),
                        tagozat=form.cleaned_data.get("tagozat"),
                        kezdes_eve=class_year_section[0] if class_year_section else None,
                        szekcio=class_year_section[1] if class_year_section else "",
                    )

                review_request = ManualReviewRequest.objects.create(
                    user=user,
                    applicant_type=applicant_type,
                    position=(form.cleaned_data.get("position") or "").strip(),
                    employee_number=(form.cleaned_data.get("employee_number") or "").strip(),
                )
                if applicant_type == ManualReviewRequest.ApplicantType.TEACHER:
                    TeacherProfile.objects.create(
                        user=user,
                        employee_number=review_request.employee_number,
                    )
        except IntegrityError:
            request.session[PREFILL_SESSION_KEY] = email
            request.session.pop(SIGNUP_SESSION_KEY, None)
            messages.info(request, "Ehhez az e-mail-címhez már fiók tartozik. Indítsd újra a folyamatot.")
            return redirect("school-account-setup")

        _send_admin_review_notification(request, user, review_request)
        request.session.pop(SIGNUP_SESSION_KEY, None)
        request.session[SUBMITTED_SESSION_KEY] = email
        return redirect("school-account-submitted")

    return _render_school_account_registration(request, form, email, registration_kind, info)


@require_http_methods(["GET"])
def school_account_submitted(request):
    email = request.session.get(SUBMITTED_SESSION_KEY)
    if not isinstance(email, str):
        return redirect("school-account-setup")
    return render(
        request,
        "registration/school_account_submitted.html",
        {"email": email, **privacy_context()},
    )


def _require_staff_dashboard_user(request):
    if not (request.user.is_staff or request.user.is_superuser):
        raise PermissionDenied


@login_required
@require_http_methods(["GET"])
def manual_review_list(request):
    _require_staff_dashboard_user(request)

    reviews = ManualReviewRequest.objects.select_related("user", "reviewed_by")
    pending_reviews = reviews.filter(user__account_review_status=AccountReviewStatus.PENDING)
    completed_reviews = reviews.exclude(
        user__account_review_status=AccountReviewStatus.PENDING
    )[:50]
    return render(
        request,
        "dashboard/manual_review_list.html",
        {
            "section": "manual-review",
            "review_tab": "accounts",
            "pending_reviews": pending_reviews,
            "completed_reviews": completed_reviews,
            "pending_count": pending_reviews.count(),
            "application_pending_count": ApplicationVerificationRequest.objects.filter(
                status__in=(
                    ApplicationVerificationRequest.Status.PENDING,
                    ApplicationVerificationRequest.Status.LEGACY_REVIEW,
                )
            ).count(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def manual_review_detail(request, pk):
    _require_staff_dashboard_user(request)

    review_request = get_object_or_404(
        ManualReviewRequest.objects.select_related("user", "reviewed_by"),
        pk=pk,
    )
    user = review_request.user
    if user.account_review_status != AccountReviewStatus.PENDING:
        return redirect("manual-review-list")

    form = ManualReviewForm(
        request.POST or None,
        user=user,
        review_request=review_request,
    )
    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action", "save")
        if action not in {"save", "approve", "reject"}:
            form.add_error(None, "Érvénytelen felülvizsgálati művelet.")
        else:
            approved = action == "approve"
            decision_made = action in {"approve", "reject"}
            already_reviewed = False
            with transaction.atomic():
                user = CustomUser.objects.select_for_update().get(pk=user.pk)
                review_request = ManualReviewRequest.objects.select_for_update().get(
                    pk=review_request.pk
                )
                if user.account_review_status != AccountReviewStatus.PENDING:
                    already_reviewed = True
                else:
                    form.user = user
                    form.review_request = review_request
                    form.save_review_details()
                    if decision_made:
                        user.account_review_status = (
                            AccountReviewStatus.APPROVED
                            if approved
                            else AccountReviewStatus.REJECTED
                        )
                        user.is_active = approved
                        user.email_verified = approved
                        user.save(
                            update_fields=[
                                "account_review_status",
                                "is_active",
                                "email_verified",
                            ]
                        )
                        review_request.reviewed_by = request.user
                        review_request.reviewed_at = timezone.now()
                        review_request.save(update_fields=["reviewed_by", "reviewed_at"])

            if already_reviewed:
                messages.info(request, "Egy másik adminisztrátor már elvégezte a felülvizsgálatot.")
                return redirect("manual-review-list")

            if decision_made:
                _send_review_decision(
                    request,
                    user,
                    approved,
                    reviewer_note=review_request.reviewer_note,
                )
                messages.success(
                    request,
                    "A fiókot jóváhagytuk és aktiváltuk."
                    if approved
                    else "A fiók jelentkezését elutasítottuk.",
                )
                return redirect("manual-review-list")

            messages.success(request, "A jelentkező adatait elmentettük.")
            return redirect("manual-review-detail", pk=review_request.pk)

    return render(
        request,
        "dashboard/manual_review_detail.html",
        {
            "section": "manual-review",
            "form": form,
            "review_request": review_request,
            "review_user": user,
        },
    )
