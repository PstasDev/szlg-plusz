from datetime import datetime
from urllib.parse import urlsplit

from django.db.models import OuterRef, Subquery

from .models import (
    ApplicationProfile,
    ApplicationVerificationRequest,
    GlobalConfig,
    email_info,
)


def szlg_terms_url() -> str:
    config = GlobalConfig.objects.only("terms_of_service_url").first()
    return config.terms_of_service_url if config else ""


def verification_checked_at_subquery():
    return Subquery(
        ApplicationVerificationRequest.objects.filter(
            application_id=OuterRef("pk"),
            status=ApplicationVerificationRequest.Status.APPROVED,
        )
        .exclude(reviewed_at__isnull=True)
        .order_by("-reviewed_at")
        .values("reviewed_at")[:1]
    )


def application_verification_checked_at(application) -> datetime | None:
    if not application:
        return None
    return (
        ApplicationVerificationRequest.objects.filter(
            application_id=application.pk,
            status=ApplicationVerificationRequest.Status.APPROVED,
        )
        .exclude(reviewed_at__isnull=True)
        .order_by("-reviewed_at")
        .values_list("reviewed_at", flat=True)
        .first()
    )


def application_verification_snapshot(application, *, profile=None) -> dict:
    """Return public/security-relevant app details as they stood at submission."""
    if profile is None:
        profile = ApplicationProfile.objects.filter(
            application_id=application.pk
        ).first()

    return {
        "name": application.name,
        "client_type": application.client_type,
        "redirect_uris": application.redirect_uris,
        "owner_id": application.user_id,
        "developer": profile.developer if profile else "",
        "short_description": profile.short_description if profile else "",
        "launch_url": profile.launch_url if profile else "",
        "required_group_keys": list(profile.required_group_keys or []) if profile else [],
        "logo": profile.logo.name if profile and profile.logo else "",
        "privacy_contact_name": profile.privacy_contact_name if profile else "",
        "privacy_contact_email": profile.privacy_contact_email if profile else "",
        "privacy_policy_url": profile.privacy_policy_url if profile else "",
        "uses_szlg_privacy_policy": profile.uses_szlg_privacy_policy if profile else False,
        "szlg_privacy_policy_url": (
            "/adatvedelem/"
            if profile and profile.uses_szlg_privacy_policy
            else ""
        ),
        "terms_of_service_url": profile.terms_of_service_url if profile else "",
        "uses_szlg_terms_of_service": (
            profile.uses_szlg_terms_of_service if profile else False
        ),
        "szlg_terms_of_service_url": (
            szlg_terms_url()
            if profile and profile.uses_szlg_terms_of_service
            else ""
        ),
    }


def _is_https_url(value: str) -> bool:
    parsed = urlsplit(value or "")
    return parsed.scheme == "https" and bool(parsed.netloc)


def verification_missing_requirements(application) -> list[str]:
    """Explain which developer-provided details must be completed before review."""
    try:
        profile = application.profile
    except ApplicationProfile.DoesNotExist:
        return ["Az alkalmazás nyilvános profilja nincs kitöltve."]

    missing = []
    if not profile.developer.strip():
        missing.append("Add meg az alkalmazás fejlesztőjét.")
    if not profile.short_description.strip():
        missing.append("Adj meg egy rövid alkalmazásleírást.")
    if not profile.privacy_contact_email.strip():
        missing.append("Adj meg adatvédelmi kapcsolattartási e-mail-címet.")

    privacy_url = profile.privacy_policy_url.strip()
    if privacy_url and profile.uses_szlg_privacy_policy:
        missing.append(
            "Az adatkezelési tájékoztatónál válassz a saját URL és az SZLG+ tájékoztatója közül."
        )
    elif not privacy_url and not profile.uses_szlg_privacy_policy:
        missing.append(
            "Válaszd ki, melyik adatkezelési tájékoztató vonatkozik az alkalmazásra."
        )
    elif privacy_url and not _is_https_url(privacy_url):
        missing.append("A saját adatkezelési tájékoztató HTTPS-link legyen.")

    terms_url = profile.terms_of_service_url.strip()
    if terms_url and profile.uses_szlg_terms_of_service:
        missing.append(
            "Az ÁSZF-nél válassz a saját URL és az SZLG+ ÁSZF-je közül."
        )
    elif not terms_url and not profile.uses_szlg_terms_of_service:
        missing.append("Válaszd ki, melyik ÁSZF vonatkozik az alkalmazásra.")
    elif terms_url and not _is_https_url(terms_url):
        missing.append("A saját ÁSZF HTTPS-link legyen.")
    elif profile.uses_szlg_terms_of_service and not szlg_terms_url():
        missing.append(
            "Az SZLG+ ÁSZF-re csak akkor hivatkozhatsz, ha az adminisztrátor beállította a dokumentum URL-jét."
        )
    elif profile.uses_szlg_terms_of_service and not _is_https_url(szlg_terms_url()):
        missing.append(
            "Az SZLG+ ÁSZF adminisztrátor által beállított hivatkozása HTTPS-link legyen."
        )

    owner = application.user if application.user_id else None
    if owner is None:
        missing.append("Az alkalmazáshoz felelős tulajdonosi fiókot kell rendelni.")
    elif not email_info(owner.email).is_in_school_domain and not (
        (privacy_url or profile.uses_szlg_privacy_policy)
        and (terms_url or profile.uses_szlg_terms_of_service)
    ):
        missing.append(
            "Külsős fejlesztőként mindkét jogi tájékoztatóra meg kell adnod a vonatkozó dokumentumot vagy nyilatkozatot."
        )

    if not application.redirect_uris.split():
        missing.append("Legalább egy átirányítási URI szükséges.")

    return missing
