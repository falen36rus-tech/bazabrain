"""Create an independent article in another section, including its content."""

from django.db import transaction

from .models import (
    AUDIENCE_STAFF, Article, Attachment, ContentBlock, Section,
)


def source_audience(article: Article):
    """Keep restrictions inherited from the original section hierarchy."""
    restrictions = {article.audience} - {AUDIENCE_STAFF}
    section = article.section
    while section is not None:
        restrictions.add(section.audience)
        section = section.parent
    restrictions.discard(AUDIENCE_STAFF)
    if len(restrictions) > 1:
        raise ValueError("Исходная статья совмещает разные ограничения доступа и не может быть безопасно скопирована.")
    return next(iter(restrictions), AUDIENCE_STAFF)


@transaction.atomic
def copy_article_to_section(source: Article, destination: Section, actor) -> Article:
    if destination.service_slug != "1c" or destination.catalog != "discipline":
        raise ValueError("Статью можно скопировать только в дисциплину 1С.")
    audience = source_audience(source)

    copy = Article.objects.create(
        section=destination,
        title=source.title,
        summary=source.summary,
        summary_is_rich=source.summary_is_rich,
        title_alignment=source.title_alignment,
        title_size=source.title_size,
        title_bold=source.title_bold,
        title_italic=source.title_italic,
        featured_video_url=source.featured_video_url,
        featured_video_file=source.featured_video_file.name,
        network_video_path=source.network_video_path,
        audience=audience,
        status=source.status,
        position=source.position,
        created_by=actor,
        updated_by=actor,
    )
    ContentBlock.objects.bulk_create([
        ContentBlock(
            article=copy,
            kind=block.kind,
            position=block.position,
            text=block.text,
            text_is_rich=block.text_is_rich,
            image=block.image.name,
            gallery_id=block.gallery_id,
            display_width=block.display_width,
            video_url=block.video_url,
            caption=block.caption,
        )
        for block in source.blocks.all()
    ])
    Attachment.objects.bulk_create([
        Attachment(
            article=copy,
            title=attachment.title,
            file=attachment.file.name,
            original_filename=attachment.original_filename,
            position=attachment.position,
        )
        for attachment in source.attachments.all()
    ])
    copy.rebuild_search_text()
    return copy
