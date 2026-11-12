from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Article, Attachment, ContentBlock


def refresh_article_index(article_id):
    article = Article.objects.filter(pk=article_id).first()
    if article is not None:
        article.rebuild_search_text()


@receiver(post_save, sender=ContentBlock)
@receiver(post_delete, sender=ContentBlock)
@receiver(post_save, sender=Attachment)
@receiver(post_delete, sender=Attachment)
def update_search_after_content_change(sender, instance, **kwargs):
    refresh_article_index(instance.article_id)


def schedule_delete(storage, name):
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@receiver(pre_save, sender=ContentBlock)
@receiver(pre_save, sender=Attachment)
def remember_replaced_file(sender, instance, **kwargs):
    if not instance.pk:
        return
    field = "image" if sender is ContentBlock else "file"
    old_name = sender.objects.filter(pk=instance.pk).values_list(field, flat=True).first()
    new_name = getattr(instance, field).name
    instance._replaced_file = old_name if old_name and old_name != new_name else None


@receiver(post_save, sender=ContentBlock)
@receiver(post_save, sender=Attachment)
def delete_replaced_file(sender, instance, **kwargs):
    old_name = getattr(instance, "_replaced_file", None)
    if old_name:
        field = instance.image if sender is ContentBlock else instance.file
        schedule_delete(field.storage, old_name)


@receiver(post_delete, sender=ContentBlock)
@receiver(post_delete, sender=Attachment)
def delete_removed_file(sender, instance, **kwargs):
    field = instance.image if sender is ContentBlock else instance.file
    if field:
        schedule_delete(field.storage, field.name)
