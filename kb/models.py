import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .rutube import embed_url as rutube_embed_url
from .catalog import SERVICES
from .rich_text import rich_plain_text


AUDIENCE_STAFF = "staff"
AUDIENCE_MANAGER = "manager"
AUDIENCE_DEVELOPER = "developer"
AUDIENCES = [
    (AUDIENCE_STAFF, "Все посетители"),
    (AUDIENCE_MANAGER, "Руководители"),
    (AUDIENCE_DEVELOPER, "Разработчики"),
]

GROUP_MANAGERS = "Руководители"
GROUP_DEVELOPERS = "Разработчики"
GROUP_EDITORS = "Редакторы"
GROUP_READERS = "Пользователи базы знаний"


def unique_slug(model, title, instance_pk=None):
    stem = slugify(title, allow_unicode=True)[:180] or "page"
    candidate = stem
    number = 2
    while model.objects.filter(slug=candidate).exclude(pk=instance_pk).exists():
        candidate = f"{stem[:170]}-{number}"
        number += 1
    return candidate


def image_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()[:12]
    return f"images/{uuid.uuid4().hex}{suffix}"


def attachment_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()[:12]
    return f"attachments/{uuid.uuid4().hex}{suffix}"


def validate_upload_size(file):
    if file.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError("Файл больше 25 МБ. Уменьшите его перед загрузкой.")


class Section(models.Model):
    title = models.CharField("Название", max_length=200)
    slug = models.SlugField("Адрес", max_length=200, unique=True, allow_unicode=True, blank=True)
    description = models.TextField("Описание", blank=True)
    description_is_rich = models.BooleanField(default=False, editable=False)
    service_slug = models.CharField("Сервис", max_length=40, choices=SERVICES, default="1c")
    catalog = models.CharField("Каталог", max_length=20, choices=(("main", "Разделы 1С"), ("discipline", "Дисциплины")), default="main")
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="Ответственный руководитель", null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_kb_sections")
    parent = models.ForeignKey("self", verbose_name="Родительский раздел", null=True, blank=True, related_name="children", on_delete=models.PROTECT)
    audience = models.CharField("Кому доступен", max_length=20, choices=AUDIENCES, default=AUDIENCE_STAFF)
    position = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Раздел"
        verbose_name_plural = "Разделы"
        ordering = ["position", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("kb:section", args=[self.slug])

    def clean(self):
        super().clean()
        if self.parent and (self.parent.service_slug != self.service_slug or self.parent.catalog != self.catalog):
            raise ValidationError({"parent": "Родитель должен находиться в том же сервисе и каталоге."})
        seen = {self.pk}
        ancestor = self.parent
        while ancestor:
            if ancestor.pk in seen:
                raise ValidationError({"parent": "Раздел нельзя вложить в самого себя или в свой дочерний раздел."})
            seen.add(ancestor.pk)
            ancestor = ancestor.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Section, self.title, self.pk)
        super().save(*args, **kwargs)


