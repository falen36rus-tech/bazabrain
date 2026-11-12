"""Local rich-text controls for the existing Django admin forms."""

from django import forms

from .models import Article, ContentBlock, Section
from .rich_text import clean_rich_html


class RichTextWidget(forms.Textarea):
    class Media:
        css = {"all": ("kb/vendor/quill/quill.snow.css", "kb/admin_rich.css")}
        js = ("kb/vendor/quill/quill.js", "kb/admin_rich.js")

    def __init__(self, attrs=None):
        super().__init__({"data-kb-rich-editor": "1", **(attrs or {})})


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

    class Meta:
        model = Article
        fields = "__all__"
        widgets = {"summary": RichTextWidget}


class ContentBlockRichForm(RichTextFormMixin, forms.ModelForm):
    rich_field = "text"
    rich_flag = "text_is_rich"

    class Meta:
        model = ContentBlock
        fields = "__all__"
        widgets = {"text": RichTextWidget}
