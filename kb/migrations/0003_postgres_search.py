from django.db import migrations


def add_search_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    schema_editor.execute(
        "CREATE INDEX IF NOT EXISTS kb_article_fts_gin ON kb_article USING GIN "
        "(to_tsvector('russian', coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(search_text, '')))"
    )
    schema_editor.execute("CREATE INDEX IF NOT EXISTS kb_article_title_trgm ON kb_article USING GIN (title gin_trgm_ops)")


def remove_search_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("DROP INDEX IF EXISTS kb_article_title_trgm")
    schema_editor.execute("DROP INDEX IF EXISTS kb_article_fts_gin")


class Migration(migrations.Migration):
    dependencies = [("kb", "0002_roles")]
    operations = [migrations.RunPython(add_search_indexes, remove_search_indexes)]
