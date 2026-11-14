"""Read-only video files supplied by the company network share."""

from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError


VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm"}


def video_path(relative_name):
    name = PurePosixPath(relative_name)
    if (not relative_name or "\\" in relative_name or name.is_absolute()
            or any(part in {".", ".."} for part in relative_name.split("/"))
            or name.suffix.lower() not in VIDEO_TYPES):
        raise ValidationError("Выберите видео из доступной папки.")
    root = Path(settings.VIDEO_LIBRARY_ROOT).resolve()
    path = (root / relative_name).resolve()
    if not path.is_relative_to(root):
        raise ValidationError("Недопустимый путь к видео.")
    return path


def available_videos():
    root = Path(settings.VIDEO_LIBRARY_ROOT)
    if not root.is_dir():
        return []
    names = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_TYPES:
            name = path.relative_to(root).as_posix()
            try:
                video_path(name)
            except ValidationError:
                continue
            names.append(name)
    return sorted(names, key=str.casefold)
