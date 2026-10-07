"""Hungarian, user-facing explanations of the OAuth/OIDC scopes SZLG+ offers."""

SCOPE_DETAILS = {
    "openid": {
        "title": "Személyazonosítás",
        "description": (
            "Az alkalmazás megtudja, hogy ki jelentkezett be, egy SZLG+-os egyedi "
            "azonosító alapján. A jelszavadat soha nem kapja meg."
        ),
        "icon": "fingerprint",
    },
    "profile": {
        "title": "Alapadatok",
        "description": "A neved (vezeték- és keresztnév) és a születési dátumod.",
        "icon": "user",
    },
    "email": {
        "title": "E-mail-cím",
        "description": "Az e-mail-címed, és hogy az meg van-e erősítve.",
        "icon": "mail",
    },
    "phone": {
        "title": "Telefonszám",
        "description": "A fiókodhoz megadott telefonszámod.",
        "icon": "phone",
    },
    "groups": {
        "title": "Szerepkör és iskolai csoportok",
        "description": (
            "Hogy diák vagy tanár vagy-e, és mely iskolai csoportokhoz (például osztály "
            "vagy szakkör) tartozol."
        ),
        "icon": "users",
    },
}

SCOPE_SHORT_DESCRIPTIONS = {
    scope: f"{details['title']}: {details['description']}"
    for scope, details in SCOPE_DETAILS.items()
}


def describe_scopes(scopes):
    """Return display details for the requested scopes, ignoring unknown ones' text."""
    described = []
    for scope in scopes:
        details = SCOPE_DETAILS.get(scope)
        if details is None:
            details = {
                "title": scope,
                "description": "Az alkalmazás ehhez a speciális adathoz is hozzáfér.",
                "icon": "key",
            }
        described.append({"scope": scope, **details})
    return described
