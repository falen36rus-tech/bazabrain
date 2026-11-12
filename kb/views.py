import mimetypes
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .access import navigation_tree, visible_articles, visible_sections
from .models import Article, Attachment, ContentBlock
from .rich_text import rich_plain_text
from .search import search_articles, search_sections


SITE_NAME = "База знаний 1С"


def base_context(request, *, sections=None, articles=None):
    sections = visible_sections(request.user) if sections is None else sections
    return {
        "site_name": SITE_NAME,
        "nav_tree": navigation_tree(request.user, sections, articles),
        "current_article": None,
        "current_section": None,
        "can_edit": request.user.is_superuser,
    }


@login_required
def home(request):
    sections = visible_sections(request.user)
    articles = visible_articles(request.user, sections)
    context = base_context(request, sections=sections)
    filled_articles = articles.filter(Q(blocks__isnull=False) | Q(attachments__isnull=False)).distinct()
    context.update(
        sections=[section for section in sections if section.parent_id is None],
        recent_articles=list(filled_articles.only("id", "title", "slug", "section_id", "updated_at", "section__title").order_by("-updated_at")[:6]),
        article_count=articles.count(),
    )
    return render(request, "kb/home.html", context)


@login_required
def section_detail(request, slug):
    sections = visible_sections(request.user)
    section = next((item for item in sections if item.slug == slug), None)
    if section is None:
        raise Http404
    articles = list(visible_articles(request.user, sections).filter(section_id=section.pk))
    context = base_context(request, sections=sections)
    context.update(
        section=section,
        current_section=section,
        child_sections=[item for item in sections if item.parent_id == section.pk],
        articles=articles,
    )
    return render(request, "kb/section.html", context)


@login_required
def article_detail(request, slug):
    article = get_object_or_404(visible_articles(request.user), slug=slug)
    context = base_context(request)
    context.update(
        article=article,
        blocks=list(article.blocks.all()),
        attachments=list(article.attachments.all()),
        current_article=article,
        current_section=article.section,
    )
    return render(request, "kb/article.html", context)


@login_required
def search(request):
    query = request.GET.get("q", "")[:160].strip()
    context = base_context(request)
    section_results = search_sections(request.user, query)
    search_results = search_articles(request.user, query)
    context.update(q=query, section_results=section_results, search_results=search_results, result_count=len(section_results) + len(search_results))
    return render(request, "kb/search.html", context)


@login_required
def suggest(request):
    query = request.GET.get("q", "")[:160]
    sections = search_sections(request.user, query, limit=3) if len(query.strip()) >= 2 else []
    articles = search_articles(request.user, query, limit=7 - len(sections)) if len(query.strip()) >= 2 else []
    return JsonResponse(
        {
            "results": [
                {
                    "title": section.title,
                    "section": "Раздел",
                    "summary": (rich_plain_text(section.description) if section.description_is_rich else section.description)[:160],
                    "url": reverse("kb:section", args=[section.slug]),
                }
                for section in sections
            ] + [
                {
                    "title": article.title,
                    "section": article.section.title,
                    "summary": (rich_plain_text(article.summary) if article.summary_is_rich else article.summary)[:160],
                    "url": reverse("kb:article", args=[article.slug]),
                }
                for article in articles
            ]
        }
    )


@login_required
def private_file(request, pk):
    block = get_object_or_404(ContentBlock.objects.select_related("article"), pk=pk, kind=ContentBlock.IMAGE)
    if not visible_articles(request.user).filter(pk=block.article_id).exists() or not block.image:
        raise Http404
    guessed_type = mimetypes.guess_type(block.image.name)[0]
    if guessed_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        raise Http404
    try:
        response = FileResponse(block.image.open("rb"), content_type=guessed_type)
    except FileNotFoundError as exc:
        raise Http404 from exc
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def private_attachment(request, pk):
    attachment = get_object_or_404(Attachment.objects.select_related("article"), pk=pk)
    if not visible_articles(request.user).filter(pk=attachment.article_id).exists():
        raise Http404
    filename = attachment.original_filename or Path(attachment.file.name).name
    try:
        response = FileResponse(attachment.file.open("rb"), as_attachment=True, filename=filename, content_type="application/octet-stream")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
