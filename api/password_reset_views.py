from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from .forms import SZLGPasswordResetForm


@method_decorator(ratelimit(key="ip", rate="10/h", method="POST", block=True), name="dispatch")
@method_decorator(ratelimit(key="post:email", rate="3/h", method="POST", block=True), name="dispatch")
class PasswordResetRequestView(auth_views.PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    form_class = SZLGPasswordResetForm
    success_url = reverse_lazy("password-reset-done")


class PasswordResetSentView(auth_views.PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


@method_decorator(ratelimit(key="ip", rate="20/h", method="POST", block=True), name="dispatch")
class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("password-reset-complete")


class PasswordResetFinishedView(auth_views.PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"
