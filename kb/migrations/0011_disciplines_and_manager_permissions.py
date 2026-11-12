from django.db import migrations


DISCIPLINES = (
    ("discipline-construction", "Общестроительные работы"),
    ("discipline-steel", "Металлоконструкции"),
    ("discipline-equipment", "Оборудование"),
    ("discipline-pipelines", "Трубопроводы"),
    ("discipline-electrical", "Электрика"),
    ("discipline-instrumentation", "КИПиА"),
    ("discipline-networks", "Инженерные сети"),
)


def prepare_catalog(apps, schema_editor):
    Section = apps.get_model("kb", "Section")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    db = schema_editor.connection.alias
    for position, (slug, title) in enumerate(DISCIPLINES, 1):
        Section.objects.using(db).get_or_create(
            slug=slug,
            defaults={"title": title, "service_slug": "1c", "catalog": "discipline", "position": position * 10},
        )
    group, _ = Group.objects.using(db).get_or_create(name="Руководители")
    Group.objects.using(db).get_or_create(name="Пользователи базы знаний")
    for model_name, actions in {
        "section": ("view", "change"),
        "article": ("view", "add", "change"),
        "contentblock": ("view", "add", "change", "delete"),
        "attachment": ("view", "add", "change", "delete"),
    }.items():
        content_type = ContentType.objects.using(db).get(app_label="kb", model=model_name)
        for action in actions:
            permission = Permission.objects.using(db).get(content_type=content_type, codename=f"{action}_{model_name}")
            group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("kb", "0010_section_catalog_section_manager_section_service_slug")]
    operations = [migrations.RunPython(prepare_catalog, migrations.RunPython.noop)]
