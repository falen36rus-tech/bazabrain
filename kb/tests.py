"""Behavioral checks for visibility and the RUTUBE embed boundary."""

import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from reversion.models import Version

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


class InitialTreeTests(TestCase):
    def test_revised_document_tree_matches_all_titles_and_parent_links(self):
        self.assertEqual(Section.objects.count(), 57)
        self.assertEqual(Article.objects.count(), 290)
        self.assertEqual(Section.objects.filter(parent__isnull=True).count(), 11)
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

        self.assertEqual(actual(Section.objects.filter(parent__isnull=True)), expected(expected_roots))
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