class Article(models.Model):
    DRAFT = "draft"
    PUBLISHED = "published"
    STATUSES = [(DRAFT, "Черновик"), (PUBLISHED, "Опубликована")]

    section = models.ForeignKey(Section, verbose_name="Раздел", related_name="articles", on_delete=models.PROTECT)
    title = models.CharField("Заголовок", max_length=240)
    slug = models.SlugField("Адрес", max_length=200, unique=True, allow_unicode=True, blank=True)
    summary = models.TextField("Краткое описание", blank=True, help_text="Показывается в поиске и в списке статей.")
    summary_is_rich = models.BooleanField(default=False, editable=False)
    title_alignment = models.CharField(
        "Выравнивание заголовка", max_length=10, default="left",
        choices=[("left", "Слева"), ("center", "По центру"), ("right", "Справа"), ("justify", "По ширине")],
    )
    title_size = models.CharField(
        "Размер заголовка", max_length=10, default="normal",
        choices=[("normal", "Обычный"), ("large", "Крупный"), ("huge", "Очень крупный")],
    )
    title_bold = models.BooleanField("Жирный заголовок", default=True)
    title_italic = models.BooleanField("Курсивный заголовок", default=False)
    featured_video_url = models.CharField(
        "Видео под заголовком (Rutube)", max_length=500, blank=True,
        help_text="Вставьте ссылку на видео Rutube. Плеер появится сразу под названием статьи.",
    )
    audience = models.CharField("Кому доступна", max_length=20, choices=AUDIENCES, default=AUDIENCE_STAFF)
    status = models.CharField("Статус", max_length=20, choices=STATUSES, default=DRAFT)
    position = models.PositiveIntegerField("Порядок", default=0)
    search_text = models.TextField("Текст для поиска", blank=True, editable=False)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Статья"
        verbose_name_plural = "Статьи"
        ordering = ["position", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("kb:article", args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Article, self.title, self.pk)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.featured_video_url:
            try:
                rutube_embed_url(self.featured_video_url)
            except ValidationError as exc:
                raise ValidationError({"featured_video_url": exc.messages}) from exc

    @property
    def featured_video_embed_url(self):
        if not self.featured_video_url:
            return ""
        try:
            return rutube_embed_url(self.featured_video_url)
        except ValidationError:
            return ""

    def rebuild_search_text(self):
        pieces = [
            rich_plain_text(text) if is_rich else text
            for text, is_rich in self.blocks.exclude(text="").values_list("text", "text_is_rich")
        ]
        pieces += list(self.blocks.exclude(caption="").values_list("caption", flat=True))
        pieces += list(self.attachments.values_list("title", flat=True))
        self.search_text = "\n".join(pieces)
        self.updated_at = timezone.now()
        self.save(update_fields=["search_text", "updated_at"])


class ContentBlock(models.Model):
    HEADING = "heading"
    TEXT = "text"
    NOTE = "note"
    IMAGE = "image"
    RUTUBE = "rutube"
    KINDS = [
        (HEADING, "Подзаголовок"),
        (TEXT, "Текст"),
        (NOTE, "Примечание"),
        (IMAGE, "Скриншот"),
        (RUTUBE, "Видео Rutube"),
    ]

    article = models.ForeignKey(Article, verbose_name="Статья", related_name="blocks", on_delete=models.CASCADE)
    kind = models.CharField("Тип блока", max_length=20, choices=KINDS, default=TEXT)
    position = models.PositiveIntegerField("Порядок", default=0)
    text = models.TextField("Текст", blank=True)
    text_is_rich = models.BooleanField(default=False, editable=False)
    image = models.ImageField("Скриншот", upload_to=image_upload_path, blank=True, validators=[validate_upload_size])
    gallery_id = models.CharField(max_length=32, blank=True, editable=False)
    display_width = models.PositiveSmallIntegerField(
        "Ширина изображения на странице", default=100,
        choices=[(value, f"{value}%") for value in range(25, 101, 5)],
        help_text="Размер фото под текстом. При открытии его можно увеличить отдельно.",
    )
    video_url = models.CharField("Ссылка на видео Rutube", max_length=500, blank=True)
    caption = models.CharField("Подпись", max_length=300, blank=True)

    class Meta:
        verbose_name = "Блок статьи"
        verbose_name_plural = "Блоки статьи"
        ordering = ["position", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.article}"

    def clean(self):
        super().clean()
        text = rich_plain_text(self.text) if self.text_is_rich else self.text.strip()
        if self.kind in {self.HEADING, self.TEXT, self.NOTE} and not text:
            raise ValidationError({"text": "Для этого блока укажите текст."})
        if self.kind == self.IMAGE and not self.image:
            raise ValidationError({"image": "Загрузите скриншот."})
        if self.kind == self.RUTUBE:
            if not self.video_url:
                raise ValidationError({"video_url": "Вставьте ссылку на видео Rutube."})
            try:
                rutube_embed_url(self.video_url)
            except ValidationError as exc:
                raise ValidationError({"video_url": exc.messages}) from exc

    @property
    def embed_url(self):
        if self.kind != self.RUTUBE or not self.video_url:
            return ""
        try:
            return rutube_embed_url(self.video_url)
        except ValidationError:
            return ""


class Attachment(models.Model):
    article = models.ForeignKey(Article, verbose_name="Статья", related_name="attachments", on_delete=models.CASCADE)
    title = models.CharField("Название файла", max_length=240)
    file = models.FileField("Файл", upload_to=attachment_upload_path, validators=[validate_upload_size])
    original_filename = models.CharField("Исходное имя", max_length=255, blank=True, editable=False)
    position = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Вложение"
        verbose_name_plural = "Вложения"
        ordering = ["position", "pk"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.file and (self._state.adding or not self.original_filename):
            self.original_filename = Path(self.file.name).name[:255]
        super().save(*args, **kwargs)
