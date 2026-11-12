from django.apps import AppConfig


class KbConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kb"
    verbose_name = "База знаний"

    def ready(self):
        from . import signals  # noqa: F401
