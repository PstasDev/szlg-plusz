from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.models import Application

from .access import can_access_school_features
from .directory import user_school_group_keys


class SZLGPlusOAuth2Validator(OAuth2Validator):
    oidc_claim_scope = {
        **OAuth2Validator.oidc_claim_scope,
        "smart_groups": "groups",
        "manual_groups": "groups",
        "school_groups": "groups",
        "application_required_groups": "groups",
        "application_group_access": "groups",
    }

    def get_additional_claims(self, request):
        user = request.user
        claims = {
            "sub": str(user.oidc_subject),
            "name": user.get_full_name() or user.email,
            "given_name": user.first_name,
            "family_name": user.last_name,
            "birthdate": (
                user.date_of_birth.isoformat() if user.date_of_birth else None
            ),
            "email": user.email,
            "email_verified": user.email_verified,
            "phone_number": user.phone or None,
        }
        if "groups" in getattr(request, "scopes", []):
            school_access = can_access_school_features(user)
            school_groups = user_school_group_keys(user) if school_access else []
            required_groups = []
            application_requires_groups = False
            client_id = getattr(request, "client_id", None)
            if client_id:
                application = Application.objects.filter(client_id=client_id).first()
                if application and hasattr(application, "profile"):
                    application_required_groups = (
                        application.profile.required_group_keys or []
                    )
                    application_requires_groups = bool(application_required_groups)
                    if school_access:
                        required_groups = application_required_groups
            claims.update(
                {
                    "smart_groups": (
                        user.smart_groups
                        if school_access
                        else {key: False for key in user.smart_groups}
                    ),
                    "manual_groups": sorted(
                        {
                            ancestor.full_path
                            for group in user.manual_groups.all()
                            for ancestor in group.get_ancestors(include_self=True)
                        }
                    ) if school_access else [],
                    "school_groups": school_groups,
                    "application_required_groups": required_groups,
                    "application_group_access": (
                        (
                            not required_groups
                            or bool(set(required_groups).intersection(school_groups))
                        )
                        if school_access
                        else not application_requires_groups
                    ),
                }
            )
        return {key: value for key, value in claims.items() if value is not None}
