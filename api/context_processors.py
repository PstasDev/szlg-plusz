from .access import can_access_school_features
from .privacy import get_administrator_contacts


def school_access(request):
    return {
        "can_access_school_features": can_access_school_features(request.user),
    }


def administrator_contacts(request):
    return {"administrator_contacts": get_administrator_contacts()}
