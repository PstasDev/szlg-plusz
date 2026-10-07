"""Catch-all static/media file serving views.

Django's bundled ``django.views.static.serve`` is disabled outside of DEBUG and
the ``staticfiles`` URL helpers similarly no-op in production. This app exposes
a tiny catch-all view that streams files straight from disk so the project can
serve its own assets under ASGI (gunicorn + uvicorn worker) without WhiteNoise.
"""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponseNotModified
from django.utils.http import http_date
from django.views.static import was_modified_since


def _serve_from(root: Path, path: str, request):
    root = Path(root).resolve()
    # Strip any leading slashes so Path treats it as relative.
    rel = (path or "").lstrip("/\\")
    target = (root / rel).resolve()

    # Prevent path traversal outside the configured root.
    try:
        target.relative_to(root)
    except ValueError:
        raise Http404("Path is outside of the allowed directory.")

    if not target.is_file():
        raise Http404(f"'{path}' does not exist.")

    stat = target.stat()
    if not was_modified_since(
        request.META.get("HTTP_IF_MODIFIED_SINCE"), stat.st_mtime
    ):
        return HttpResponseNotModified()

    content_type, encoding = mimetypes.guess_type(str(target))
    response = FileResponse(
        target.open("rb"),
        content_type=content_type or "application/octet-stream",
    )
    response["Content-Length"] = stat.st_size
    response["Last-Modified"] = http_date(stat.st_mtime)
    if encoding:
        response["Content-Encoding"] = encoding
    return response


def serve_static(request, path):
    return _serve_from(settings.STATIC_ROOT, path, request)


def serve_media(request, path):
    return _serve_from(settings.MEDIA_ROOT, path, request)
