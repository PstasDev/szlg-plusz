"""
Admin utility functions for Phase 1 features.
Includes password generation, permission checking, and helper functions.
"""
import secrets
import string
from django.contrib.auth.models import User
from .models import Profile, Osztaly, PermissionChangeLog
import logging

logger = logging.getLogger(__name__)


def generate_strong_password(length=16):
    """
    Generate a cryptographically secure strong password.
    
    Args:
        length: Password length (default 16, minimum 12)
    
    Returns:
        str: Generated password with uppercase, lowercase, numbers, and special characters
    """
    if length < 12:
        length = 12
    
    # Define character sets
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*()-_=+[]{}|;:,.<>?"
    
    # Ensure at least one character from each set
    password = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    
    # Fill the rest with random characters from all sets
    all_chars = uppercase + lowercase + digits + special
    password += [secrets.choice(all_chars) for _ in range(length - 4)]
    
    # Shuffle to avoid predictable patterns
    password_list = list(password)
    secrets.SystemRandom().shuffle(password_list)
    
    return ''.join(password_list)


def validate_password_strength(password):
    """
    Validate password strength requirements.
    
    Args:
        password: Password string to validate
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if len(password) < 12:
        return False, "Password must be at least 12 characters long"
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in password)
    
    if not has_upper:
        return False, "Password must contain at least one uppercase letter"
    if not has_lower:
        return False, "Password must contain at least one lowercase letter"
    if not has_digit:
        return False, "Password must contain at least one digit"
    if not has_special:
        return False, "Password must contain at least one special character"
    
    return True, None


def is_superuser(user: User) -> bool:
    """
    Check if user has superuser privileges.
    
    Args:
        user: Django User object
    
    Returns:
        bool: True if user is superuser
    """
    return user.is_superuser


def log_permission_change(user: User, changed_by: User, action: str, previous_value: bool, new_value: bool):
    """
    Log permission changes for audit trail.
    
    Args:
        user: User whose permissions changed
        changed_by: User who made the change
        action: 'promoted' or 'demoted'
        previous_value: Previous is_superuser value
        new_value: New is_superuser value
    
    Returns:
        PermissionChangeLog: Created log entry
    """
    log_entry = PermissionChangeLog.objects.create(
        user=user,
        changed_by=changed_by,
        action=action,
        previous_value=previous_value,
        new_value=new_value
    )
    
    logger.info(f"Permission change logged: {user.username} {action} by {changed_by.username}")
    return log_entry


def get_permission_history(user: User, limit=50):
    """
    Get permission change history for a user.
    
    Args:
        user: Django User object
        limit: Maximum number of history entries to return
    
    Returns:
        QuerySet: Permission change logs
    """
    return PermissionChangeLog.objects.filter(user=user).order_by('-changed_at')[:limit]


def invalidate_user_sessions(user: User):
    """
    Invalidate all active sessions for a user.
    This forces re-authentication after password change.
    
    Args:
        user: Django User object
    
    Note:
        In a JWT-based system, this is primarily symbolic.
        Actual JWT invalidation would require a token blacklist.
    """
    # For JWT systems, sessions aren't tracked server-side
    # This is a placeholder for future session management
    logger.info(f"Session invalidation requested for user {user.username}")
    pass


def get_user_full_name(user: User) -> str:
    """
    Get user's full name or username fallback.
    
    Args:
        user: Django User object
    
    Returns:
        str: Full name or username
    """
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    elif user.last_name:
        return user.last_name
    else:
        return user.username


def get_or_create_profile(user: User) -> Profile:
    """
    Get or create a Profile for a user.
    
    Args:
        user: Django User object
    
    Returns:
        Profile: User's profile
    """
    profile, created = Profile.objects.get_or_create(user=user)
    if created:
        logger.info(f"Created new profile for user {user.username}")
    return profile


def is_teacher(user: User) -> bool:
    """
    Check if user is assigned as a teacher to any class.
    
    Args:
        user: Django User object
    
    Returns:
        bool: True if user is a teacher
    """
    return Osztaly.objects.filter(osztalyfonokok=user).exists()


def can_remove_teacher_from_class(osztaly: Osztaly, teacher: User) -> tuple:
    """
    Check if a teacher can be removed from a class.
    At least one teacher must remain assigned.
    
    Args:
        osztaly: Osztaly object
        teacher: User object
    
    Returns:
        tuple: (can_remove, error_message)
    """
    teacher_count = osztaly.osztalyfonokok.count()
    
    if teacher_count <= 1:
        return False, "Cannot remove the last teacher from class. At least one teacher must be assigned."
    
    if teacher not in osztaly.osztalyfonokok.all():
        return False, f"Teacher {teacher.username} is not assigned to this class."
    
    return True, None
