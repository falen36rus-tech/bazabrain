"""Apply the corrected nesting in points 3, 4 and 5 of Дерево 2.docx.

The original migration remains immutable. Existing article IDs, addresses and
content outside the twenty formerly empty section placeholders are preserved.
"""

import hashlib
import json
from pathlib import Path

from django.db import migrations


SOURCE = Path(__file__).resolve().parents[1] / "data" / "tree_2026_10_01_revision.json"
SOURCE_SHA256 = "841961eed49bfc80aaf942c6b650e5f7812534acb35f0f8176096d87389fac5b"

# (index in the document, original root slug number, new folder slug,
#  original section numbers becoming articles, remaining direct sections)
CHANGES = (
    (2, 54, "tree-section-revision-003", (55, 56), (57, 62, 79, 83)),
    (3, 98, "tree-section-revision-004", tuple(range(99, 110)), ()),
    (4, 110, "tree-section-revision-005", tuple(range(111, 118)), (118, 126, 128, 136, 144, 153)),
)


def apply_revised_tree(apps, schema_editor):
    data = SOURCE.read_bytes()
    # Git checks out text with LF; the source was originally hashed with CRLF.
    normalized = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if hashlib.sha256(normalized).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("The revised tree source changed after the migration was created.")
    roots = json.loads(data.decode("utf-8"))
    Section = apps.get_model("kb", "Section")
    Article = apps.get_model("kb", "Article")
    db_alias = schema_editor.connection.alias

    for root_index, root_number, folder_slug, converted_numbers, remaining_numbers in CHANGES:
        root = Section.objects.using(db_alias).get(slug=f"tree-section-{root_number:03d}")
        source_root = roots[root_index]
        source_folder = source_root["children"][0]
        if len(source_folder["children"]) != len(converted_numbers):
            raise RuntimeError(f"Unexpected revised tree structure under {root.slug}.")

        old_sections = []
        for position, number in enumerate(converted_numbers, start=1):
            section = Section.objects.using(db_alias).get(slug=f"tree-section-{number:03d}")
            source_article = source_folder["children"][position - 1]
            if (
                section.parent_id != root.pk
                or source_article["sibling_order"] != position
            ):
                raise RuntimeError(f"Unexpected source section: {section.slug}.")
            if (
                Section.objects.using(db_alias).filter(parent_id=section.pk).exists()
                or Article.objects.using(db_alias).filter(section_id=section.pk).exists()
            ):
                raise RuntimeError(
                    f"Section {section.slug} contains manually added pages. "
                    "Move them before applying the revised tree."
                )
            old_sections.append(section)

        folder = Section.objects.using(db_alias).create(
            slug=folder_slug,
            title=source_folder["title"],
            parent_id=root.pk,
            audience=root.audience,
            position=source_folder["sibling_order"],
        )
        for position, (number, old_section) in enumerate(zip(converted_numbers, old_sections), start=1):
            Article.objects.using(db_alias).create(
                slug=f"tree-article-{number:03d}",
                title=old_section.title,
                summary=old_section.description,
                section_id=folder.pk,
                audience=old_section.audience,
                status="published",
                position=position,
            )
            old_section.delete(using=db_alias)

        for position, number in enumerate(remaining_numbers, start=2):
            section = Section.objects.using(db_alias).get(slug=f"tree-section-{number:03d}")
            if section.parent_id != root.pk:
                raise RuntimeError(f"Unexpected parent for {section.slug}.")
            Section.objects.using(db_alias).filter(pk=section.pk).update(position=position)


class Migration(migrations.Migration):
    dependencies = [("kb", "0004_initial_document_tree")]
    operations = [migrations.RunPython(apply_revised_tree, migrations.RunPython.noop)]
