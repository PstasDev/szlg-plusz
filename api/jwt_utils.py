import jwt
import datetime
from django.conf import settings


def generate_jwt_token(user):
    """
    Generate a JWT token for a user.
    
    Args:
        user: Django User object
        
    Returns:
        str: JWT token containing user_id, username, iat, and exp
    """
    now = datetime.datetime.utcnow()
    expiration = now + datetime.timedelta(seconds=settings.JWT_EXPIRATION_DELTA)
    
    payload = {
        'user_id': user.id,
        'username': user.username,
        'iat': int(now.timestamp()),
        'exp': int(expiration.timestamp())
    }
    
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    return token


def decode_jwt_token(token):
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded payload if valid
        
    Raises:
        jwt.ExpiredSignatureError: If token has expired
        jwt.InvalidTokenError: If token is invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise jwt.ExpiredSignatureError("Token has expired")
    except jwt.InvalidTokenError:
        raise jwt.InvalidTokenError("Invalid token")
