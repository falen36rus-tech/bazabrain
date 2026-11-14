"""Behavioral checks for visibility and the RUTUBE embed boundary."""

import json
import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from reversion.models import Version
from PIL import Image

from .access import visible_articles, visible_sections
from .models import (
    AUDIENCE_DEVELOPER,
    AUDIENCE_MANAGER,
    AUDIENCE_STAFF,
    GROUP_DEVELOPERS,
    GROUP_EDITORS,
    GROUP_MANAGERS,
    Article,
    Attachment,
    ContentBlock,
    Section,
)
from .rutube import embed_url
from .rich_text import clean_rich_html, rich_plain_text
from .admin_rich import ArticleRichForm, ContentBlockRichForm, SectionRichForm


@override_settings(SECURE_SSL_REDIRECT=False)
class KnowledgeBaseAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Keep this access matrix independent of the imported navigation tree.
        Article.objects.all().delete()
        Section.objects.filter(parent__isnull=False).delete()
        Section.objects.filter(parent__isnull=True).delete()
        user_model = get_user_model()
        cls.staff = user_model.objects.create_user("employee", password="example-password")
        cls.manager = user_model.objects.create_user("manager", password="example-password")
        cls.developer = user_model.objects.create_user("developer", password="example-password")
        cls.editor = user_model.objects.create_user("editor", password="example-password", is_staff=True)
        cls.owner = user_model.objects.create_superuser("owner", "owner@example.com", "example-password")
        cls.manager.groups.add(Group.objects.get_or_create(name=GROUP_MANAGERS)[0])
        cls.developer.groups.add(Group.objects.get_or_create(name=GROUP_DEVELOPERS)[0])
        cls.editor.groups.add(Group.objects.get(name=GROUP_EDITORS))

        cls.public_section = Section.objects.create(
            title="Общие инструкции", slug="general", audience=AUDIENCE_STAFF
        )
        cls.manager_section = Section.objects.create(
            title="Закрытый отдел руководителей", slug="management", audience=AUDIENCE_MANAGER
        )
        cls.developer_section = Section.objects.create(
            title="Закрытый отдел разработчиков", slug="development", audience=AUDIENCE_DEVELOPER
        )
        cls.nested_section = Section.objects.create(
            title="Дочерний раздел разработчиков", slug="development-child",
            parent=cls.developer_section, audience=AUDIENCE_STAFF,
        )

        def article(title, slug, section, audience=AUDIENCE_STAFF, status=Article.PUBLISHED):
            return Article.objects.create(
                title=title, slug=slug, section=section, audience=audience,
                status=status, summary=f"Справка: {title}", search_text=f"Маркер: {title}",
            )

        cls.public_article = article("Маркер общая инструкция", "public-guide", cls.public_section)
        cls.manager_article = article("Маркер инструкция руководителя", "manager-guide", cls.manager_section)
        cls.developer_article = article("Маркер инструкция разработчика", "developer-guide", cls.developer_section)
        cls.nested_article = article("Маркер дочерняя инструкция", "nested-guide", cls.nested_section)
        cls.manager_in_public = article(
            "Маркер закрытая статья руководителя", "manager-in-public", cls.public_section,
            AUDIENCE_MANAGER,
        )
        cls.developer_in_public = article(
            "Маркер закрытая статья разработчика", "developer-in-public", cls.public_section,
            AUDIENCE_DEVELOPER,
        )
        cls.draft = article(
            "Маркер неопубликованный черновик", "draft-guide", cls.public_section,
            status=Article.DRAFT,
        )

    def assert_visible_everywhere(self, user, expected_articles, expected_sections):
        self.client.force_login(user)
        expected_slugs = {article.slug for article in expected_articles}
        expected_section_slugs = {section.slug for section in expected_sections}

        self.assertSetEqual(
            {article.slug for article in visible_articles(user)}, expected_slugs
        )
        self.assertSetEqual(
            {section.slug for section in visible_sections(user)}, expected_section_slugs
        )

        home = self.client.get(reverse("kb:home"))
        self.assertEqual(home.status_code, 200)
        for section in (
            self.public_section, self.manager_section, self.developer_section,
            self.nested_section,
        ):
            section_url = reverse("kb:section", args=[section.slug])
            if section.slug in expected_section_slugs:
                self.assertContains(home, section.title)
                self.assertEqual(self.client.get(section_url).status_code, 200)
            else:
                self.assertNotContains(home, section.title)
                self.assertEqual(self.client.get(section_url).status_code, 404)

        search = self.client.get(reverse("kb:search"), {"q": "Маркер"})
        self.assertEqual(search.status_code, 200)
        self.assertSetEqual(
            {article.slug for article in search.context["search_results"]}, expected_slugs
        )

        suggestions = self.client.get(reverse("kb:suggest"), {"q": "Маркер"})
        self.assertEqual(suggestions.status_code, 200)
        self.assertSetEqual(
            {item["url"] for item in suggestions.json()["results"]},
            {reverse("kb:article", args=[slug]) for slug in expected_slugs},
        )

        for article in (
            self.public_article, self.manager_article, self.developer_article,
            self.nested_article, self.manager_in_public, self.developer_in_public,
            self.draft,
        ):
            if article.slug in expected_slugs:
                self.assertContains(home, article.title)
            else:
                self.assertNotContains(home, article.title)
            article_url = reverse("kb:article", args=[article.slug])
            expected_status = 200 if article.slug in expected_slugs else 404
            self.assertEqual(
                self.client.get(article_url).status_code, expected_status,
                f"Wrong visibility for {user.username}: {article.slug}",
            )

    def test_employee_cannot_see_manager_or_developer_material(self):
        self.assert_visible_everywhere(
            self.staff,
            [self.public_article],
            [self.public_section],
        )

    def test_guest_sees_only_filled_permitted_material_and_can_sign_in(self):
        empty_section = Section.objects.create(title="Пустой раздел", slug="empty-section")
        empty_article = Article.objects.create(
            title="Пустая статья", slug="empty-article", section=empty_section,
            status=Article.PUBLISHED,
        )
        restricted_section = Section.objects.create(
            title="Закрытый родитель", slug="restricted-parent", audience=AUDIENCE_MANAGER,
        )
        restricted_child = Section.objects.create(
            title="Открытый дочерний раздел", slug="restricted-child",
            parent=restricted_section, audience=AUDIENCE_STAFF,
        )
        restricted_child_article = Article.objects.create(
            title="Заполненная статья под закрытым родителем", slug="restricted-child-article",
            section=restricted_child, status=Article.PUBLISHED, summary="Есть содержимое",
        )
        self.client.logout()
        home = self.client.get(reverse("kb:home"))
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, self.public_section.title)
        self.assertNotContains(home, empty_section.title)
        self.assertNotContains(home, restricted_child.title)
        self.assertSetEqual(
            {section.slug for section in visible_sections(self.client.get("/").wsgi_request.user)},
            {self.public_section.slug},
        )
        self.assertEqual(self.client.get(self.public_article.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(empty_section.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(empty_article.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(restricted_child_article.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(self.manager_article.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(self.developer_article.get_absolute_url()).status_code, 404)
        self.assertContains(home, "Войти")
        search = self.client.get(reverse("kb:search"), {"q": "Пустая"})
        self.assertNotContains(search, empty_article.title)
        suggestions = self.client.get(reverse("kb:suggest"), {"q": "Пустая"})
        self.assertEqual(suggestions.json()["results"], [])

    def test_regular_user_has_no_edit_controls(self):
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(self.public_article.get_absolute_url()), "Редактировать")
        self.assertEqual(self.client.get(reverse("admin:kb_article_change", args=[self.public_article.pk])).status_code, 302)

    def test_manager_edits_only_assigned_section(self):
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        self.public_section.manager = self.manager
        self.public_section.save(update_fields=["manager"])
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("admin:kb_section_change", args=[self.public_section.pk])).status_code, 200)
        self.assertNotEqual(self.client.get(reverse("admin:kb_section_change", args=[self.manager_section.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:kb_article_change", args=[self.public_article.pk])).status_code, 200)
        self.assertNotEqual(self.client.get(reverse("admin:kb_article_change", args=[self.manager_article.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:kb_section_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:kb_article_add")).status_code, 200)
        self.assertContains(self.client.get(self.public_article.get_absolute_url()), "Редактировать")
        self.assertNotContains(self.client.get(self.manager_article.get_absolute_url()), "Редактировать")
        response = self.client.post(reverse("admin:kb_article_change", args=[self.public_article.pk]), {
            "section": self.manager_section.pk, "title": self.public_article.title,
            "slug": self.public_article.slug, "summary": self.public_article.summary,
            "title_size": "normal", "title_alignment": "left", "title_bold": "on",
            "audience": AUDIENCE_STAFF, "status": Article.PUBLISHED, "position": 0,
            "blocks-TOTAL_FORMS": 0, "blocks-INITIAL_FORMS": 0,
            "blocks-MIN_NUM_FORMS": 0, "blocks-MAX_NUM_FORMS": 1000,
            "attachments-TOTAL_FORMS": 0, "attachments-INITIAL_FORMS": 0,
            "attachments-MIN_NUM_FORMS": 0, "attachments-MAX_NUM_FORMS": 1000,
        })
        self.assertEqual(response.status_code, 200)
        self.public_article.refresh_from_db()
        self.assertEqual(self.public_article.section_id, self.public_section.pk)

    def test_admin_logout_returns_to_public_site(self):
        self.client.force_login(self.owner)
        response = self.client.post("/admin/logout/")
        self.assertRedirects(response, "/")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertContains(self.client.get("/"), "Войти")

    def test_manager_cannot_see_developer_material(self):
        self.assert_visible_everywhere(
            self.manager,
            [self.public_article, self.manager_article, self.manager_in_public],
            [self.public_section, self.manager_section],
        )

    def test_developer_cannot_see_manager_material(self):
        self.assert_visible_everywhere(
            self.developer,
            [self.public_article, self.developer_article, self.nested_article,
             self.developer_in_public],
            [self.public_section, self.developer_section, self.nested_section],
        )

    def test_draft_stays_out_of_public_views_even_for_owner(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.draft.get_absolute_url()).status_code, 404)
        search = self.client.get(reverse("kb:search"), {"q": "неопубликованный"})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(list(search.context["search_results"]), [])
        suggestions = self.client.get(reverse("kb:suggest"), {"q": "неопубликованный"})
        self.assertEqual(suggestions.status_code, 200)
        self.assertEqual(suggestions.json()["results"], [])

    def test_multiline_summary_keeps_steps_readable_without_empty_message(self):
        self.public_article.summary = "1. Первый шаг\n\n2. Второй шаг\nСледующая строка"
        self.public_article.save(update_fields=["summary"])
        self.client.force_login(self.staff)
        response = self.client.get(self.public_article.get_absolute_url())
        self.assertContains(response, "<p>1. Первый шаг</p>", html=True)
        self.assertContains(response, "<p>2. Второй шаг<br>Следующая строка</p>", html=True)
        self.assertNotContains(response, "Материал пока не заполнен")

    def test_multiline_section_description_keeps_paragraphs(self):
        self.public_section.description = "Первый абзац\n\nВторой абзац\nСледующая строка"
        self.public_section.save(update_fields=["description"])
        self.client.force_login(self.staff)
        response = self.client.get(self.public_section.get_absolute_url())
        self.assertContains(response, "<p>Первый абзац</p>", html=True)
        self.assertContains(response, "<p>Второй абзац<br>Следующая строка</p>", html=True)

    def test_featured_rutube_video_appears_directly_under_article_title(self):
        video_id = "0123456789abcdef0123456789abcdef"
        self.public_article.featured_video_url = f"https://rutube.ru/video/{video_id}/"
        self.public_article.save(update_fields=["featured_video_url"])
        self.client.force_login(self.staff)
        response = self.client.get(self.public_article.get_absolute_url())
        content = response.content.decode()
        embed_url = f"https://rutube.ru/play/embed/{video_id}/"
        self.assertIn(embed_url, content)
        self.assertLess(content.index('id="article-title"'), content.index(embed_url))
        self.assertLess(content.index(embed_url), content.index('class="article-summary"'))
        self.assertNotContains(response, "Материал пока не заполнен")

    def test_uploaded_video_player_and_authenticated_range_access(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.public_article.featured_video_file = SimpleUploadedFile(
                "guide.mp4", b"0123456789", content_type="video/mp4",
            )
            self.public_article.save(update_fields=["featured_video_file"])
            page = self.client.get(self.public_article.get_absolute_url())
            video_url = reverse("kb:private_video", args=[self.public_article.pk])
            self.assertContains(page, f'<source src="{video_url}" type="video/mp4">', html=True)
            self.assertEqual(b"".join(self.client.get(video_url).streaming_content), b"0123456789")
            part = self.client.get(video_url, HTTP_RANGE="bytes=2-5")
            self.assertEqual(part.status_code, 206)
            self.assertEqual(part["Content-Range"], "bytes 2-5/10")
            self.assertEqual(b"".join(part.streaming_content), b"2345")
            self.assertEqual(self.client.get(video_url, HTTP_RANGE="bytes=99-").status_code, 416)
            self.client.force_login(self.staff)
            self.assertEqual(self.client.get(video_url, HTTP_RANGE="bytes=-3").status_code, 206)
            self.client.logout()
            self.manager_article.featured_video_file = SimpleUploadedFile(
                "secret.mp4", b"secret", content_type="video/mp4",
            )
            self.manager_article.save(update_fields=["featured_video_file"])
            self.assertEqual(self.client.get(reverse("kb:private_video", args=[self.manager_article.pk])).status_code, 404)

    def test_uploaded_video_validates_type_and_size(self):
        self.public_article.featured_video_file = SimpleUploadedFile("bad.exe", b"x")
        with self.assertRaises(ValidationError):
            self.public_article.full_clean()
        with override_settings(MAX_VIDEO_UPLOAD_BYTES=2):
            self.public_article.featured_video_file = SimpleUploadedFile("large.mp4", b"123")
            with self.assertRaises(ValidationError):
                self.public_article.full_clean()

    def test_network_video_is_listed_and_streamed_only_for_allowed_articles(self):
        with tempfile.TemporaryDirectory() as library, override_settings(VIDEO_LIBRARY_ROOT=library):
            Path(library, "guide.mp4").write_bytes(b"0123456789")
            Path(library, "notes.txt").write_text("not a video")
            self.assertIn(("guide.mp4", "guide.mp4"), ArticleRichForm().fields["network_video_path"].choices)
            self.assertNotIn(("notes.txt", "notes.txt"), ArticleRichForm().fields["network_video_path"].choices)
            self.public_article.network_video_path = "guide.mp4"
            self.public_article.save(update_fields=["network_video_path"])
            video_url = reverse("kb:private_video", args=[self.public_article.pk])
            self.assertContains(self.client.get(self.public_article.get_absolute_url()), video_url)
            part = self.client.get(video_url, HTTP_RANGE="bytes=2-5")
            self.assertEqual(part.status_code, 206)
            self.assertEqual(b"".join(part.streaming_content), b"2345")
            self.manager_article.network_video_path = "guide.mp4"
            self.manager_article.save(update_fields=["network_video_path"])
            self.assertEqual(self.client.get(reverse("kb:private_video", args=[self.manager_article.pk])).status_code, 404)

    def test_network_video_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as library, override_settings(VIDEO_LIBRARY_ROOT=library):
            self.public_article.network_video_path = "../outside.mp4"
            with self.assertRaises(ValidationError):
                self.public_article.full_clean()

    def test_featured_video_rejects_non_rutube_links(self):
        self.public_article.featured_video_url = (
            "https://rutube.ru.evil.example/video/0123456789abcdef0123456789abcdef/"
        )
        with self.assertRaises(ValidationError) as error:
            self.public_article.full_clean()
        self.assertIn("featured_video_url", error.exception.message_dict)

    def test_editor_can_read_all_audiences_but_not_drafts_on_site(self):
        self.assert_visible_everywhere(
            self.editor,
            [self.public_article, self.manager_article, self.developer_article,
             self.nested_article, self.manager_in_public, self.developer_in_public],
            [self.public_section, self.manager_section, self.developer_section,
             self.nested_section],
        )

    def test_editor_can_edit_materials_with_history_but_not_manage_users(self):
        self.client.force_login(self.editor)
        article_url = reverse("admin:kb_article_change", args=[self.public_article.pk])
        section_url = reverse("admin:kb_section_change", args=[self.public_section.pk])
        self.assertEqual(self.client.get(article_url).status_code, 200)
        self.assertEqual(self.client.get(section_url).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:kb_article_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:kb_section_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:auth_user_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:kb_article_delete", args=[self.public_article.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:kb_section_delete", args=[self.public_section.pk])).status_code, 403)

        response = self.client.post(article_url, {
            "section": self.public_section.pk,
            "title": "Маркер обновлённая инструкция",
            "slug": self.public_article.slug,
            "summary": "Исправлено редактором",
            "title_size": "normal",
            "title_alignment": "left",
            "title_bold": "on",
            "audience": AUDIENCE_STAFF,
            "status": Article.PUBLISHED,
            "position": 0,
            "blocks-TOTAL_FORMS": 1,
            "blocks-INITIAL_FORMS": 0,
            "blocks-MIN_NUM_FORMS": 0,
            "blocks-MAX_NUM_FORMS": 1000,
            "blocks-0-position": 0,
            "blocks-0-kind": ContentBlock.TEXT,
            "blocks-0-text": "Новый текст инструкции",
            "blocks-0-display_width": 100,
            "attachments-TOTAL_FORMS": 0,
            "attachments-INITIAL_FORMS": 0,
            "attachments-MIN_NUM_FORMS": 0,
            "attachments-MAX_NUM_FORMS": 1000,
        })
        self.assertEqual(response.status_code, 302, response.context)
        self.public_article.refresh_from_db()
        self.assertEqual(self.public_article.summary, "Исправлено редактором")
        self.assertIn("Новый текст инструкции", self.public_article.search_text)
        self.assertEqual(Version.objects.get_for_object(self.public_article).count(), 1)
        block = self.public_article.blocks.get()
        self.assertEqual(Version.objects.get_for_object(block).count(), 1)
        history_url = reverse("admin:kb_article_history", args=[self.public_article.pk])
        self.assertEqual(self.client.get(history_url).status_code, 200)

    def test_replaced_files_remain_available_for_revision_recovery(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            block = ContentBlock.objects.create(
                article=self.public_article,
                kind=ContentBlock.IMAGE,
                image=SimpleUploadedFile("first.png", b"first", content_type="image/png"),
            )
            first_path = Path(block.image.path)
            block.image = SimpleUploadedFile("second.png", b"second", content_type="image/png")
            block.save()
            self.assertTrue(first_path.exists())
            second_path = Path(block.image.path)
            block.delete()
            self.assertTrue(second_path.exists())

    def test_private_image_and_attachment_require_article_access(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = ContentBlock.objects.create(
                article=self.developer_article,
                kind=ContentBlock.IMAGE,
                image=SimpleUploadedFile("capture.png", b"\x89PNG\r\n\x1a\ncontent", content_type="image/png"),
            )
            attachment = Attachment.objects.create(
                article=self.developer_article,
                title="Закрытый файл",
                file=SimpleUploadedFile("specification.txt", b"developer-only"),
            )
            urls = (
                reverse("kb:private_file", args=[image.pk]),
                reverse("kb:private_attachment", args=[attachment.pk]),
            )
            for user in (self.staff, self.manager):
                self.client.force_login(user)
                for url in urls:
                    self.assertEqual(self.client.get(url).status_code, 404)

            self.client.force_login(self.developer)
            for url in urls:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                response.close()

    def test_multiple_images_save_as_gallery_with_selected_width(self):
        def picture(name, color):
            data = BytesIO()
            Image.new("RGB", (4, 4), color).save(data, format="PNG")
            return SimpleUploadedFile(name, data.getvalue(), content_type="image/png")

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.owner)
            response = self.client.post(reverse("admin:kb_article_change", args=[self.public_article.pk]), {
                "section": self.public_section.pk, "title": self.public_article.title,
                "slug": self.public_article.slug, "summary": self.public_article.summary,
                "title_size": "normal", "title_alignment": "left", "title_bold": "on",
                "audience": AUDIENCE_STAFF, "status": Article.PUBLISHED, "position": 0,
                "blocks-TOTAL_FORMS": 1, "blocks-INITIAL_FORMS": 0,
                "blocks-MIN_NUM_FORMS": 0, "blocks-MAX_NUM_FORMS": 1000,
                "blocks-0-position": 1, "blocks-0-kind": ContentBlock.TEXT,
                "blocks-0-display_width": 50,
                "blocks-0-extra_images": [picture("first.png", "red"), picture("second.png", "blue")],
                "attachments-TOTAL_FORMS": 0, "attachments-INITIAL_FORMS": 0,
                "attachments-MIN_NUM_FORMS": 0, "attachments-MAX_NUM_FORMS": 1000,
            })
            self.assertEqual(response.status_code, 302, response.context[0]["adminform"].form.errors if response.context else "")
            blocks = list(self.public_article.blocks.order_by("pk"))
            self.assertEqual(len(blocks), 2)
            self.assertTrue(all(block.kind == ContentBlock.IMAGE for block in blocks))
            self.assertTrue(all(block.display_width == 50 for block in blocks))
            self.assertEqual(blocks[0].gallery_id, blocks[1].gallery_id)
            self.assertTrue(all(Path(block.image.path).exists() for block in blocks))
            page = self.client.get(self.public_article.get_absolute_url())
            self.assertContains(page, 'class="image-gallery image-width-50"')
            self.assertContains(page, 'data-gallery-slide', count=2)
            self.assertContains(page, 'data-gallery-count')
            for block in blocks:
                image_response = self.client.get(reverse("kb:private_file", args=[block.pk]))
                self.assertEqual(image_response.status_code, 200)
                image_response.close()

    def test_image_in_text_block_remains_visible(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image_data = BytesIO()
            Image.new("RGB", (4, 4), "green").save(image_data, format="PNG")
            block = ContentBlock.objects.create(
                article=self.public_article, kind=ContentBlock.TEXT,
                text="Абзац с рисунком", image=SimpleUploadedFile("older.png", image_data.getvalue(), content_type="image/png"),
            )
            self.client.force_login(self.staff)
            page = self.client.get(self.public_article.get_absolute_url())
            self.assertContains(page, "Абзац с рисунком")
            self.assertContains(page, reverse("kb:private_file", args=[block.pk]))
            image_response = self.client.get(reverse("kb:private_file", args=[block.pk]))
            self.assertEqual(image_response.status_code, 200)
            image_response.close()

    def test_text_and_uploaded_photo_stay_together(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image_data = BytesIO()
            Image.new("RGB", (4, 4), "green").save(image_data, format="PNG")
            self.client.force_login(self.owner)
            response = self.client.post(reverse("admin:kb_article_change", args=[self.public_article.pk]), {
                "section": self.public_section.pk, "title": self.public_article.title,
                "slug": self.public_article.slug, "summary": self.public_article.summary,
                "title_size": "normal", "title_alignment": "left", "title_bold": "on",
                "audience": AUDIENCE_STAFF, "status": Article.PUBLISHED, "position": 0,
                "blocks-TOTAL_FORMS": 1, "blocks-INITIAL_FORMS": 0,
                "blocks-MIN_NUM_FORMS": 0, "blocks-MAX_NUM_FORMS": 1000,
                "blocks-0-position": 1, "blocks-0-kind": ContentBlock.TEXT,
                "blocks-0-text": "Сначала текст, потом скриншот",
                "blocks-0-display_width": 60,
                "blocks-0-extra_images": [SimpleUploadedFile("one.png", image_data.getvalue(), content_type="image/png")],
                "attachments-TOTAL_FORMS": 0, "attachments-INITIAL_FORMS": 0,
                "attachments-MIN_NUM_FORMS": 0, "attachments-MAX_NUM_FORMS": 1000,
            })
            self.assertEqual(response.status_code, 302)
            block = self.public_article.blocks.get()
            self.assertEqual(block.kind, ContentBlock.TEXT)
            page = self.client.get(self.public_article.get_absolute_url())
            content = page.content.decode()
            self.assertLess(content.index("Сначала текст, потом скриншот"), content.index('class="image-gallery image-width-60"'))

    def test_section_search_respects_visibility(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("kb:search"), {"q": "Закрытый отдел разработчиков"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["section_results"]), [])
        suggestions = self.client.get(reverse("kb:suggest"), {"q": "Закрытый отдел разработчиков"})
        self.assertEqual(suggestions.json()["results"], [])

        self.client.force_login(self.developer)
        response = self.client.get(reverse("kb:search"), {"q": "Закрытый отдел разработчиков"})
        self.assertEqual([item.pk for item in response.context["section_results"]], [self.developer_section.pk])
        suggestions = self.client.get(reverse("kb:suggest"), {"q": "Закрытый отдел разработчиков"})
        self.assertIn(self.developer_section.get_absolute_url(), {item["url"] for item in suggestions.json()["results"]})


@override_settings(SECURE_SSL_REDIRECT=False)
class RichFormattingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("rich-reader", password="example-password")
        cls.owner = get_user_model().objects.create_superuser("rich-owner", "rich@example.com", "example-password")
        cls.section = Section.objects.create(title="Раздел форматирования", slug="rich-section")
        cls.article = Article.objects.create(
            section=cls.section, title="Оформленный заголовок", slug="rich-article",
            status=Article.PUBLISHED, summary="<p>Текст <strong>важный</strong></p>",
            summary_is_rich=True, title_alignment="center", title_size="large",
            title_bold=False, title_italic=True,
        )

    def test_rich_text_is_sanitized_without_losing_formatting(self):
        source = '<p class="ql-align-center" onclick="alert(1)">Привет <strong>мир</strong><span class="ql-size-large" style="color:red">!</span><script>alert(2)</script></p>'
        cleaned = clean_rich_html(source)
        self.assertIn('class="ql-align-center"', cleaned)
        self.assertIn('<strong>мир</strong>', cleaned)
        self.assertIn('class="ql-size-large"', cleaned)
        self.assertNotIn('onclick', cleaned)
        self.assertNotIn('style=', cleaned)
        self.assertNotIn('script', cleaned)
        self.assertNotIn('alert', cleaned)
        self.assertEqual(rich_plain_text(source), 'Привет мир!')

    def test_bold_words_keep_large_size_after_saving(self):
        source = (
            '<p><span class="ql-size-large">Текст перед </span>'
            '<strong>важным словом</strong>'
            '<span class="ql-size-large"> и после него.</span></p>'
        )
        self.assertIn(
            '<span class="ql-size-large"><strong>важным словом</strong></span>',
            clean_rich_html(source),
        )

    def test_formatted_article_and_plain_previews(self):
        ContentBlock.objects.create(
            article=self.article, kind=ContentBlock.TEXT, position=1,
            text='<p class="ql-align-justify">Текст <span class="ql-size-huge">крупнее</span><script>alert(1)</script></p>',
            text_is_rich=True,
        )
        self.client.force_login(self.user)
        response = self.client.get(self.article.get_absolute_url())
        self.assertContains(response, 'title-size-large title-align-center title-regular title-italic')
        self.assertContains(response, '<strong>важный</strong>', html=True)
        self.assertContains(response, 'class="ql-align-justify"')
        self.assertContains(response, 'class="ql-size-huge"')
        self.assertNotContains(response, 'alert(1)')
        self.assertNotContains(response, '&lt;strong&gt;')
        response = self.client.get(self.section.get_absolute_url())
        self.assertContains(response, 'Текст важный')
        self.assertNotContains(response, '<strong>важный</strong>')

    def test_rich_admin_editor_and_form_cleaning(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('admin:kb_article_change', args=[self.article.pk]))
        self.assertContains(response, 'kb/vendor/quill/quill.js')
        self.assertContains(response, 'data-kb-rich-editor="1"')
        form = ArticleRichForm(data={
            'section': self.section.pk, 'title': self.article.title, 'slug': self.article.slug,
            'summary': '<p class="ql-align-right">Шаг <em>один</em><img src=x onerror=alert(1)></p>',
            'summary__rich': '1', 'title_alignment': 'right', 'title_size': 'huge',
            'audience': AUDIENCE_STAFF, 'status': Article.PUBLISHED, 'position': 0,
        }, instance=self.article)
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertTrue(item.summary_is_rich)
        self.assertIn('ql-align-right', item.summary)
        self.assertNotIn('<img', item.summary)
        self.assertNotIn('onerror', item.summary)

        section_form = SectionRichForm(data={
            'title': self.section.title, 'slug': self.section.slug,
            'description': '<p class="ql-align-center">Описание <strong>раздела</strong></p>',
            'description__rich': '1', 'audience': AUDIENCE_STAFF, 'position': 0,
            'service_slug': '1c', 'catalog': 'main',
        }, instance=self.section)
        self.assertTrue(section_form.is_valid(), section_form.errors)
        self.assertTrue(section_form.save().description_is_rich)

        block_form = ContentBlockRichForm(data={
            'article': self.article.pk, 'kind': ContentBlock.TEXT, 'position': 0,
            'text': '<p>Новый <em>блок</em></p>', 'text__rich': '1',
            'display_width': 100,
        })
        self.assertTrue(block_form.is_valid(), block_form.errors)
        self.assertTrue(block_form.save().text_is_rich)

    def test_admin_can_delete_existing_text_block(self):
        block = ContentBlock.objects.create(
            article=self.article, kind=ContentBlock.TEXT, position=1,
            text='<p>Старый абзац</p>', text_is_rich=True,
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse('admin:kb_article_change', args=[self.article.pk]), {
            'section': self.section.pk,
            'title': self.article.title,
            'slug': self.article.slug,
            'summary': self.article.summary,
            'summary__rich': '1',
            'network_video_path': '',
            'featured_video_url': '',
            'title_alignment': 'center',
            'title_size': 'large',
            'title_italic': 'on',
            'audience': AUDIENCE_STAFF,
            'status': Article.PUBLISHED,
            'position': 0,
            'blocks-TOTAL_FORMS': '1',
            'blocks-INITIAL_FORMS': '1',
            'blocks-MIN_NUM_FORMS': '0',
            'blocks-MAX_NUM_FORMS': '1000',
            'blocks-0-id': str(block.pk),
            'blocks-0-article': str(self.article.pk),
            'blocks-0-position': '1',
            'blocks-0-kind': ContentBlock.TEXT,
            'blocks-0-text': block.text,
            'blocks-0-display_width': '100',
            'blocks-0-DELETE': 'on',
            'attachments-TOTAL_FORMS': '0',
            'attachments-INITIAL_FORMS': '0',
            'attachments-MIN_NUM_FORMS': '0',
            'attachments-MAX_NUM_FORMS': '1000',
            '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ContentBlock.objects.filter(pk=block.pk).exists())


class InitialTreeTests(TestCase):
    def test_service_catalog_and_disciplines(self):
        from .catalog import SERVICES
        self.assertEqual(len(SERVICES), 18)
        self.assertTrue(Group.objects.filter(name="Пользователи базы знаний").exists())
        self.assertEqual(self.client.get(reverse("kb:service", args=["cis"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("kb:service", args=["unknown"])).status_code, 404)
        response = self.client.get(reverse("kb:disciplines"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Общестроительные работы")
        self.assertEqual(Section.objects.filter(service_slug="1c", catalog="discipline", parent__isnull=True).count(), 7)
        self.assertNotContains(self.client.get(reverse("kb:home")), 'href="/sections/discipline-construction/"')
        section = Section.objects.create(title="Руководство по CIS", slug="cis-guide", service_slug="cis")
        self.assertNotContains(self.client.get(reverse("kb:service", args=["cis"])), section.title)
        Article.objects.create(title="Заполненный CIS", slug="cis-filled", section=section, summary="Инструкция", status=Article.PUBLISHED)
        self.assertContains(self.client.get(reverse("kb:service", args=["cis"])), section.title)
        self.assertNotContains(self.client.get(reverse("kb:home")), section.title)
        user = get_user_model().objects.create_user("catalog-reader", password="example-password")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("kb:disciplines")), "Общестроительные работы")

    def test_revised_document_tree_matches_all_titles_and_parent_links(self):
        self.assertEqual(Section.objects.filter(service_slug="1c", catalog="main").count(), 57)
        self.assertEqual(Article.objects.count(), 290)
        self.assertEqual(Section.objects.filter(parent__isnull=True, service_slug="1c", catalog="main").count(), 11)
        self.assertEqual(Article.objects.filter(status=Article.PUBLISHED).count(), 290)

        source = Path(__file__).parent / "data" / "tree_2026_10_01_revision.json"
        expected_roots = json.loads(source.read_text(encoding="utf-8"))

        def expected(nodes):
            return [
                (
                    "article" if node["level"] == 2 else "section",
                    node["title"],
                    expected(node["children"]),
                )
                for node in nodes
            ]

        def actual(sections):
            result = []
            for section in sections:
                children = [
                    (item.position, "section", item)
                    for item in Section.objects.filter(parent=section)
                ]
                children.extend(
                    (item.position, "article", item)
                    for item in Article.objects.filter(section=section)
                )
                children.sort(key=lambda entry: entry[0])
                result.append(
                    (
                        "section",
                        section.title,
                        [
                            ("article", item.title, [])
                            if kind == "article"
                            else ("section", item.title, actual([item])[0][2])
                            for _, kind, item in children
                        ],
                    )
                )
            return result

        self.assertEqual(actual(Section.objects.filter(parent__isnull=True, service_slug="1c", catalog="main")), expected(expected_roots))
        for number in (55, 56, *range(99, 110), *range(111, 118)):
            self.assertTrue(Article.objects.filter(slug=f"tree-article-{number:03d}").exists())
            self.assertFalse(Section.objects.filter(slug=f"tree-section-{number:03d}").exists())


class RutubeEmbedTests(SimpleTestCase):
    VIDEO_ID = "0123456789abcdef0123456789abcdef"

    def test_plain_id_and_video_link_produce_fixed_origin_embed(self):
        expected = f"https://rutube.ru/play/embed/{self.VIDEO_ID}/"
        self.assertEqual(embed_url(self.VIDEO_ID.upper()), expected)
        self.assertEqual(embed_url(f"https://www.rutube.ru/video/{self.VIDEO_ID}/"), expected)
        self.assertEqual(embed_url(f"https://rutube.ru/play/embed/{self.VIDEO_ID}/"), expected)

    def test_private_video_link_preserves_only_access_key(self):
        expected = f"https://rutube.ru/play/embed/{self.VIDEO_ID}/?p=AccessKey_12"
        self.assertEqual(
            embed_url(
                f"https://rutube.ru/video/private/{self.VIDEO_ID}/?p=AccessKey_12"
            ),
            expected,
        )

    def test_invalid_domains_ids_and_injected_markup_are_rejected(self):
        invalid_values = (
            f"http://rutube.ru/video/{self.VIDEO_ID}/",
            f"https://rutube.ru.evil.example/video/{self.VIDEO_ID}/",
            f"https://evil.rutube.ru/video/{self.VIDEO_ID}/",
            f"https://rutube.ru@evil.example/video/{self.VIDEO_ID}/",
            "javascript:alert(1)",
            "<iframe src='https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef'>",
            "https://rutube.ru/video/not-a-valid-id/",
            f"https://rutube.ru/video/{self.VIDEO_ID}/#unexpected",
            f"https://rutube.ru/video/{self.VIDEO_ID}/?p=valid&p=second",
            f"https://rutube.ru/video/{self.VIDEO_ID}/?p=%3Cscript%3E",
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                embed_url(value)
