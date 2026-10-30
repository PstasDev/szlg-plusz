import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit
from oauth2_provider.models import Application

from .application_verification import (
    application_verification_snapshot,
    verification_missing_requirements,
)
from .forms import (
    ApplicationVerificationDecisionForm,
    ApplicationVerificationSubmissionForm,
)
from .models import (
    AccountReviewStatus,
    ApplicationProfile,
    ApplicationVerificationRequest,
    CustomUser,
)

logger = logging.getLogger(__name__)

OPEN_STATUSES = (
    ApplicationVerificationRequest.Status.PENDING,
    ApplicationVerificationRequest.Status.LEGACY_REVIEW,
)


def _require_staff(request):
    if not (request.user.is_staff or request.user.is_superuser):
        raise PermissionDenied


def _send_admin_notification(request, verification_request):
    application = verification_request.application
    admins = CustomUser.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(is_superuser=True)
    )
    recipients = list(dict.fromkeys(admins.values_list("email", flat=True)))
    if not recipients:
        logger.warning(
            "No active administrator could be notified about application verification %s",
            verification_request.pk,
        )
        return False

    review_url = request.build_absolute_uri(reverse("application-review-list"))
    body = (
        "Új alkalmazás-ellenőrzési kérelem érkezett.\n\n"
        f"Alkalmazás: {application.name}\n"
        f"Fejlesztő: {application.profile.developer}\n"
        f"Tulajdonos: {application.user.email}\n\n"
        "A kérelmet a dashboard Manuális felülvizsgálat / Alkalmazások oldalán nézheted meg:\n"
        f"{review_url}\n"
    )
    try:
        return bool(
            send_mail(
                "[SZLG+] Alkalmazás vár ellenőrzésre",
                body,
                settings.DEFAULT_FROM_EMAIL,
                recipients,
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception(
            "Could not notify administrators about application verification %s",
            verification_request.pk,
        )
        return False


def _send_developer_decision(request, verification_request):
    application = verification_request.application
    owner = application.user if application.user_id else None
    if owner is None or not owner.email:
        return False

    if verification_request.status == ApplicationVerificationRequest.Status.APPROVED:
        subject = "Az SZLG+ ellenőrizte az alkalmazásodat"
        decision = (
            "Az alkalmazás ellenőrzési kérelmét jóváhagytuk. Az alkalmazás mostantól "
            "ellenőrzöttként jelenik meg az SZLG+ felületein."
        )
    elif verification_request.status == ApplicationVerificationRequest.Status.CHANGES_REQUESTED:
        subject = "Javítás szükséges az SZLG+ alkalmazás-ellenőrzéséhez"
        decision = (
            "Az ellenőrzés folytatásához módosítanod kell az alkalmazás adatait. "
            "A javítás után új ellenőrzési kérelmet küldhetsz be."
        )
    elif verification_request.status == ApplicationVerificationRequest.Status.SUPERSEDED:
        subject = "Az SZLG+ alkalmazás-ellenőrzési kérelme frissítésre szorul"
        decision = (
            "A kérelem beküldése óta megváltoztak az alkalmazás adatai, ezért a korábbi "
            "kérelmet lezártuk. Ellenőrizd az adatokat, majd küldj be új kérelmet."
        )
    else:
        subject = "Az SZLG+ nem hagyta jóvá az alkalmazás ellenőrzését"
        decision = (
            "Az alkalmazás ellenőrzési kérelmét elutasítottuk. Az alkalmazás "
            "ellenőrizetlen marad; az indoklást alább találod."
        )

    detail_url = request.build_absolute_uri(
        reverse("application-detail", args=[application.pk])
    )
    body = (
        f"Kedves {owner.get_full_name() or owner.email}!\n\n"
        f"{decision}\n\n"
        f"Alkalmazás: {application.name}\n"
        f"Indoklás / teendő: {verification_request.reviewer_note or 'Nincs külön megjegyzés.'}\n\n"
        f"Az alkalmazás beállításai: {detail_url}\n"
    )
    try:
        return bool(
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [owner.email],
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception(
            "Could not send application verification decision %s to owner %s",
            verification_request.pk,
            owner.pk,
        )
        return False


def _send_submission_confirmation(request, verification_request):
    application = verification_request.application
    owner = application.user if application.user_id else None
    if owner is None or not owner.email:
        return False
    detail_url = request.build_absolute_uri(
        reverse("application-detail", args=[application.pk])
    )
    body = (
        f"Kedves {owner.get_full_name() or owner.email}!\n\n"
        f"Megkaptuk a(z) „{application.name}” alkalmazás ellenőrzési kérelmét. "
        "A döntésig az alkalmazás ellenőrizetlen marad. Az állapotot itt követheted:\n"
        f"{detail_url}\n"
    )
    try:
        return bool(
            send_mail(
                "Az SZLG+ megkapta az alkalmazás-ellenőrzési kérelmedet",
                body,
                settings.DEFAULT_FROM_EMAIL,
                [owner.email],
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception(
            "Could not send application verification receipt %s to owner %s",
            verification_request.pk,
            owner.pk,
        )
        return False


@login_required
@require_POST
@ratelimit(key="user", rate="5/h", method="POST", block=True)
def request_application_verification(request, pk):
    application = get_object_or_404(
        Application.objects.select_related("profile", "user"),
        pk=pk,
        user=request.user,
    )
    try:
        profile = application.profile
    except ApplicationProfile.DoesNotExist:
        messages.error(request, "Előbb töltsd ki az alkalmazás nyilvános adatait.")
        return redirect("application-detail", pk=application.pk)

    if profile.verified:
        messages.info(request, "Ezt az alkalmazást már ellenőrizte az SZLG+.")
        return redirect("application-detail", pk=application.pk)

    form = ApplicationVerificationSubmissionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "A kérelem nem érvényes.")
        return redirect("application-detail", pk=application.pk)

    missing = verification_missing_requirements(application)
    if missing:
        for item in missing:
            messages.error(request, item)
        return redirect("application-edit", pk=application.pk)

    try:
        with transaction.atomic():
            if ApplicationVerificationRequest.objects.filter(
                application=application,
                status__in=OPEN_STATUSES,
            ).exists():
                messages.info(request, "Ehhez az alkalmazáshoz már van függőben lévő kérelem.")
                return redirect("application-detail", pk=application.pk)

            verification_request = ApplicationVerificationRequest.objects.create(
                application=application,
                submitted_by=request.user,
                status=ApplicationVerificationRequest.Status.PENDING,
                developer_note=form.cleaned_data["developer_note"].strip(),
                submitted_snapshot=application_verification_snapshot(application),
            )
    except IntegrityError:
        messages.info(request, "Ehhez az alkalmazáshoz már van függőben lévő kérelem.")
        return redirect("application-detail", pk=application.pk)

    _send_admin_notification(request, verification_request)
    _send_submission_confirmation(request, verification_request)
    messages.success(
        request,
        "Elküldtük az ellenőrzési kérelmet. A döntésig az alkalmazás ellenőrizetlen marad.",
    )
    return redirect("application-detail", pk=application.pk)


@login_required
@require_GET
def application_verification_list(request):
    _require_staff(request)
    requests = ApplicationVerificationRequest.objects.select_related(
        "application",
        "application__profile",
        "application__user",
        "submitted_by",
        "reviewed_by",
    )
    pending_requests = requests.filter(status__in=OPEN_STATUSES)
    completed_requests = requests.exclude(status__in=OPEN_STATUSES)[:50]
    return render(
        request,
        "dashboard/application_review_list.html",
        {
            "section": "manual-review",
            "review_tab": "applications",
            "pending_requests": pending_requests,
            "completed_requests": completed_requests,
            "pending_count": pending_requests.count(),
            "account_pending_count": CustomUser.objects.filter(
                account_review_status=AccountReviewStatus.PENDING
            ).count(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def application_verification_detail(request, pk):
    _require_staff(request)
    verification_request = get_object_or_404(
        ApplicationVerificationRequest.objects.select_related(
            "application",
            "application__profile",
            "application__user",
            "submitted_by",
            "reviewed_by",
        ),
        pk=pk,
    )
    if verification_request.status not in OPEN_STATUSES:
        return redirect("application-review-list")

    application = verification_request.application
    form = ApplicationVerificationDecisionForm(
        request.POST or None,
        initial={"reviewer_note": verification_request.reviewer_note},
    )
    if request.method == "POST":
        action = request.POST.get("action")
        if action not in {"approve", "reject", "changes_requested"}:
            form.add_error(None, "Válassz érvényes felülvizsgálati műveletet.")
        elif form.is_valid():
            missing = verification_missing_requirements(application)
            if action == "approve" and missing:
                form.add_error(
                    None,
                    "A kérelem nem hagyható jóvá, amíg a fejlesztő nem pótolja a hiányzó adatokat.",
                )
            elif (
                action == "approve"
                and (
                    verification_request.submitted_by_id == request.user.pk
                    or application.user_id == request.user.pk
                )
            ):
                form.add_error(
                    None,
                    "Saját alkalmazásod ellenőrzési kérelmét nem hagyhatod jóvá.",
                )
            else:
                stale_request = False
                already_reviewed = False
                with transaction.atomic():
                    locked_request = ApplicationVerificationRequest.objects.select_for_update().get(
                        pk=verification_request.pk
                    )
                    if locked_request.status not in OPEN_STATUSES:
                        already_reviewed = True
                    else:
                        locked_application = Application.objects.select_for_update().select_related(
                            "profile", "user"
                        ).get(pk=locked_request.application_id)
                        profile = locked_application.profile
                        snapshot = locked_request.submitted_snapshot
                        if snapshot and snapshot != application_verification_snapshot(
                            locked_application
                        ):
                            profile.verified = False
                            profile.save(update_fields=["verified"])
                            locked_request.status = (
                                ApplicationVerificationRequest.Status.SUPERSEDED
                            )
                            locked_request.reviewer_note = (
                                "Az alkalmazás adatai a beküldés óta megváltoztak. "
                                "Az aktuális adatokkal új kérelmet kell beküldeni."
                            )
                            stale_request = True
                        else:
                            if action == "approve":
                                locked_request.status = (
                                    ApplicationVerificationRequest.Status.APPROVED
                                )
                                profile.verified = True
                            elif action == "changes_requested":
                                locked_request.status = (
                                    ApplicationVerificationRequest.Status.CHANGES_REQUESTED
                                )
                                profile.verified = False
                            else:
                                locked_request.status = (
                                    ApplicationVerificationRequest.Status.REJECTED
                                )
                                profile.verified = False
                            profile.save(update_fields=["verified"])
                            locked_request.reviewer_note = form.cleaned_data[
                                "reviewer_note"
                            ].strip()
                        locked_request.reviewed_by = request.user
                        locked_request.reviewed_at = timezone.now()
                        locked_request.save(
                            update_fields=(
                                "status",
                                "reviewer_note",
                                "reviewed_by",
                                "reviewed_at",
                            )
                        )

                if already_reviewed:
                    messages.info(
                        request,
                        "Egy másik adminisztrátor már elvégezte a felülvizsgálatot.",
                    )
                    return redirect("application-review-list")
                verification_request.refresh_from_db()
                if stale_request:
                    messages.warning(
                        request,
                        "Az alkalmazás adatai időközben megváltoztak. A régi kérelmet lezártuk; a friss adatokkal újat kell beküldeni.",
                    )
                    _send_developer_decision(request, verification_request)
                    return redirect("application-review-list")

                _send_developer_decision(request, verification_request)
                messages.success(
                    request,
                    {
                        "approve": "Az alkalmazást ellenőrzöttnek jelöltük.",
                        "reject": "A kérelmet elutasítottuk.",
                        "changes_requested": "A fejlesztőtől javítást kértünk.",
                    }[action],
                )
                return redirect("application-review-list")

    return render(
        request,
        "dashboard/application_review_detail.html",
        {
            "section": "manual-review",
            "review_tab": "applications",
            "verification_request": verification_request,
            "application": application,
            "redirect_uris": application.redirect_uris.split(),
            "form": form,
            "missing_requirements": verification_missing_requirements(application),
            "is_legacy_review": (
                verification_request.status
                == ApplicationVerificationRequest.Status.LEGACY_REVIEW
            ),
        },
    )
