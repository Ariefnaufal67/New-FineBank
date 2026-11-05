"""Pagination: ?page=2&limit=5 (limit maks. 100) dengan objek `meta`."""
from rest_framework.pagination import BasePagination
from rest_framework.response import Response


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class StandardPagination(BasePagination):
    default_limit = 10
    max_limit = 100

    def paginate_queryset(self, queryset, request, view=None):
        self.page = max(_int(request.query_params.get('page'), 1), 1)
        self.limit = min(max(_int(request.query_params.get('limit'), self.default_limit), 1), self.max_limit)
        self.total = queryset.count()
        offset = (self.page - 1) * self.limit
        return list(queryset[offset:offset + self.limit])

    def get_paginated_response(self, data):
        total_pages = max(-(-self.total // self.limit), 1)
        return Response({
            'success': True,
            'data': data,
            'meta': {'page': self.page, 'limit': self.limit, 'total': self.total, 'totalPages': total_pages,
                     'hasNext': self.page < total_pages, 'hasPrev': self.page > 1},
        })

    def get_paginated_response_schema(self, schema):
        return {'type': 'object', 'properties': {
            'success': {'type': 'boolean'}, 'data': schema,
            'meta': {'type': 'object', 'properties': {
                'page': {'type': 'integer'}, 'limit': {'type': 'integer'}, 'total': {'type': 'integer'},
                'totalPages': {'type': 'integer'}, 'hasNext': {'type': 'boolean'}, 'hasPrev': {'type': 'boolean'}}}}}

    def get_schema_operation_parameters(self, view):
        return [
            {'name': 'page', 'in': 'query', 'schema': {'type': 'integer'}},
            {'name': 'limit', 'in': 'query', 'description': 'Maks. 100', 'schema': {'type': 'integer'}},
        ]
