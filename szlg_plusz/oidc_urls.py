"""Protocol endpoints of django-oauth-toolkit.

The bundled application/token management views are intentionally left out:
they would let any signed-in user register clients with arbitrary grant
types. Applications are managed through the SZLG+ dashboard instead.
"""

from oauth2_provider import urls as dot_urls

app_name = "oauth2_provider"

urlpatterns = (
    dot_urls.metadata_urlpatterns
    + dot_urls.base_urlpatterns
    + dot_urls.oidc_urlpatterns
)
