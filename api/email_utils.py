from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


def send_otp_email(user, otp_code, subject_override=None):
    """
    Send OTP email to user for password reset.
    
    Args:
        user: Django User object
        otp_code: 6-digit OTP code string
        subject_override: Optional custom subject line (overrides default)
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        logger.debug(f"[EMAIL DEBUG] Attempting to send OTP email to {user.email}")
        logger.debug(f"[EMAIL DEBUG] Email backend: {settings.EMAIL_BACKEND}")
        logger.debug(f"[EMAIL DEBUG] Email host: {settings.EMAIL_HOST}")
        logger.debug(f"[EMAIL DEBUG] Email port: {settings.EMAIL_PORT}")
        logger.debug(f"[EMAIL DEBUG] Email use TLS: {settings.EMAIL_USE_TLS}")
        logger.debug(f"[EMAIL DEBUG] From email: {settings.DEFAULT_FROM_EMAIL}")
        
        subject = subject_override if subject_override else '[SZLG Igazoláskezelő] Elfelejtett jelszó'
        
        # Render HTML email template
        html_message = render_to_string('emails/otp_reset_password.html', {
            'user': user,
            'otp_code': otp_code[:3] + '-' + otp_code[3:],
            'current_year': timezone.now().year,
            'timestamp': timezone.now(),
        })
        
        logger.debug(f"[EMAIL DEBUG] Email template rendered successfully")
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        # Send email
        logger.debug(f"[EMAIL DEBUG] Sending email with subject: {subject}")
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"✓ [EMAIL SUCCESS] OTP email sent successfully to {user.email}")
        logger.debug(f"[EMAIL DEBUG] Email delivery completed without errors")
        return True
        
    except Exception as e:
        logger.error(f"✗ [EMAIL FAILED] Failed to send OTP email to {user.email}: {str(e)}")
        logger.error(f"[EMAIL ERROR] Exception type: {type(e).__name__}")
        logger.error(f"[EMAIL ERROR] Exception details: {str(e)}")
        return False


def send_password_changed_notification(user, subject_override=None):
    """
    Send notification email when password is successfully changed.
    
    Args:
        user: Django User object
        subject_override: Optional custom subject line (overrides default)
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        logger.debug(f"[EMAIL DEBUG] Attempting to send password change notification to {user.email}")
        logger.debug(f"[EMAIL DEBUG] Email backend: {settings.EMAIL_BACKEND}")
        logger.debug(f"[EMAIL DEBUG] From email: {settings.DEFAULT_FROM_EMAIL}")
        
        subject = subject_override if subject_override else '[SZLG Igazoláskezelő] Jelszó sikeresen megváltoztatva'
        
        # Render HTML email template
        html_message = render_to_string('emails/password_changed.html', {
            'user': user,
            'current_year': timezone.now().year,
            'timestamp': timezone.now(),
        })
        
        logger.debug(f"[EMAIL DEBUG] Email template rendered successfully")
        
        # Create plain text version
        plain_message = strip_tags(html_message)
        
        logger.debug(f"[EMAIL DEBUG] Sending notification with subject: {subject}")
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"✓ [EMAIL SUCCESS] Password change notification sent to {user.email}")
        logger.debug(f"[EMAIL DEBUG] Email delivery completed without errors")
        return True
        
    except Exception as e:
        logger.error(f"✗ [EMAIL FAILED] Failed to send password change notification to {user.email}: {str(e)}")
        logger.error(f"[EMAIL ERROR] Exception type: {type(e).__name__}")
        logger.error(f"[EMAIL ERROR] Exception details: {str(e)}")
        return False


def send_password_generated_email(user, password, subject_override=None):
    """
    Send email with newly generated password.
    
    Args:
        user: Django User object
        password: The generated password (plaintext)
        subject_override: Optional custom subject line (overrides default)
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        logger.debug(f"[EMAIL DEBUG] Attempting to send generated password to {user.email}")
        
        subject = subject_override if subject_override else '[SZLG Igazoláskezelő] A jelszavát visszaállították'
        
        message = f"""
