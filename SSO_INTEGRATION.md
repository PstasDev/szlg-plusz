# SZLG+ application integration guide

This guide is for developers integrating an application with the SZLG+ OpenID
Connect provider. SZLG+ performs authentication; your application must not ask
for or store a user's SZLG+ password.

## 1. Register a client

Sign in to SZLG+, open **Alkalmazásaim** (My applications), and register an
application. Registration is self-service; it does not mean that the school has
verified the application. Ask an SZLG+ administrator to verify it if needed.

Provide the public application name, a short description, developer name, and
the exact callback URI(s) used by your OIDC client. Callback URI matching is
exact. Production redirect URIs must use HTTPS.

Choose the client type according to where the code runs:

- **Public**: browser-based or native mobile clients. There is no client secret;
  PKCE is mandatory.
- **Confidential**: a server-side client that can keep its secret private. The
  secret is shown only when created or rotated. Store it in a server-side secret
  store, never in browser code or a mobile app. Rotating it immediately
  invalidates the previous secret.

The SZLG+ self-service registration flow configures Authorization Code,
RS256 ID-token signing, and required PKCE with `S256`; these are not selectable
per-client settings in that flow. Dynamic client registration is not available.
A standard user account may register up to ten applications; staff accounts
are not subject to this limit.

## 2. Discover the provider configuration

Use OIDC discovery instead of hard-coding endpoints or copying signing keys.
The dashboard's application detail page displays the discovery URL for the
current environment.

Production:

```text
https://sso.szlg.info/o/.well-known/openid-configuration
```

Local SZLG+ development:

```text
http://localhost:8002/o/.well-known/openid-configuration
```

For production, the issuer is `https://sso.szlg.info/o`. The discovery
document's `issuer` must match the ID token's `iss` claim. Read `jwks_uri` from
discovery to obtain public signing keys; the provider's private RSA key is
never shared with clients.

The protocol endpoints currently include:

| Purpose | Production endpoint |
| --- | --- |
| Authorization | `https://sso.szlg.info/o/authorize/` |
| Token | `https://sso.szlg.info/o/token/` |
| UserInfo | `https://sso.szlg.info/o/userinfo/` |

Prefer the endpoint URLs published by discovery, which remain the source of
truth if deployment paths change.

## 3. Use Authorization Code + PKCE

Use a maintained OIDC client library for your language and framework. It should
generate and validate `state`, `nonce`, and PKCE values, exchange the code, and
validate tokens. For each sign-in, the high-level sequence is:

1. Generate cryptographically random `state`, `nonce`, and a PKCE verifier;
   compute the challenge using `S256`. Keep the state and verifier bound to the
   user's browser session.
2. Redirect to the discovered `authorization_endpoint` with `response_type=code`,
   the registered `client_id` and exact `redirect_uri`, requested scopes,
   `state`, `nonce`, `code_challenge`, and `code_challenge_method=S256`.
3. On callback, reject a missing or mismatched `state`. Exchange the code at the
   discovered `token_endpoint`, sending the same `redirect_uri` and original
   PKCE verifier. Confidential clients authenticate with their server-held
   client credentials as required by the library.
4. Validate the ID token signature against the discovered JWKS and validate
   `iss`, `aud`, expiry, and `nonce` before using any claim.
5. Create your application's own session using the validated identity. Keep
   tokens in a server-side session or platform secure storage; do not expose
   confidential-client secrets or long-lived credentials to the browser.

Example authorization parameters (illustrative; let your OIDC library construct
the actual request):

```text
response_type=code
client_id=<registered-client-id>
redirect_uri=https://app.example.org/oidc/callback
scope=openid profile email groups
state=<random-state>
nonce=<random-nonce>
code_challenge=<S256-challenge>
code_challenge_method=S256
```

Never accept an ID token by merely decoding its JWT payload. Never use the ID
token as an API access token.

## 4. Request only the claims you need

`openid` is required for OIDC sign-in. Other scopes control which claims are
released after the user approves the request:

| Scope | Claims/data |
| --- | --- |
| `profile` | `name`, `given_name`, `family_name`, `birthdate` |
| `email` | `email`, `email_verified` |
| `phone` | `phone_number` |
| `groups` | `smart_groups`, `manual_groups`, `school_groups`, `application_required_groups`, `application_group_access` |

The ID token's `sub` is a stable SZLG+ subject identifier. Use it as the
account key in your application; do not use an e-mail address as a permanent
identifier. An account may have no optional profile value, so handle absent
claims.

Claim values below are JSON types. Optional claims with no value are omitted,
not returned as `null`; empty strings, `false`, and empty arrays are distinct
values and should not be treated as missing.

