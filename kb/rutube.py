"""A narrow RUTUBE embed adapter: editors paste a link, never iframe HTML."""

import re
from urllib.parse import parse_qs, urlencode, urlsplit

from django.core.exceptions import ValidationError


VIDEO_ID = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def embed_url(value: str) -> str:
    """Return a fixed-origin iframe URL for a documented RUTUBE video link."""
    raw = value.strip()
    if VIDEO_ID.fullmatch(raw):
        video_id = raw.lower()
        token = None
    else:
        parsed = urlsplit(raw)
        if parsed.scheme != "https" or parsed.hostname not in {"rutube.ru", "www.rutube.ru"}:
            raise ValidationError("Используйте ссылку https://rutube.ru/video/... или https://rutube.ru/play/embed/...")
        if parsed.port or parsed.username or parsed.password or parsed.fragment:
            raise ValidationError("Некорректная ссылка на Rutube.")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 2 and parts[0] == "video":
            video_id = parts[1]
        elif len(parts) == 3 and parts[:2] == ["video", "private"]:
            video_id = parts[2]
        elif len(parts) == 3 and parts[:2] == ["play", "embed"]:
            video_id = parts[2]
        else:
            raise ValidationError("Ссылка должна вести на конкретное видео Rutube.")
        if not VIDEO_ID.fullmatch(video_id):
            raise ValidationError("Не найден корректный идентификатор видео Rutube.")
        query = parse_qs(parsed.query, keep_blank_values=True)
        token_values = query.get("p", [])
        if len(token_values) > 1:
            raise ValidationError("В ссылке слишком много параметров доступа.")
        token = token_values[0] if token_values else None
        if token is not None and not TOKEN.fullmatch(token):
            raise ValidationError("Некорректный параметр доступа к видео.")
        video_id = video_id.lower()

    result = f"https://rutube.ru/play/embed/{video_id}/"
    if token:
        result += "?" + urlencode({"p": token})
    return result
