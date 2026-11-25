"""Local rich-text controls for the existing Django admin forms."""

from django import forms
from django.core.files.base import ContentFile
from django.utils.html import format_html
import base64
import binascii
from io import BytesIO
import re
import uuid
from PIL import Image, UnidentifiedImageError

from .models import Article, ContentBlock, Section, validate_upload_size
from .rich_text import clean_rich_html, rich_plain_text


class RichTextWidget(forms.Textarea):
    class Media:
        css = {"all": ("kb/vendor/quill/quill.snow.css", "kb/admin_rich.css")}
        js = ("kb/vendor/quill/quill.js", "kb/admin_rich.js")

    def __init__(self, attrs=None):
        super().__init__({"data-kb-rich-editor": "1", **(attrs or {})})


class PrivateImageInput(forms.FileInput):
    def render(self, name, value, attrs=None, renderer=None):
        control = super().render(name, value, attrs, renderer)
        if value and getattr(value, "name", None):
            return format_html('{}<span class="help">Изображение сохранено: {}</span>', control, value.name.rsplit('/', 1)[-1])
        return control


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleImageInput

    def clean(self, data, initial=None):
        if not data:
            return []
        single_clean = super().clean
        return [single_clean(file) for file in data if file]


class RichTextFormMixin:
    rich_field = None
    rich_flag = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields[self.rich_field]
        marker = f"{self.add_prefix(self.rich_field)}__rich"
        was_rich = bool(getattr(self.instance, self.rich_flag, False))
        field.widget.attrs["data-kb-original-rich"] = "1" if was_rich or self.data.get(marker) == "1" else "0"
        if was_rich and not self.is_bound:
            self.initial[self.rich_field] = clean_rich_html(getattr(self.instance, self.rich_field))

    def clean(self):
        cleaned = super().clean()
        if self.rich_field in cleaned:
            marker = f"{self.add_prefix(self.rich_field)}__rich"
            if self.data.get(marker) == "1" or getattr(self.instance, self.rich_flag, False):
                cleaned[self.rich_field] = clean_rich_html(cleaned[self.rich_field])
                setattr(self.instance, self.rich_flag, True)
        return cleaned


class SectionRichForm(RichTextFormMixin, forms.ModelForm):
    rich_field = "description"
    rich_flag = "description_is_rich"

    class Meta:
        model = Section
        fields = "__all__"
        widgets = {"description": RichTextWidget}


class ArticleRichForm(RichTextFormMixin, forms.ModelForm):
    rich_field = "summary"
    rich_flag = "summary_is_rich"
    network_video_path = forms.ChoiceField(label="Видео с сетевого диска", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["body"].widget.attrs["data-kb-original-rich"] = "1" if self.instance.body_is_rich or self.data.get(f"{self.add_prefix('body')}__rich") == "1" else "0"
        from .video_library import available_videos
        names = available_videos()
        current = self.instance.network_video_path
        if current and current not in names:
            names.insert(0, current)
        self.fields["network_video_path"].choices = [("", "Без видео с сетевого диска")] + [
            (name, name) for name in names
        ]
        self.fields["network_video_path"].help_text = "Файлы из общей папки; выберите нужный ролик."

    def clean(self):
        cleaned = super().clean()
        self.pending_inline_images = []
        raw = cleaned.get("body") or ""
        if self.data.get(f"{self.add_prefix('body')}__rich") == "1" or self.instance.body_is_rich:
            def capture(match):
                mime, encoded = match.group(1), match.group(2)
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise forms.ValidationError("Некорректное изображение в тексте.")
                if len(data) > 8 * 1024 * 1024:
                    raise forms.ValidationError("Изображение в тексте не должно превышать 8 МБ.")
                try:
                    with Image.open(BytesIO(data)) as picture:
                        if picture.format != {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP", "gif": "GIF"}[mime]:
                            raise forms.ValidationError("Формат скриншота не совпадает с содержимым файла.")
                        picture.verify()
                except (UnidentifiedImageError, OSError) as exc:
                    raise forms.ValidationError("Некорректное изображение в тексте.") from exc
                token = f"KBINLINEIMAGE{uuid.uuid4().hex}"
                self.pending_inline_images.append((token, ContentFile(data, name=f"{token}.{mime.replace('jpeg', 'jpg')}")))
                return token
            def replace_image(match):
                source = re.search(r'\bsrc="data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)"', match.group(0))
                return capture(source) if source else match.group(0)
            try:
                raw = re.sub(r'<img\b[^>]*>', replace_image, raw)
            except forms.ValidationError as exc:
                self.add_error("body", exc)
            cleaned["body"] = clean_rich_html(raw, allow_images=True)
            self.instance.body_is_rich = True
        return cleaned

    class Meta:
        model = Article
        fields = "__all__"
        widgets = {"summary": RichTextWidget, "body": RichTextWidget(attrs={"data-kb-article-body": "1"})}


class ContentBlockRichForm(RichTextFormMixin, forms.ModelForm):
    rich_field = "text"
    rich_flag = "text_is_rich"
    extra_images = MultipleImageField(
        label="Добавить ещё фото", required=False,
        validators=[validate_upload_size],
        help_text="Можно выбрать несколько файлов сразу. Они появятся одной галереей после сохранения.",
    )

    def clean(self):
        cleaned = super().clean()
        extras = cleaned.get("extra_images") or []
        if extras:
            if not cleaned.get("image"):
                cleaned["image"] = extras.pop(0)
            self.instance.gallery_id = self.instance.gallery_id or uuid.uuid4().hex
        text = cleaned.get("text") or ""
        has_text = bool(rich_plain_text(text) if self.instance.text_is_rich else text.strip())
        if cleaned.get("image") and not has_text:
            cleaned["kind"] = ContentBlock.IMAGE
        return cleaned

    class Meta:
        model = ContentBlock
        fields = "__all__"
        widgets = {"text": RichTextWidget}
