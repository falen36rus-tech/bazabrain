"""Keep the search index current when article blocks change."""

from django.db.models.signals import post_delete, post_save
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
