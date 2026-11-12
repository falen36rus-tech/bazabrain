"""A narrow, safe HTML subset for editor-written knowledge-base text."""

from html import unescape
from html.parser import HTMLParser

import nh3


TAGS = {"p", "br", "strong", "em", "u", "span"}
CLASSES = {
    "p": {"ql-align-center", "ql-align-right", "ql-align-justify"},
    "span": {"ql-size-small", "ql-size-large", "ql-size-huge"},
}


def clean_rich_html(value):
    return nh3.clean(
        value or "",
        tags=TAGS,
        attributes={},
        allowed_classes=CLASSES,
        clean_content_tags={"script", "style", "iframe", "svg", "math"},
    )


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
