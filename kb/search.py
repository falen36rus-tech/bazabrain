"""Search is always applied after article visibility filtering."""

from django.db import connection
from django.db.models import Q

from .access import visible_articles, visible_sections


def search_articles(user, raw_query, limit=40):
    query = " ".join(raw_query.strip().split())[:160]
    if not query:
        return []
    queryset = visible_articles(user)
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity
        from django.db.models import ExpressionWrapper, F, FloatField, Value

        vector = SearchVector("title", "summary", "search_text", config="russian")
        needle = SearchQuery(query, config="russian", search_type="websearch")
        return list(
            queryset.annotate(
                search_vector=vector,
                rank=SearchRank(vector, needle),
                similarity=TrigramSimilarity("title", query),
            )
            .filter(Q(search_vector=needle) | Q(title__trigram_similar=query) | Q(section__title__icontains=query))
            .annotate(score=ExpressionWrapper(F("rank") + F("similarity") * Value(0.25), output_field=FloatField()))
            .order_by("-score", "title")[:limit]
        )

    # The small SQLite demo lacks Russian stemming; casefold in Python is reliable.
    terms = query.casefold().split()
    ranked = []
    for article in queryset:
        title = article.title.casefold()
        summary = article.summary.casefold()
        body = article.search_text.casefold()
        section = article.section.title.casefold()
        if not all(any(term in field for field in (title, summary, body, section)) for term in terms):
            continue
        score = sum(10 * (term in title) + 4 * (term in section) + 3 * (term in summary) + (term in body) for term in terms)
        ranked.append((score, article))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
    return [article for _, article in ranked[:limit]]


def search_sections(user, raw_query, limit=20):
    query = " ".join(raw_query.strip().split())[:160]
    if not query:
        return []
    terms = query.casefold().split()
    ranked = []
    for section in visible_sections(user):
        title = section.title.casefold()
        description = section.description.casefold()
        if not all(term in title or term in description for term in terms):
            continue
        score = sum(5 * (term in title) + (term in description) for term in terms)
        ranked.append((score, section))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
    return [section for _, section in ranked[:limit]]
