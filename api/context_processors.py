from .access import can_access_school_features


def school_access(request):
    return {
        "can_access_school_features": can_access_school_features(request.user),
    }
