from oauth2_provider.oauth2_validators import OAuth2Validator


class SZLGPlusOAuth2Validator(OAuth2Validator):
    oidc_claim_scope = {
        **OAuth2Validator.oidc_claim_scope,
        "smart_groups": "groups",
        "manual_groups": "groups",
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
            "smart_groups": user.smart_groups,
            "manual_groups": sorted(
                {
                    ancestor.full_path
                    for group in user.manual_groups.all()
                    for ancestor in group.get_ancestors(include_self=True)
                }
            ),
        }
        return {key: value for key, value in claims.items() if value is not None}