| Claim | JSON type | Scope / behavior |
| --- | --- | --- |
| `iss` | string (URL) | ID-token issuer; must equal discovery `issuer`. |
| `aud` | string or array of strings | ID-token audience; the registered client ID must be present. |
| `iat`, `exp` | integer | ID-token issued-at and expiry Unix timestamps, in seconds. Validate expiry. |
| `nonce` | string | Present when sent in the authorization request; the OIDC client must validate it. |
| `sub` | string (UUID) | `openid`; stable SZLG+ identifier. Store it without interpreting its UUID format. |
| `name` | string | `profile`; full name, falling back to the account e-mail if no name is set. |
| `given_name`, `family_name` | string | `profile`; first and last name. Either may be an empty string. |
| `birthdate` | string (`YYYY-MM-DD`) | `profile`; omitted if no birth date is set. |
| `email` | string | `email`; the account e-mail address. |
| `email_verified` | boolean | `email`; `false` is a real value, not a missing claim. |
| `phone_number` | string | `phone`; omitted if the phone field is blank. |
| `smart_groups` | object with boolean values | `groups`; the seven calculated flags listed below. All keys are returned, including flags set to `false`. |
| `manual_groups` | array of strings | `groups`; sorted, unique hierarchical paths made from manually managed group slugs. No memberships means `[]`. |
| `school_groups` | array of strings | `groups`; stable directory group keys, including manual, smart, tagozat, szekció, class, and school-role groups. |
| `application_required_groups` | array of strings | `groups`; group keys configured for this application by its owner. |
| `application_group_access` | boolean | `groups`; true if no group requirement is configured or the user belongs to at least one configured group. The application must enforce this result. |

The `smart_groups` object currently has these keys:

| Key | Meaning |
| --- | --- |
| `student` | True if a student profile exists, or if the school-domain e-mail local part ends in a student suffix such as `.23a` or `.2023a`. |
| `teacher` | True if the account has a `TeacherProfile`. |
| `staff` | The Django `is_staff` flag on SZLG+; this does not grant privileges in your application. |
| `part_time_student` | True if a part-time-student profile exists, or if the local part ends in a suffix such as `.23af` or `.2023af`. |
| `computer_test_account` | True for a school-domain e-mail starting `x.` when its final local-part segment contains a digit. |
| `group_email` | True only when an SZLG+ administrator explicitly marks the account as a group mailbox. |
| `teacher_or_school_employee` | Calculated from a school-domain name-style local part; a teacher profile separately sets `teacher`. |

For example, assigning a user to the `betanulok` child group under `studiosok`
can produce `manual_groups: ["studiosok", "studiosok/betanulok"]`. Group names
may change; the slug path is the integration value. Smart groups are calculated
descriptive flags, not an exclusive role enum or an authorization system. Do
not grant access based on them without defining and maintaining your own
authorization policy. The `staff` smart flag is descriptive only and is not a
directory group. Django admin permission groups are never sent to clients or
linked to school-group membership.

Manual group membership is managed by group managers; users cannot join or
leave a group themselves. The directory also calculates membership from student
profiles, class assignments, tagozat, szekció, and institutional roles.
`school_groups` uses stable identifiers rather than display names: manual keys
use `manual-<group-slug>`, class keys include the starting year and section (for
example `osztaly-2023-f-diakok`), and role keys use the role slug. Store these
keys exactly as returned; do not derive them from translated labels.
Application owners can select group keys on their application's registration
or edit page. If one or more keys are selected, at least one matching
membership makes `application_group_access` true. The provider reports this
claim but does not enforce authorization inside the client application: the app
must reject access when the claim is false.

Example group claims:

```json
{
  "smart_groups": {
    "student": true,
    "teacher": false,
    "staff": false,
    "part_time_student": false,
    "computer_test_account": false,
    "group_email": false,
    "teacher_or_school_employee": false
  },
  "manual_groups": ["studiosok", "studiosok/betanulok"],
  "school_groups": ["manual-studiosok", "osztaly-2023-f-diakok", "smart-student"],
  "application_required_groups": ["osztaly-2023-f-diakok"],
  "application_group_access": true
}
```

The access token is opaque and is for resource access; the signed JWT is the ID
token. Access and ID tokens currently expire after one hour. Follow the
discovery metadata and your OIDC library's token handling rather than assuming
that the access token is a JWT.

## 5. Django server-side integration (Authlib)

This minimal example uses a Django session to remember the validated SZLG+
identity. It does not create a Django `User` or make `request.user` authenticated;
see the account-mapping note below if your application needs Django's built-in
authentication framework.

### Step 1: Register the Django callback

In **Alkalmazásaim**, register a **confidential** client and an exact HTTPS
callback, for example `https://app.example.org/auth/oidc/callback/`. Copy the
client ID and secret. Keep the secret in environment variables or a secret
manager, never in source control. Use separate registrations for development
and production.

### Step 2: Install Authlib

If you are starting a new project (skip `startproject` / `startapp` if you
already have a Django app):

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install Django Authlib
django-admin startproject config .
python manage.py startapp app
python manage.py migrate
```

For an existing project, install Authlib into its active virtual environment
with `python -m pip install Authlib`. Pin the Django and Authlib versions you
tested in the project's dependency lock file. Django must have
`django.contrib.sessions`, `SessionMiddleware`, and CSRF protection enabled (the
standard Django project defaults).

### Step 3: Configure environment and Django settings

Set these values using your local shell or deployment secret manager:

```bash
export SZLG_OIDC_CLIENT_ID='registered-client-id'
export SZLG_OIDC_CLIENT_SECRET='server-side-client-secret'
export SZLG_OIDC_DISCOVERY_URL='https://sso.szlg.info/o/.well-known/openid-configuration'
```

In `settings.py`:

```python
import os

