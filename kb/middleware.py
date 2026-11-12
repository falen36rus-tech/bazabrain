class ContentSecurityPolicyMiddleware:
    """Keep article text and media restricted to known origins."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Django's stock admin currently uses inline scripts and styles.
        if request.path.startswith("/admin/"):
            return response
        response["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "frame-src https://rutube.ru; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        return response
