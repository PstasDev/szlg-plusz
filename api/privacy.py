from .models import GlobalConfig, get_school_domain


def privacy_context() -> dict:
    """Template data shared by the privacy notice and account-entry pages."""
    contacts = GlobalConfig.get_solo().administrator_contacts.filter(
        is_active=True
    ).order_by("last_name", "first_name", "email")
    return {
        "administrator_contacts": contacts,
        "school_domain": get_school_domain(),
    }
