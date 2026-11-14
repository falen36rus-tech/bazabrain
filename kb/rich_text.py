"""A narrow, safe HTML subset for editor-written knowledge-base text."""

from html import unescape
from html.parser import HTMLParser
import re

import nh3


TAGS = {"p", "br", "strong", "em", "u", "span"}
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


def clean_rich_html(value):
    cleaned = nh3.clean(
        value or "",
        tags=TAGS,
        attributes={},
        allowed_classes=CLASSES,
        clean_content_tags={"script", "style", "iframe", "svg", "math"},
    )
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

    def handle_data(self, data):
        self.parts.append(data)


def rich_plain_text(value):
    parser = _TextExtractor()
    parser.feed(clean_rich_html(value))
    return unescape("".join(parser.parts)).strip()
