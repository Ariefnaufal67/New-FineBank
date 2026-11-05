from rest_framework.renderers import JSONRenderer


class EnvelopeRenderer(JSONRenderer):
    """Bungkus semua respons sukses menjadi { success: true, data: ... } (kontrak sama dengan versi Node)."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get('response')
        if response is not None and response.status_code < 400 and data is not None:
            if not (isinstance(data, dict) and 'success' in data):
                data = {'success': True, 'data': data}
        return super().render(data, accepted_media_type, renderer_context)
