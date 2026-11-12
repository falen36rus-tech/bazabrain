from django.contrib import admin
from django.forms import FileInput
from django.utils.html import format_html
from reversion.admin import VersionAdmin

from .admin_rich import ArticleRichForm, ContentBlockRichForm, SectionRichForm
from .models import Article, Attachment, ContentBlock, Section


admin.site.site_header = "Управление базой знаний 1С"
admin.site.site_title = "База знаний 1С"
admin.site.index_title = "Материалы и пользователи"


@admin.register(Section)
class SectionAdmin(VersionAdmin):
    form = SectionRichForm
    history_latest_first = True
    list_display = ("title", "parent", "audience", "position", "article_count")
    list_filter = ("audience",)
    search_fields = ("title", "description")
    ordering = ("parent__title", "position", "title")
    fields = ("title", "slug", "description", "parent", "audience", "position")

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Статей")
    def article_count(self, obj):
        return obj.articles.count()


class ContentBlockInline(admin.StackedInline):
    model = ContentBlock
    form = ContentBlockRichForm
    extra = 0
    fields = ("position", "kind", "text", "image", "video_url", "caption")
    formfield_overrides = {ContentBlock._meta.get_field("image").__class__: {"widget": FileInput}}
    verbose_name = "Блок: текст, заголовок, скриншот или Rutube"
    verbose_name_plural = "Содержимое статьи — добавьте блоки в нужном порядке"


class AttachmentInline(admin.StackedInline):
    model = Attachment
    extra = 0
    fields = ("position", "title", "file")
    verbose_name = "Файл"
    verbose_name_plural = "Файлы для скачивания"


@admin.register(Article)
class ArticleAdmin(VersionAdmin):
    form = ArticleRichForm
    history_latest_first = True
    list_display = ("title", "section", "status", "audience", "updated_at", "view_link")
    list_filter = ("status", "audience", "section")
    search_fields = ("title", "summary", "search_text")
    ordering = ("section__title", "position", "title")
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "section", "title", ("title_size", "title_alignment"),
        ("title_bold", "title_italic"), "featured_video_url", "slug", "summary",
        "audience", "status", "position", "created_at", "updated_at",
    )
    inlines = [ContentBlockInline, AttachmentInline]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "summary" and field is not None:
            field.help_text = (
                "Короткий анонс для списка и поиска. Полную инструкцию с шагами, "
                "скриншотами и видео добавляйте ниже в «Содержимое статьи» отдельными блоками."
            )
        return field

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="На сайте")
    def view_link(self, obj):
        if obj.status != Article.PUBLISHED:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Открыть</a>', obj.get_absolute_url())

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.rebuild_search_text()
