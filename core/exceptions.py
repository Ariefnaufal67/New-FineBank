from django.http import Http404
from rest_framework import exceptions
from rest_framework.views import exception_handler


class Conflict(exceptions.APIException):
    status_code = 409
    default_detail = 'Data duplikat'
    default_code = 'conflict'


def _flatten(detail, prefix=''):
    """Ubah detail validasi DRF menjadi [{field, message}]."""
    out = []
    if isinstance(detail, dict):
        for k, v in detail.items():
            out += _flatten(v, f'{prefix}.{k}' if prefix else str(k))
    elif isinstance(detail, list):
        for v in detail:
            out += _flatten(v, prefix)
    else:
        out.append({'field': prefix, 'message': str(detail)})
    return out


def handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound('Data tidak ditemukan')
    response = exception_handler(exc, context)
    if response is None:
        return None
    errors = None
    if isinstance(exc, exceptions.ValidationError):
        message, errors = 'Validasi gagal', _flatten(exc.detail)
    elif isinstance(exc, exceptions.NotAuthenticated):
        message = 'Token Bearer wajib disertakan'
    elif isinstance(exc, exceptions.PermissionDenied):
        message = 'Role Anda tidak diizinkan mengakses resource ini'
    elif isinstance(exc, exceptions.Throttled):
        message = 'Terlalu banyak request, coba lagi nanti'
    elif isinstance(exc, exceptions.ParseError):
        message = 'JSON tidak valid'
    else:
        message = str(exc.detail)
    body = {'success': False, 'message': message}
    if errors is not None:
        body['errors'] = errors
    response.data = body
    return response
