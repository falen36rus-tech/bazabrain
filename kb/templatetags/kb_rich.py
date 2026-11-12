from django import template
from django.utils.html import linebreaks
from django.utils.safestring import mark_safe

from kb.rich_text import clean_rich_html, rich_plain_text


register = template.Library()


@register.filter
def rich_content(value, is_rich):
    if is_rich:
        return mark_safe(clean_rich_html(value))
    return mark_safe(linebreaks(value or "", autoescape=True))


@register.filter
def plain_excerpt(value, is_rich):
    return " ".join((rich_plain_text(value) if is_rich else value or "").split())
