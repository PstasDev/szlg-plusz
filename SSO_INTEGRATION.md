# SZLG+ SSO integration (MVP)

SZLG+ is an OpenID Connect provider using OAuth 2.0 Authorization Code with
PKCE (`S256`). Client applications must be registered by an administrator;
dynamic client registration is not enabled. Do not collect SZLG+ passwords in
a client application.

## Provider setup

1. Install the pinned dependencies with `pip install -r requirements.txt`.
2. For local development, run:

   ```text
   python manage.py runserver
   ```

   SZLG+ binds by default to `127.0.0.1:8002`. Set `DEBUG=True`, allow
   `localhost` and `127.0.0.1` in `ALLOWED_HOSTS`, and set
   `WEBAUTHN_RP_ID=localhost` and
   `WEBAUTHN_ORIGINS=http://localhost:8002,http://127.0.0.1:8002`.
   The local client should use
   `http://localhost:8002/o/.well-known/openid-configuration`; development
   configuration does not redirect discovery to the deployed IdP. An
   explicitly supplied `runserver` address/port is respected.
3. Generate an RSA signing key on the provider host and protect it as a secret
   (run this before the first start; the settings refuse to load without it):

   ```text
   python scripts/generate_oidc_key.py
   ```

   The script writes `.secrets/oidc-private.pem` (or the path in
   `OIDC_RSA_PRIVATE_KEY_FILE`), refuses to overwrite an existing key unless
   `--force` is given, and needs only the project's Python dependencies. The
   equivalent OpenSSL command is
   `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out .secrets/oidc-private.pem`.

   Set `OIDC_RSA_PRIVATE_KEY_FILE` to that file. The private key is never
   published; SZLG+ exposes the public key through its JWKS endpoint.
   Generate a separate Django `SECRET_KEY` with
   `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`.
4. Configure `SECRET_KEY`, `ALLOWED_HOSTS`, `WEBAUTHN_RP_ID`,
   `WEBAUTHN_ORIGINS`, and the production HTTPS/cookie settings from
   `.env.example`. The deployed provider is `https://sso.szlg.info`.
   If TLS terminates at a reverse proxy, set `USE_X_FORWARDED_PROTO=True`
   only when the proxy overwrites the forwarded-protocol header.
5. Apply migrations and create an administrator:

   ```text
   python manage.py migrate
   python manage.py createsuperuser
   ```

6. In Django admin, add an OAuth application. Use **Authorization code** grant,
   **Public** client type for browser/mobile apps (or confidential for a server
   with a protected secret), the registered callback URI, and **RS256** for
   OIDC signing. Exact callback URI matching is required. PKCE is required by
   the provider.
7. Create `StudentProfile` / `TeacherProfile` rows and assign school groups (`ManualGroup`, shown as *iskolai csoport*) from the user
   admin screen. Django's built-in groups are shown as *jogosultsági kör* and only
   control access to this admin site; they are never sent to client applications.

This MVP uses a new `AUTH_USER_MODEL`. Install and migrate it before creating
real accounts. Replacing the user model in a database that has already applied
the old project migrations is not an in-place migration; plan a user-data
conversion or start with a fresh database.

## Provider metadata

For the deployed issuer at `https://sso.szlg.info/o`, use:

- Discovery: `https://sso.szlg.info/o/.well-known/openid-configuration`
- Authorization: `https://sso.szlg.info/o/authorize/`
- Token: `https://sso.szlg.info/o/token/`
- UserInfo: `https://sso.szlg.info/o/userinfo/`

For local development, use the equivalent endpoints on
`http://localhost:8002/o/` instead.

Use the `jwks_uri` published by discovery instead of copying the signing key.
The `groups` scope adds `smart_groups` (role booleans) and `manual_groups`
(hierarchical slug paths of the user's school groups) to the signed ID token. `openid`, `profile`, `email`,
and `phone` control their corresponding standard OIDC claims.

## Node.js / Express client outline

Register the exact Express callback URI, for example
`https://app.example.org/oidc/callback`. Use an OIDC client library (such as
`openid-client`) to handle discovery, state, nonce, PKCE, token exchange, and
signature validation:

1. Load the provider configuration from its OIDC discovery URL. Keep the client
   secret server-side for confidential clients; public clients do not have a
   secret.
2. For each login, generate a cryptographically random `state`, `nonce`, and
   PKCE verifier. Compute the `S256` challenge, then redirect the browser to
   the discovered `authorization_endpoint` with:

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

3. On the callback, require the returned `state` to match the value stored in
   the user's session. Exchange the code at the discovered `token_endpoint`,
   sending the exact `redirect_uri` and the original PKCE verifier. The OIDC
   library must validate the ID token's signature using the discovered JWKS,
   issuer, audience, expiry, and nonce before accepting the login.
4. Use validated ID-token claims such as `sub`, `email`, `smart_groups`, and
   `manual_groups`. Treat `sub` as the stable account identifier. Do not decode
   a JWT without validating its signature and claims.

The OAuth access token is opaque and intended for API/resource access; the
signed JWT is the OIDC ID token. Do not treat the ID token as an API access
token. Clients should request only the scopes they need and store tokens in
server-side sessions or a platform secure store.

Password and passkey endpoints are rate-limited. The default local cache is
process-local; configure a shared cache backend (for example Redis) before
running multiple application workers so rate limits are consistent across
workers.
