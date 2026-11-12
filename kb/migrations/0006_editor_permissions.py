"""Allow named staff editors to manage all knowledge-base material."""

from django.db import migrations


EDITOR_PERMISSIONS = {
    "section": ("view", "add", "change"),
    "article": ("view", "add", "change"),
    "contentblock": ("view", "add", "change", "delete"),
    "attachment": ("view", "add", "change", "delete"),
}


def create_editor_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    db_alias = schema_editor.connection.alias
    group, _ = Group.objects.using(db_alias).get_or_create(name="Редакторы")

    for model_name, actions in EDITOR_PERMISSIONS.items():
        content_type, _ = ContentType.objects.using(db_alias).get_or_create(
            app_label="kb", model=model_name
        )
        for action in actions:
            permission, _ = Permission.objects.using(db_alias).get_or_create(
                content_type=content_type,
                codename=f"{action}_{model_name}",
                defaults={"name": f"Can {action} {model_name}"},
            )
            group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("kb", "0005_revised_document_tree")]
    operations = [migrations.RunPython(create_editor_group, migrations.RunPython.noop)]
