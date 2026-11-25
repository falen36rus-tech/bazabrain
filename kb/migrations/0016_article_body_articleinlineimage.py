from django.db import migrations, models
import django.db.models.deletion
import kb.models


class Migration(migrations.Migration):
    dependencies = [("kb", "0015_article_created_by_article_updated_by")]

    operations = [
        migrations.AddField(model_name="article", name="body", field=models.TextField(blank=True, verbose_name="Содержимое статьи")),
        migrations.AddField(model_name="article", name="body_is_rich", field=models.BooleanField(default=False, editable=False)),
        migrations.CreateModel(
            name="ArticleInlineImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to=kb.models.image_upload_path, validators=[kb.models.validate_upload_size])),
                ("article", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inline_images", to="kb.article")),
            ],
        ),
    ]
