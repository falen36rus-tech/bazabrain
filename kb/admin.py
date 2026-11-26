from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from reversion.admin import VersionAdmin

from .admin_rich import ArticleRichForm, ContentBlockRichForm, PrivateImageInput, SectionRichForm
from .models import Article, ArticleInlineImage, Attachment, ContentBlock, Section
from .rich_text import clean_rich_html
from .access import editable_section_ids
from .copying import copy_article_to_section
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
    change_form_template = "admin/kb/article/change_form.html"
    history_latest_first = True
    list_display = ("title", "section", "status", "audience", "created_by", "updated_by", "updated_at", "view_link")
    list_filter = ("status", "audience", "section")
    search_fields = ("title", "summary", "search_text")
    ordering = ("section__title", "position", "title")
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")
    fields = (
        "section", "help_for_service", "title", ("title_size", "title_alignment"),
        ("title_bold", "title_italic"), "network_video_path", "slug", "summary", "body",
        "audience", "status", "position", "created_at", "created_by", "updated_at", "updated_by",
    )
    inlines = [AttachmentInline]

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/copy-to-discipline/",
                self.admin_site.admin_view(self.copy_to_discipline_view),
                name="kb_article_copy_to_discipline",
            ),
        ]
        return custom_urls + super().get_urls()

    def copy_to_discipline_view(self, request, object_id):
        source = self.get_object(request, object_id)
        if source is None or not self.has_change_permission(request, source) or not self.has_add_permission(request):
            raise PermissionDenied

        destinations = Section.objects.filter(service_slug="1c", catalog="discipline")
        if scoped_manager(request.user):
            destinations = destinations.filter(pk__in=editable_section_ids(request.user))

        class DestinationField(forms.ModelChoiceField):
            def label_from_instance(self, section):
                names = []
                while section is not None:
                    names.append(section.title)
                    section = section.parent
                return " / ".join(reversed(names))

        class CopyForm(forms.Form):
            destination = DestinationField(
                label="Дисциплина или вложенный раздел",
                queryset=destinations,
                empty_label="Выберите место для копии",
            )

        form = CopyForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                copied = copy_article_to_section(source, form.cleaned_data["destination"], request.user)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(request, f"Статья «{source.title}» скопирована в дисциплину.", messages.SUCCESS)
                return HttpResponseRedirect(reverse("admin:kb_article_change", args=[copied.pk]))

        context = {
            **self.admin_site.each_context(request),
            "title": "Скопировать статью в дисциплину",
            "source": source,
            "form": form,
            "opts": self.model._meta,
            "original": source,
        }
        return render(request, "admin/kb/article/copy_to_discipline.html", context)

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
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        if form.pending_inline_images:
            body = obj.body
            for token, file in form.pending_inline_images:
                image = ArticleInlineImage.objects.create(article=obj, image=file)
                body = body.replace(token, f'<img src="/private/article-image/{image.pk}/" alt="Скриншот">')
            obj.body = clean_rich_html(body, allow_images=True, allow_tables=True)
            obj.save(update_fields=["body"])

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "summary" and field is not None:
            field.help_text = (
                "Короткий анонс для списка и поиска. Полную инструкцию с текстом "
                "и скриншотами добавляйте ниже в одно поле «Содержимое статьи»."
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
                # The formset was validated before saving. Revalidating a deleted
                # form here fails because Django has already cleared its PK.
                if inline_form.cleaned_data.get("DELETE"):
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
