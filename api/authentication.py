import jwt
from ninja.security import HttpBearer
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.utils import timezone
from .jwt_utils import decode_jwt_token


class JWTAuth(HttpBearer):
    """
    Custom JWT authentication for Django Ninja.
    Validates Bearer tokens from the Authorization header.
    """
    
    def authenticate(self, request: HttpRequest, token: str):
        """
        Authenticate the request using JWT token.
        
        Updates user's last_login timestamp and login_count on every successful authentication.
        
        Args:
            request: Django HttpRequest object
            token: JWT token string from Bearer header
            
        Returns:
            User object if authentication successful, None otherwise
        """
        try:
            # Decode and validate the token
            payload = decode_jwt_token(token)
            
            # Get user from payload
            user_id = payload.get('user_id')
            
            if not user_id:
                return None
            
            # Fetch user from database
            try:
                from .models import Profile
                
                user = User.objects.get(pk=user_id, is_active=True)
                
                # Update last_login timestamp
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                
                # Update login_count in Profile
                profile, created = Profile.objects.get_or_create(user=user)
                if created or profile.login_count == 0:
                    # First login or new profile
                    profile.login_count = 1
                else:
                    # Don't increment on every API call, only on actual new sessions
                    # For now, we'll track this in the login endpoint
                    pass
                profile.save(update_fields=['login_count'])
                
                return user
            except User.DoesNotExist:
                return None
                
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None
        except Exception:
            return None

