from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils.html import format_html
from reversion.admin import VersionAdmin

from .admin_rich import ArticleRichForm, ContentBlockRichForm, PrivateImageInput, SectionRichForm
from .models import Article, Attachment, ContentBlock, Section
from .access import editable_section_ids
from .models import GROUP_EDITORS, GROUP_MANAGERS


def scoped_manager(user):
    return user.is_authenticated and not user.is_superuser and not user.groups.filter(name=GROUP_EDITORS).exists() and user.groups.filter(name=GROUP_MANAGERS).exists()


admin.site.site_header = "Управление базой знаний 1С"
admin.site.site_title = "База знаний 1С"
admin.site.index_title = "Материалы и пользователи"


@admin.register(Section)
class SectionAdmin(VersionAdmin):
    form = SectionRichForm
    history_latest_first = True
    list_display = ("title", "service_slug", "catalog", "parent", "manager", "audience", "position", "article_count")
    list_filter = ("service_slug", "catalog", "audience")
    search_fields = ("title", "description")
    ordering = ("parent__title", "position", "title")
    fields = ("title", "slug", "description", "service_slug", "catalog", "parent", "manager", "audience", "position")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "manager":
            kwargs["queryset"] = get_user_model().objects.filter(is_staff=True, groups__name=GROUP_MANAGERS).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.filter(pk__in=editable_section_ids(request.user)) if scoped_manager(request.user) else queryset

    def get_readonly_fields(self, request, obj=None):
        return ("service_slug", "catalog", "parent", "manager") if scoped_manager(request.user) else ()

    def has_add_permission(self, request):
        return not scoped_manager(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or not scoped_manager(request.user) or obj.pk in editable_section_ids(request.user))

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (obj is None or not scoped_manager(request.user) or obj.pk in editable_section_ids(request.user))

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description="Статей")
    def article_count(self, obj):
        return obj.articles.count()


class ContentBlockInline(admin.StackedInline):
    model = ContentBlock
    form = ContentBlockRichForm
    extra = 0
    fields = ("position", "kind", "text", "image", "extra_images", "display_width", "video_url", "caption")
    formfield_overrides = {ContentBlock._meta.get_field("image").__class__: {"widget": PrivateImageInput}}
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
        ("title_bold", "title_italic"), "featured_video_file", "featured_video_url", "slug", "summary",
        "audience", "status", "position", "created_at", "updated_at",
    )
    inlines = [ContentBlockInline, AttachmentInline]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.filter(section_id__in=editable_section_ids(request.user)) if scoped_manager(request.user) else queryset

    def get_list_filter(self, request):
        return ("status", "audience") if scoped_manager(request.user) else super().get_list_filter(request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if scoped_manager(request.user) and "section" in form.base_fields:
            form.base_fields["section"].queryset = Section.objects.filter(pk__in=editable_section_ids(request.user))
        return form

    def has_add_permission(self, request):
        return super().has_add_permission(request) and (not scoped_manager(request.user) or bool(editable_section_ids(request.user)))

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or not scoped_manager(request.user) or obj.section_id in editable_section_ids(request.user))

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (obj is None or not scoped_manager(request.user) or obj.section_id in editable_section_ids(request.user))

    def save_model(self, request, obj, form, change):
        if scoped_manager(request.user) and obj.section_id not in editable_section_ids(request.user):
            raise PermissionDenied
        super().save_model(request, obj, form, change)

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
        for formset in formsets:
            if formset.model is not ContentBlock:
                continue
            for inline_form in formset.forms:
                if not inline_form.is_valid() or inline_form.cleaned_data.get("DELETE"):
                    continue
                extras = inline_form.cleaned_data.get("extra_images") or []
                parent = inline_form.instance
                if not parent.pk:
                    continue
                for image in extras:
                    ContentBlock.objects.create(
                        article=parent.article, kind=ContentBlock.IMAGE, position=parent.position,
                        gallery_id=parent.gallery_id, image=image, caption=parent.caption,
                        display_width=parent.display_width,
                    )
        form.instance.rebuild_search_text()