Kedves {user.get_full_name() or user.username},

A jelszavát egy adminisztrátor visszaállította.

Az új jelszava: {password}

Kérjük, jelentkezzen be, és azonnal változtassa meg a jelszavát.

Bejelentkezés: {settings.FRONTEND_URL if hasattr(settings, 'FRONTEND_URL') else 'https://igazolas.szlg.info'}/login

Ha nem Ön kérte ezt a műveletet, azonnal vegye fel a kapcsolatot adminisztrátorával!

Üdvözlettel,
SZLG Igazoláskezelő Rendszer
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"✓ [EMAIL SUCCESS] Generated password sent to {user.email}")
        return True
        
    except Exception as e:
        logger.error(f"✗ [EMAIL FAILED] Failed to send generated password to {user.email}: {str(e)}")
        return False


def send_permission_change_email(user, promoted: bool, changed_by, subject_override=None):
    """
    Send email notification when user permissions change.
    
    Args:
        user: Django User object whose permissions changed
        promoted: True if promoted to superuser, False if demoted
        changed_by: User who made the change
        subject_override: Optional custom subject line (overrides default)
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        logger.debug(f"[EMAIL DEBUG] Attempting to send permission change notification to {user.email}")
        
        subject = subject_override if subject_override else '[SZLG Igazoláskezelő] A fiókjának jogosultságai megváltoztak'
        
        if promoted:
            permission_text = "Ön adminisztrátori jogosultságot kapott."
        else:
            permission_text = "Az Ön adminisztrátori jogosultságát megvonták."
        
        message = f"""
Kedves {user.get_full_name() or user.username},

A fiókjának jogosultságait {changed_by.get_full_name() or changed_by.username} frissítette.

{permission_text}

A változások azonnal érvényesek.

Ha kérdése van, kérjük, lépjen kapcsolatba a rendszergazdájával.

Üdvözlettel,
SZLG Igazoláskezelő Rendszer
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"✓ [EMAIL SUCCESS] Permission change notification sent to {user.email}")
        return True
        
    except Exception as e:
        logger.error(f"✗ [EMAIL FAILED] Failed to send permission change notification to {user.email}: {str(e)}")
        return False


def send_hianypotlas_szukseges_email(igazolas, subject_override=None):
    """
    Notify a student that their igazolás was sent back for corrections
    (Hiánypótlásra visszaküldve) by their osztályfőnök.

    Args:
        igazolas: Igazolas model instance (already saved with the new állapot
            and megjegyzes_tanar)
        subject_override: Optional custom subject line (overrides default)

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    user = igazolas.profile.user
    if not user.email:
        logger.warning(f"[EMAIL SKIPPED] User {user.username} has no email address, cannot send hiánypótlás notification")
        return False

    try:
        logger.debug(f"[EMAIL DEBUG] Attempting to send hiánypótlás notification to {user.email}")

        subject = subject_override if subject_override else '[SZLG Igazoláskezelő] Hiánypótlás szükséges az igazolásodhoz'

        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://igazolas.szlg.info')
        login_url = f"{frontend_url}/login?editIgazolas={igazolas.id}"

        html_message = render_to_string('emails/hianypotlas_szukseges.html', {
            'user': user,
            'igazolas': igazolas,
            'tipus_nev': igazolas.tipus.nev,
            'eleje': igazolas.eleje,
            'vege': igazolas.vege,
            'megjegyzes_tanar': igazolas.megjegyzes_tanar,
            'login_url': login_url,
            'current_year': timezone.now().year,
            'timestamp': timezone.now(),
        })

        plain_message = strip_tags(html_message)

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"✓ [EMAIL SUCCESS] Hiánypótlás notification sent to {user.email} for igazolás #{igazolas.id}")
        return True

    except Exception as e:
        logger.error(f"✗ [EMAIL FAILED] Failed to send hiánypótlás notification to {user.email}: {str(e)}")
        return False
