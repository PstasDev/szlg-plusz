from .access import can_access_school_features
from .models import GlobalConfig


def school_access(request):
    return {
        "can_access_school_features": can_access_school_features(request.user),
    }


def administrator_contacts(request):
    config = GlobalConfig.get_solo()
    return {
        "administrator_contacts": config.administrator_contacts.filter(
            is_active=True
        ).order_by("last_name", "first_name", "email"),
        "szlg_terms_url": config.terms_of_service_url,
    }
