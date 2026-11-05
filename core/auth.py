"""Autentikasi JWT (Authorization: Bearer <token>). Token memuat sub, name, email, role."""
import time

import jwt
from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import User


def sign_token(user):
    now = int(time.time())
    payload = {'sub': str(user.id), 'name': user.name, 'email': user.email, 'role': user.role,
               'iat': now, 'exp': now + int(settings.JWT_LIFETIME.total_seconds())}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


class JWTAuth(BaseAuthentication):
    def authenticate(self, request):
        parts = request.headers.get('Authorization', '').split()
        if len(parts) != 2 or parts[0] != 'Bearer':
            return None  # tanpa token -> IsAuthenticated menolak dengan 401
        try:
            payload = jwt.decode(parts[1], settings.SECRET_KEY, algorithms=['HS256'])
        except jwt.PyJWTError:
            raise AuthenticationFailed('Token tidak valid atau kedaluwarsa')
        user = User.objects.filter(pk=payload.get('sub'), is_active=True).first()
        if not user:
            raise AuthenticationFailed('Pengguna tidak ditemukan')
        return (user, parts[1])

    def authenticate_header(self, request):
        return 'Bearer'


class JWTAuthScheme(OpenApiAuthenticationExtension):
    target_class = 'core.auth.JWTAuth'
    name = 'bearerAuth'

    def get_security_definition(self, auto_schema):
        return {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}
