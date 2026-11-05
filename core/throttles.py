"""Throttling: jumlah request per jendela 15 menit per IP (nilai dari settings)."""
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class _WindowThrottle(SimpleRateThrottle):
    def parse_rate(self, rate):
        # rate = jumlah request; jendela tetap RATE_WINDOW_SECONDS
        return int(rate), settings.RATE_WINDOW_SECONDS

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class GlobalThrottle(_WindowThrottle):
    scope = 'global'


class AuthThrottle(_WindowThrottle):
    """Login & register: dibatasi lebih ketat untuk menahan tebak-tebakan password."""
    scope = 'auth'
