from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("kb", "0016_article_body_articleinlineimage")]

    operations = [
        migrations.AddField(
            model_name="article",
            name="help_for_service",
            field=models.CharField(
                blank=True, choices=[
                    ("1c", "1С — веб-версия"), ("cis", "CIS"), ("daily-obp", "Daily OBP"),
                    ("abd-schedule", "ABD Schedule"), ("pcms", "PCMS"), ("network-drive", "Сетевой диск"),
                    ("astrum", "Astrum"), ("assai", "Assai"), ("electric-workspace", "Electric Workspace"),
                    ("openproject", "OpenProject"), ("piping-abd", "Piping ABD rev.00"), ("jsr", "JSR"),
                    ("punch-visualisation", "Punch Visualisation"), ("incoming-control", "База входного контроля"),
                    ("request-form", "Форма заведения заявок"), ("camera-department", "Камеральный отдел СС7"),
                    ("electrical-input", "Входной контроль электрика"), ("isolation", "Isolation Изоляция"),
                ],
                help_text="Выберите сервис, если эта статья должна открываться по значку ? и ссылке «Инструкция» на портале.",
                max_length=40, verbose_name="Справка сервиса",
            ),
        ),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(
                condition=~models.Q(help_for_service=""), fields=("help_for_service",),
                name="kb_one_help_article_per_service",
            ),
        ),
    ]
