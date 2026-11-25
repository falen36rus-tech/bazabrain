"""A narrow, safe HTML subset for editor-written knowledge-base text."""

from html import unescape
from html.parser import HTMLParser
import re

import nh3


TAGS = {"p", "br", "strong", "em", "u", "span"}
TABLE_TAGS = {"table", "thead", "tbody", "tr", "th", "td"}
_PRIVATE_IMAGE = re.compile(r'^/private/article-image/[0-9]+/$')
CLASSES = {
    "p": {"ql-align-center", "ql-align-right", "ql-align-justify"},
    "span": {"ql-size-small", "ql-size-large", "ql-size-huge"},
}

# Quill can split a uniformly sized paragraph when bold is applied, leaving
# the bold run without its size span. Restore that size when both neighbours
# explicitly use the same size.
_SIZED_BOLD_GAP = re.compile(
    r'(?P<left><span class="ql-size-(?P<size>small|large|huge)">[^<]*</span>)'
    r'(?P<bold><strong>[^<]*</strong>)'
    r'(?P<right><span class="ql-size-(?P=size)">)'
)


def clean_rich_html(value, allow_images=False, allow_tables=False):
    cleaned = nh3.clean(
        value or "",
        tags=TAGS | ({"img"} if allow_images else set()) | (TABLE_TAGS if allow_tables else set()),
        attributes={
            **({"img": {"src", "alt"}} if allow_images else {}),
            **({"td": {"data-row"}} if allow_tables else {}),
        },
        allowed_classes=CLASSES,
        clean_content_tags={"script", "style", "iframe", "svg", "math"},
    )
    if allow_images:
        cleaned = re.sub(r'<img\b[^>]*>', lambda match: match.group(0) if any(
            _PRIVATE_IMAGE.fullmatch(src) for src in re.findall(r'\bsrc="([^"]*)"', match.group(0))
        ) else '', cleaned)
    while True:
        normalized = _SIZED_BOLD_GAP.sub(
            lambda match: (
                match.group("left")
                + f'<span class="ql-size-{match.group("size")}">{match.group("bold")}</span>'
                + match.group("right")
            ),
            cleaned,
        )
        if normalized == cleaned:
            return cleaned
        cleaned = normalized


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "p":
            self.parts.append("\n")
        elif tag in {"th", "td"}:
            self.parts.append(" ")
        elif tag == "tr":
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def rich_plain_text(value):
    parser = _TextExtractor()
    parser.feed(clean_rich_html(value, allow_tables=True))
    return unescape("".join(parser.parts)).strip()
