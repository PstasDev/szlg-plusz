"""Protocol endpoints of django-oauth-toolkit.

The bundled application/token management views are intentionally left out:
they would let any signed-in user register clients with arbitrary grant
types. Applications are managed through the SZLG+ dashboard instead.
"""

import copy
import json
import logging
import secrets
from urllib.parse import urlencode

from django.core import signing
from django.http import HttpResponseBadRequest
from django.urls import path
from django.utils import timezone
from oauth2_provider import urls as dot_urls
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import get_application_model
from oauth2_provider.oauth2_validators import is_valid_resource_uri
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import AuthorizationView

from api.application_verification import application_verification_checked_at
from api.models import ApplicationProfile, UserAppConnection
from api.scopes import describe_scopes

logger = logging.getLogger(__name__)
CONFIRMATION_SALT = "szlg.oauth.confirmation"
CONFIRMATION_MAX_AGE = 5 * 60
CONFIRMATION_SESSION_KEY = "oauth_confirmation_tickets"
AUTHORIZATION_FORM_FIELDS = (
    "redirect_uri",
    "scope",
    "nonce",
    "client_id",
    "state",
    "response_type",
    "code_challenge",
    "code_challenge_method",
    "claims",
    "resource",
)

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
        application = context.get("application")
        if application is not None:
            try:
                if application.profile.verified:
                    application.verification_checked_at = (
                        application_verification_checked_at(application)
                    )
            except ApplicationProfile.DoesNotExist:
                pass
        return context

    @staticmethod
    def _form_values(values):
        return {field: values.get(field) or "" for field in AUTHORIZATION_FORM_FIELDS}

    def _authorization_context(self, application, scopes, credentials, resource_values):
        """Build the same form/context as DOT's GET handler for custom screens."""
        context = {
            "scopes_descriptions": [
                get_scopes_backend().get_all_scopes()[scope] for scope in scopes
            ],
            "scopes": scopes,
            "application": application,
            "client_id": credentials["client_id"],
            "redirect_uri": credentials["redirect_uri"],
            "response_type": credentials["response_type"],
            "state": credentials.get("state"),
        }
        for field in ("code_challenge", "code_challenge_method", "nonce"):
            if field in credentials:
                context[field] = credentials[field]
        if "claims" in credentials:
            context["claims"] = json.dumps(credentials["claims"])
        if resource_values:
            context["resource"] = " ".join(resource_values)

        self.oauth2_data = context
        form = self.get_form(self.get_form_class())
        context["form"] = form
        return self.get_context_data(**context)

    def _confirmation_ticket(self, connection, form_values):
        nonce = secrets.token_urlsafe(24)
        outstanding = self.request.session.get(CONFIRMATION_SESSION_KEY, {})
        outstanding = outstanding if isinstance(outstanding, dict) else {}
        while len(outstanding) >= 10:
            outstanding.pop(next(iter(outstanding)))
        outstanding[nonce] = True
        self.request.session[CONFIRMATION_SESSION_KEY] = outstanding
        return signing.dumps(
            {
                "nonce": nonce,
                "user_id": str(self.request.user.pk),
                "connection_id": connection.pk,
                "application_id": connection.application_id,
                "form": self._form_values(form_values),
            },
            salt=CONFIRMATION_SALT,
            compress=True,
        )

    def _ticket_is_valid(self, ticket, connection, form):
        if not ticket or connection is None:
            return False
        try:
            payload = signing.loads(
                ticket,
                salt=CONFIRMATION_SALT,
                max_age=CONFIRMATION_MAX_AGE,
            )
        except signing.BadSignature:
            return False
        form_values = self._form_values(form.cleaned_data)
        expected = {
            "user_id": str(self.request.user.pk),
            "connection_id": connection.pk,
            "application_id": connection.application_id,
            "form": form_values,
        }
        nonce = payload.get("nonce") if isinstance(payload, dict) else None
        if (
            not isinstance(nonce, str)
            or {key: value for key, value in payload.items() if key != "nonce"} != expected
        ):
            return False
        outstanding = self.request.session.get(CONFIRMATION_SESSION_KEY, {})
        if not isinstance(outstanding, dict) or nonce not in outstanding:
            return False
        outstanding.pop(nonce)
        if outstanding:
            self.request.session[CONFIRMATION_SESSION_KEY] = outstanding
        else:
            self.request.session.pop(CONFIRMATION_SESSION_KEY, None)
        return True

    def _render_authorization_page(
        self, application, scopes, credentials, resource_values, *, template_name
    ):
        context = self._authorization_context(application, scopes, credentials, resource_values)
        return self._render_with_template(self.get_context_data(**context), template_name)

    def _render_with_template(self, context, template_name):
        original_template = self.template_name
        self.template_name = template_name
        try:
            return self.render_to_response(context)
        finally:
            self.template_name = original_template

    @staticmethod
    def _without_silent_prompt(request):
        """Remove prompt=none only from OAuthLib's internal validation pass.

        The view's login mixin has already authenticated this session; the
        durable-consent check runs before issuing any response. oauthlib's
        default silent-login validator cannot inspect Django's session user.
        All other authorization parameters remain unchanged.
        """
        request_copy = copy.copy(request)
        request_copy.META = request.META.copy()
        query = request.GET.copy()
        query.pop("prompt", None)
        request_copy.GET = query
        request_copy.META["QUERY_STRING"] = query.urlencode()
        return request_copy

    def _approved_response(self, application, scopes, credentials, *, request=None):
        try:
            uri, _headers, _body, _status = self.create_authorization_response(
                request=request or self.request,
                scopes=" ".join(scopes),
                credentials=credentials,
                allow=True,
            )
        except OAuthToolkitError as error:
            return self.error_response(error, application)
        UserAppConnection.objects.filter(
            user=self.request.user, application=application
        ).update(last_used_at=timezone.now())
        return self.redirect(uri, application)

    def _prompt_error(self, application, credentials, error):
        redirect_uri = credentials["redirect_uri"]
        params = {"error": error}
        if credentials.get("state"):
            params["state"] = credentials["state"]
        if oauth2_settings.COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS:
            params["iss"] = oauth2_settings.oauth2_authorization_server_issuer(self.request)
        separator = "&" if "?" in redirect_uri else "?"
        return self.redirect(f"{redirect_uri}{separator}{urlencode(params)}", application)

    def get(self, request, *args, **kwargs):
        prompt = set(request.GET.get("prompt", "").split())
        # Keep DOT's standard handling for reauthentication and account creation.
        if prompt & {"login", "create"}:
            return super().get(request, *args, **kwargs)

        validation_request = (
            self._without_silent_prompt(request) if prompt == {"none"} else request
        )
        try:
            scopes, credentials = self.validate_authorization_request(validation_request)
        except OAuthToolkitError as error:
            return self.error_response(error, application=None)

        application = (
            get_application_model()
            .objects.select_related("profile")
            .get(client_id=credentials["client_id"])
        )
        resource_values = request.GET.getlist("resource")
        # Match DOT's resource-indicator handling. Let its normal error page
        # produce the response for malformed resource URIs.
        if any(not is_valid_resource_uri(value) for value in resource_values):
            return super().get(request, *args, **kwargs)
        if resource_values:
            credentials["resource"] = resource_values

        if "consent" in prompt:
            return self._render_authorization_page(
                application,
                scopes,
                credentials,
                resource_values,
                template_name=self.template_name,
            )
        if (
            request.GET.get("approval_prompt") == "force"
            and "none" not in prompt
        ):
            return self._render_authorization_page(
                application,
                scopes,
                credentials,
                resource_values,
                template_name=self.template_name,
            )

        if application.skip_authorization:
            return self._approved_response(
                application,
                scopes,
                credentials,
                request=validation_request if prompt == {"none"} else None,
            )

        connection = UserAppConnection.objects.filter(
            user=request.user, application=application
        ).first()
        approved_scopes = (
            set(connection.scopes)
            if connection and isinstance(connection.scopes, list)
            else set()
        )
        consent_covers_request = connection is not None and set(scopes).issubset(approved_scopes)

        if consent_covers_request:
            if connection.interaction_mode == UserAppConnection.InteractionMode.AUTOMATIC:
                return self._approved_response(
                    application,
                    scopes,
                    credentials,
                    request=validation_request if prompt == {"none"} else None,
                )
            if "none" in prompt:
                return self._prompt_error(application, credentials, "interaction_required")

            context = self._authorization_context(
                application, scopes, credentials, resource_values
            )
            form = context["form"]
            context.update(
                {
                    "interaction_ticket": self._confirmation_ticket(
                        connection, form.initial
                    ),
                    "next_url": request.get_full_path(),
                }
            )
            return self._render_with_template(
                self.get_context_data(**context), "oauth2_provider/confirm.html"
            )

        if "none" in prompt:
            return self._prompt_error(application, credentials, "consent_required")
        # Always require a fresh, explicit consent when there is no durable
        # connection (or when this request adds scopes). DOT's legacy
        # approval_prompt=auto only consults non-expired access tokens and is
        # intentionally not used as the source of durable consent here.
        return self._render_authorization_page(
            application,
            scopes,
            credentials,
            resource_values,
            template_name=self.template_name,
        )

    def form_valid(self, form):
        application = get_application_model().objects.get(
            client_id=form.cleaned_data["client_id"]
        )
        requested_scopes = set(form.cleaned_data.get("scope", "").split())
        connection = UserAppConnection.objects.filter(
            user=self.request.user, application=application
        ).first()
        if form.cleaned_data.get("allow") and self.request.POST.get("interaction_ticket"):
            if not self._ticket_is_valid(
                self.request.POST.get("interaction_ticket"), connection, form
            ):
                return HttpResponseBadRequest("Érvénytelen vagy lejárt megerősítési kérés.")

        response = super().form_valid(form)
        if (
            form.cleaned_data.get("allow")
            and response.status_code in (302, 303)
            and self.request.user.is_authenticated
        ):
            connection, created = UserAppConnection.objects.get_or_create(
                user=self.request.user,
                application=application,
                defaults={"scopes": sorted(requested_scopes)},
            )
            if not created:
                prior_scopes = (
                    connection.scopes if isinstance(connection.scopes, list) else []
                )
                connection.scopes = sorted(set(prior_scopes) | requested_scopes)
                connection.save(update_fields=["scopes"])
            UserAppConnection.objects.filter(pk=connection.pk).update(
                last_used_at=timezone.now()
            )
        return response

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
