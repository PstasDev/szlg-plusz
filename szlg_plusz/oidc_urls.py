"""Protocol endpoints of django-oauth-toolkit.

The bundled application/token management views are intentionally left out:
they would let any signed-in user register clients with arbitrary grant
types. Applications are managed through the SZLG+ dashboard instead.
"""

import logging

from django.urls import path
from oauth2_provider import urls as dot_urls
from oauth2_provider.models import get_application_model
from oauth2_provider.views import AuthorizationView

from api.scopes import describe_scopes

logger = logging.getLogger(__name__)

app_name = "oauth2_provider"


class SZLGAuthorizationView(AuthorizationView):
    """Keeps the application in the consent page when an approval POST is re-rendered.

    The toolkit only puts the application and scopes into the template context
    on GET. When the submitted approval form is invalid, the page is rendered
    again without them, so the app details and the "verified" state vanish.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        if context.get("application") is None:
            client_id = data.get("client_id")
            context["application"] = (
                get_application_model()
                .objects.select_related("profile")
                .filter(client_id=client_id)
                .first()
                if client_id
                else None
            )
        if not context.get("scopes"):
            context["scopes"] = data.get("scope", "").split()
        context["scope_items"] = describe_scopes(context["scopes"])
        return context

    def error_response(self, error, application, **kwargs):
        # Fatal errors (unknown client, mismatching redirect URI, ...) render a 400 page.
        oauth_error = error.oauthlib_error
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        logger.warning(
            "Authorization request rejected: %s (%s) client_id=%s redirect_uri=%s",
            oauth_error.error,
            oauth_error.description,
            data.get("client_id"),
            data.get("redirect_uri"),
        )
        return super().error_response(error, application, **kwargs)

    def form_invalid(self, form):
        # Field names only: the values include one-time codes and state.
        logger.warning(
            "Authorization approval rejected, invalid fields: %s",
            {name: [error.code for error in errors.data] for name, errors in form.errors.items()},
        )
        return super().form_invalid(form)


urlpatterns = (
    dot_urls.metadata_urlpatterns
    + [path("authorize/", SZLGAuthorizationView.as_view(), name="authorize")]
    + [pattern for pattern in dot_urls.base_urlpatterns if pattern.name != "authorize"]
    + dot_urls.oidc_urlpatterns
)