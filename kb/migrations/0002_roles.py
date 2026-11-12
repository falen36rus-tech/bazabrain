from django.db import migrations


def create_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.using(schema_editor.connection.alias).get_or_create(name="Руководители")
    Group.objects.using(schema_editor.connection.alias).get_or_create(name="Разработчики")


class Migration(migrations.Migration):
    dependencies = [("kb", "0001_initial"), ("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(create_roles, migrations.RunPython.noop)]
