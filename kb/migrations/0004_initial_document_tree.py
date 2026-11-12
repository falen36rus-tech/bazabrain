"""Initial section and article titles from the user's 1C tree document.

The source JSON is immutable for this migration. Later editorial changes in the
admin are not overwritten by server restarts or subsequent migrations.
"""

import hashlib
import json
from pathlib import Path

from django.db import migrations


SOURCE = Path(__file__).resolve().parents[1] / "data" / "tree_2026_10_01.json"
SOURCE_SHA256 = "d3f2bdb4f26fbe5f0c54ae818552a5b71c488b229b87ec1512ecedcc7e37a031"


def add_tree(apps, schema_editor):
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("The initial tree source changed after the migration was created.")
    roots = json.loads(data.decode("utf-8"))
    Section = apps.get_model("kb", "Section")
    Article = apps.get_model("kb", "Article")
    db_alias = schema_editor.connection.alias
    imported = set()

    def walk(nodes, parent=None):
        for node in nodes:
            order = int(node["order"])
            level = int(node["level"])
            if order in imported:
                raise RuntimeError(f"Duplicate initial tree position: {order}")
            imported.add(order)
            if level in (0, 1):
                section, _ = Section.objects.using(db_alias).get_or_create(
                    slug=f"tree-section-{order:03d}",
                    defaults={
                        "title": node["title"],
                        "parent_id": parent.pk if parent else None,
                        "audience": "staff",
                        "position": int(node["sibling_order"]),
                    },
                )
                walk(node["children"], section)
            elif level == 2:
                if parent is None or node["children"]:
                    raise RuntimeError(f"Invalid article position in initial tree: {order}")
                Article.objects.using(db_alias).get_or_create(
                    slug=f"tree-article-{order:03d}",
                    defaults={
                        "title": node["title"],
                        "section_id": parent.pk,
                        "audience": "staff",
                        "status": "published",
                        "position": int(node["sibling_order"]),
                    },
                )
            else:
                raise RuntimeError(f"Unexpected initial tree level: {level}")

    walk(roots)
    if imported != set(range(1, 345)):
        raise RuntimeError("The initial tree must contain all 344 ordered items.")


class Migration(migrations.Migration):
    dependencies = [("kb", "0003_postgres_search")]
    operations = [migrations.RunPython(add_tree, migrations.RunPython.noop)]