SZLG_OIDC_CLIENT_ID = os.environ["SZLG_OIDC_CLIENT_ID"]
SZLG_OIDC_CLIENT_SECRET = os.environ["SZLG_OIDC_CLIENT_SECRET"]
SZLG_OIDC_DISCOVERY_URL = os.environ.get(
    "SZLG_OIDC_DISCOVERY_URL",
    "https://sso.szlg.info/o/.well-known/openid-configuration",
)
```

Do not put real credentials in a committed `.env` file. Use HTTPS and secure
session cookies in production (`SESSION_COOKIE_SECURE = True`).

### Step 4: Register the OIDC client

Create `app/oidc_client.py`:

```python
from authlib.integrations.django_client import OAuth
from django.conf import settings

oauth = OAuth()
oauth.register(
    name="szlg",
    client_id=settings.SZLG_OIDC_CLIENT_ID,
    client_secret=settings.SZLG_OIDC_CLIENT_SECRET,
    server_metadata_url=settings.SZLG_OIDC_DISCOVERY_URL,
    client_kwargs={
        # Add "groups" only if the application needs school-group data.
        "scope": "openid profile email",
        "code_challenge_method": "S256",
    },
)
```

Authlib reads authorization, token, UserInfo, and JWKS endpoints from discovery.
Do not hard-code endpoints or signing keys. To receive the group claims, add
`groups` to the requested scope; `phone` can be requested separately when
needed.

### Step 5: Add login and callback views

In `app/views.py`:

```python
from authlib.integrations.base_client.errors import OAuthError
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET

from .oidc_client import oauth


@require_GET
def oidc_login(request):
    callback = request.build_absolute_uri(reverse("oidc_callback"))
    return oauth.szlg.authorize_redirect(request, callback)


@require_GET
def oidc_callback(request):
    # The OIDC client handles state/nonce, PKCE, token exchange, and validation.
    try:
        token = oauth.szlg.authorize_access_token(request)
    except OAuthError:
        return HttpResponseBadRequest("SZLG+ sign-in could not be completed")
    userinfo = token.get("userinfo")
    if not userinfo or not userinfo.get("sub"):
        return HttpResponseBadRequest("Missing OIDC subject")

    request.session.cycle_key()
    request.session["szlg_identity"] = {
        "sub": str(userinfo["sub"]),
        "name": userinfo.get("name"),
        "email": userinfo.get("email"),
        "smart_groups": dict(userinfo.get("smart_groups", {})),
        "manual_groups": list(userinfo.get("manual_groups", [])),
        "school_groups": list(userinfo.get("school_groups", [])),
        "application_required_groups": list(userinfo.get("application_required_groups", [])),
        "application_group_access": userinfo.get("application_group_access"),
    }
    return redirect("home")  # Replace with a URL name that exists in your project.
```

The application session stores only selected claims. Omit the group fields if
the app does not request `groups`. For a real Django login, look up or create
your local user by the unique `sub` value and then call Django's `login(request,
user)`; never automatically link an existing account by e-mail alone. Handle
OAuth errors without creating a session, and do not log tokens, authorization
codes, state, nonce, or client secrets.

### Step 6: Wire the URLs and test

In `app/urls.py`:

```python
from django.urls import path
from . import views

urlpatterns = [
    path("auth/oidc/login/", views.oidc_login, name="oidc_login"),
    path("auth/oidc/callback/", views.oidc_callback, name="oidc_callback"),
]
```

Include `app.urls` in the project URL configuration and link your sign-in button
to `oidc_login`. Confirm that the generated callback URL exactly matches the
client registration, complete a login and consent, and verify that the session
contains a `sub`. Also test a rejected/mismatched `state`, wrong redirect URI,
and denied consent; none should establish an application login. A local HTTP
callback works only with a local SZLG+ development provider configured for it;
use HTTPS for production and normal provider testing.

## Consent, revocation, and account selection

SZLG+ shows the application name, developer, description, verification status,
and requested scopes on the consent page. Existing consent can be configured
by the user for automatic redirect or for confirmation/account selection on
each sign-in. A newly requested scope requires fresh consent.

Users can revoke an application's SZLG+ access from their account dashboard.
Revocation stops future SZLG+ authorization and invalidates the provider-side
tokens, but it does not terminate a session already created inside your
application. Provide your own sign-out and session-expiry behavior.

## Local testing

The local provider uses `http://localhost:8002` by default. In local SZLG+
development only, `DEBUG=True` permits HTTP redirect URIs; WebAuthn still
requires the configured relying-party ID and origins to match the local host.
Use a separate test registration and configuration from production. Do not
point production clients at the local issuer or disable token validation to
make a test pass.

For provider setup, operations, or contributing to SZLG+ itself, see the
**SZLG+ fejlesztőknek** section in the site's documentation.
