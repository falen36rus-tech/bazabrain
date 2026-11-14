"""The single visibility rule used by pages, search and private files."""

from django.db.models import Q, QuerySet

from .models import (
    AUDIENCE_DEVELOPER,
    AUDIENCE_MANAGER,
    AUDIENCE_STAFF,
    GROUP_DEVELOPERS,
    GROUP_EDITORS,
    GROUP_MANAGERS,
    Article,
    Section,
)


def allowed_audiences(user):
    if not user.is_authenticated:
        return {AUDIENCE_STAFF}
    if user.is_superuser:
        return {AUDIENCE_STAFF, AUDIENCE_MANAGER, AUDIENCE_DEVELOPER}
    audiences = {AUDIENCE_STAFF}
    group_names = set(user.groups.values_list("name", flat=True))
    if GROUP_EDITORS in group_names:
        return {AUDIENCE_STAFF, AUDIENCE_MANAGER, AUDIENCE_DEVELOPER}
    if GROUP_MANAGERS in group_names:
        audiences.add(AUDIENCE_MANAGER)
    if GROUP_DEVELOPERS in group_names:
        audiences.add(AUDIENCE_DEVELOPER)
    return audiences


def filled_article_filter():
    """A title alone is not enough to publish an article to anonymous visitors."""
    return (
        Q(summary__regex=r"\S")
        | Q(featured_video_url__regex=r"\S")
        | ~Q(featured_video_file="")
        | Q(blocks__isnull=False)
        | Q(attachments__isnull=False)
    )


def visible_sections(user):
    allowed = allowed_audiences(user)
    if not allowed:
        return []
    sections = list(Section.objects.all())
    by_id = {section.pk: section for section in sections}
    memo = {}

    def can_see(section):
        if section.pk in memo:
            return memo[section.pk]
        if section.audience not in allowed:
            memo[section.pk] = False
            return False
        parent = by_id.get(section.parent_id)
        memo[section.pk] = not section.parent_id or (parent is not None and can_see(parent))
        return memo[section.pk]

    accessible = [section for section in sections if can_see(section)]
    if user.is_authenticated:
        return accessible

    accessible_ids = {section.pk for section in accessible}
    filled_section_ids = Article.objects.filter(
        status=Article.PUBLISHED,
        audience=AUDIENCE_STAFF,
        section_id__in=accessible_ids,
    ).filter(filled_article_filter()).values_list("section_id", flat=True).distinct()
    visible_ids = set()
    for section_id in filled_section_ids:
        while section_id in accessible_ids and section_id not in visible_ids:
            visible_ids.add(section_id)
            section_id = by_id[section_id].parent_id
    return [section for section in accessible if section.pk in visible_ids]


def visible_articles(user, sections=None) -> QuerySet[Article]:
    section_ids = [section.pk for section in (visible_sections(user) if sections is None else sections)]
    if not section_ids:
        return Article.objects.none()
    queryset = Article.objects.filter(
        status=Article.PUBLISHED,
        section_id__in=section_ids,
        audience__in=allowed_audiences(user),
    )
    if not user.is_authenticated:
        queryset = queryset.filter(filled_article_filter()).distinct()
    return queryset.select_related("section")


def navigation_tree(user, sections=None, articles=None):
    sections = visible_sections(user) if sections is None else sections
    articles = (
        list(visible_articles(user, sections).select_related(None).only("id", "title", "slug", "section_id", "position"))
        if articles is None else articles
    )
    nodes = {section.pk: {"section": section, "children": [], "articles": []} for section in sections}
    roots = []
    for section in sections:
        node = nodes[section.pk]
        parent = nodes.get(section.parent_id)
        (parent["children"] if parent else roots).append(node)
    for article in articles:
        if article.section_id in nodes:
            nodes[article.section_id]["articles"].append(article)
    return roots


def editable_section_ids(user):
    if not user.is_authenticated or not user.is_staff:
        return set()
    if user.is_superuser or user.groups.filter(name=GROUP_EDITORS).exists():
        return set(Section.objects.values_list("pk", flat=True))
    if not user.groups.filter(name=GROUP_MANAGERS).exists():
        return set()
    sections = list(Section.objects.values_list("pk", "parent_id", "manager_id"))
    result = {pk for pk, _, manager_id in sections if manager_id == user.pk}
    changed = True
    while changed:
        old_size = len(result)
        result.update(pk for pk, parent_id, _ in sections if parent_id in result)
        changed = len(result) != old_size
    return result
