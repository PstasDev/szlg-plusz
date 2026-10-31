from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_html_email(
    subject,
    text_body,
    from_email,
    recipient_list,
    *,
    template_name=None,
    context=None,
    html_body=None,
    fail_silently=False,
):
    """Send an email with a designed HTML version and a text fallback."""
    if html_body is None:
        html_body = render_to_string(template_name, context or {})
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=recipient_list,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=fail_silently)
