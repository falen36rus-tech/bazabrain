"""The single visibility rule used by pages, search and private files."""

from django.db.models import QuerySet

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
        return set()
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

    return [section for section in sections if can_see(section)]


def visible_articles(user, sections=None) -> QuerySet[Article]:
    section_ids = [section.pk for section in (visible_sections(user) if sections is None else sections)]
    if not section_ids:
        return Article.objects.none()
    return Article.objects.filter(
        status=Article.PUBLISHED,
        section_id__in=section_ids,
        audience__in=allowed_audiences(user),
    ).select_related("section")


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
