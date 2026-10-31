import logging
from smtplib import SMTPException

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from .forms import RegistrationForm
from .models import BotRegistrationAttempt, CustomUser, email_info
from .privacy import privacy_context
from .school_account_views import PREFILL_SESSION_KEY

logger = logging.getLogger(__name__)

CONFIRMATION_SALT = "szlg.email-confirmation"
CONFIRMATION_MAX_AGE = 3 * 24 * 60 * 60
EMAIL_CONFIRMATION_PENDING_MESSAGE = (
    "Ha ehhez a címhez megerősítésre váró SZLG+ fiók tartozik, elküldtük a megerősítő levelet."
)


def _confirmation_token(user: CustomUser) -> str:
    return signing.dumps(
        {"user_id": user.pk, "email": user.email},
        salt=CONFIRMATION_SALT,
        compress=True,
    )


def _send_confirmation_email(request, user: CustomUser) -> bool:
    confirmation_url = request.build_absolute_uri(
        reverse("email-confirm", args=[_confirmation_token(user)])
    )
    body = (
        f"Kedves {user.get_full_name() or user.email}!\n\n"
        "A SZLG+ fiók regisztrációjának befejezéséhez erősítsd meg az e-mail-címedet "
        "az alábbi hivatkozáson. A fiók a megerősítésig nem használható bejelentkezésre.\n\n"
        f"{confirmation_url}\n\n"
        "A hivatkozás 3 napig érvényes. Ha nem te kezdeményezted a regisztrációt, "
        "hagyd figyelmen kívül ezt a levelet.\n"
    )
    try:
        return bool(
            send_mail(
                "SZLG+ e-mail-cím megerősítése",
                body,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        )
    except (SMTPException, OSError):
        logger.exception("SZLG+ confirmation email could not be sent for user %s", user.pk)
        return False


def _user_from_confirmation_token(token: str):
    try:
        payload = signing.loads(
            token,
            salt=CONFIRMATION_SALT,
            max_age=CONFIRMATION_MAX_AGE,
        )
    except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    email = payload.get("email")
    if not isinstance(user_id, int) or not isinstance(email, str):
        return None
    return CustomUser.objects.filter(
        pk=user_id,
        email=email,
        is_active=False,
        email_verified=False,
        privacy_consent_at__isnull=False,
    ).first()


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
@ratelimit(key="post:email", rate="3/h", method="POST", block=True)
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST" and request.POST.get("website", ""):
        # Match NodeWS's honeypot: record only non-sensitive fields and return
        # the same confirmation page without creating a user or sending mail.
        safe_fields = {"email", "first_name", "last_name", "privacy_consent"}
        form_data = {
            key: value[:500]
            for key, value in request.POST.items()
            if key in safe_fields
        }
        BotRegistrationAttempt.objects.create(form_data=form_data)
        return render(
            request,
            "registration/registration_sent.html",
            {
                "email": request.POST.get("email", "").strip()[:254],
                "email_sent": True,
                **privacy_context(),
            },
        )

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    email=email,
                    password=form.cleaned_data["password1"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    is_active=False,
                    email_verified=False,
                    privacy_consent_at=timezone.now(),
                )
        except IntegrityError:
            # A concurrent request may have claimed the address after form validation.
            form.add_error(
                "email",
                "Ehhez az e-mail-címhez már tartozik fiók. Jelentkezz be, vagy kérj jelszó-visszaállítást.",
            )
        else:
            email_sent = _send_confirmation_email(request, user)
            return render(
                request,
                "registration/registration_sent.html",
                {
                    "email": user.email,
                    "email_sent": email_sent,
                    **privacy_context(),
                },
            )

    if request.method == "POST" and form.school_domain_attempted:
        request.session[PREFILL_SESSION_KEY] = request.POST.get("email", "").strip().lower()
        return redirect("school-account-setup")

    return render(
        request,
        "registration/register.html",
        {
            "form": form,
            "school_domain_attempted": form.school_domain_attempted,
            **privacy_context(),
        },
    )


@require_http_methods(["GET", "POST"])
def email_confirmation(request, token: str):
    user = _user_from_confirmation_token(token)
    if request.method == "POST" and user is not None:
        user.email_verified = True
        user.is_active = True
        user.save(update_fields=["email_verified", "is_active"])
        return redirect("email-confirmed")

    return render(
        request,
        "registration/email_confirmation.html",
        {"valid_token": user is not None, **privacy_context()},
        status=200 if user is not None else 400,
    )


@require_http_methods(["GET", "POST"])
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
@ratelimit(key="post:email", rate="3/h", method="POST", block=True)
def resend_confirmation(request):
    email = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        if email and not email_info(email).is_in_school_domain:
            user = get_user_model().objects.filter(
                email__iexact=email,
                is_active=False,
                email_verified=False,
                privacy_consent_at__isnull=False,
            ).first()
            if user is not None:
                _send_confirmation_email(request, user)
        return render(
            request,
            "registration/registration_sent.html",
            {
                "email": email,
                "email_sent": None,
                "generic_resend_message": EMAIL_CONFIRMATION_PENDING_MESSAGE,
                **privacy_context(),
            },
        )

    return render(
        request,
        "registration/resend_confirmation.html",
        {"email": email, **privacy_context()},
    )


@require_http_methods(["GET"])
def email_confirmation_complete(request):
    return render(request, "registration/email_confirmation_complete.html")
