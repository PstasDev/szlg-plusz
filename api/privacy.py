from .models import GlobalConfig, get_school_domain


def get_administrator_contacts():
    return GlobalConfig.get_solo().administrator_contacts.filter(
        is_active=True
    ).order_by("last_name", "first_name", "email")


def privacy_context() -> dict:
    """Template data shared by the privacy notice and account-entry pages."""
    return {
        "administrator_contacts": get_administrator_contacts(),
        "school_domain": get_school_domain(),
    }
