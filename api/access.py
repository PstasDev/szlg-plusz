from .models import email_info


def can_access_school_features(user) -> bool:
    """Whether an account may use school-wide directory and information pages."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    return email_info(getattr(user, "email", "")).is_in_school_domain
