from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("kb", "0017_article_help_for_service")]

    operations = [
        migrations.AlterField(
            model_name="article",
            name="section",
            field=models.ForeignKey(
                blank=True,
                help_text="Для общей справки сервиса оставьте пустым.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="articles",
                to="kb.section",
                verbose_name="Раздел",
            ),
        ),
    ]
