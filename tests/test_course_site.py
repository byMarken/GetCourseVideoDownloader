from pathlib import Path

from getcourse_downloader.domain.models import (
    DownloadRequest,
    Lesson,
    SelectedLesson,
    VideoQuality,
)
from getcourse_downloader.infrastructure.storage.course_site import generate_course_site


def test_course_site_contains_hierarchy_video_and_text_lesson(tmp_path: Path):
    video_item = SelectedLesson(
        ("Курс", "Блок 1", "Модуль 1"),
        Lesson("Урок 1", "https://school/lesson/1"),
    )
    text_item = SelectedLesson(
        ("Курс", "Блок 1"),
        Lesson("Контрольная работа", "https://school/lesson/2"),
    )
    video_stem = tmp_path / "Курс" / "Блок 1" / "Модуль 1" / "Урок 1"
    text_stem = tmp_path / "Курс" / "Блок 1" / "Контрольная работа"
    video_stem.parent.mkdir(parents=True)
    text_stem.parent.mkdir(parents=True, exist_ok=True)
    video_stem.with_suffix(".mp4").write_bytes(b"video")
    text_stem.with_suffix(".html").write_text("<html>Задание</html>", encoding="utf-8")
    request = DownloadRequest((video_item, text_item), VideoQuality.AUTO, tmp_path)

    output = generate_course_site(request, [video_stem, text_stem], None)

    assert output == tmp_path / "index.html"
    document = output.read_text(encoding="utf-8")
    assert 'class="tile folder"' in document
    assert "Курс" in document
    assert "Блок 1" in document
    assert "Модуль 1" in document
    assert 'class="tile lesson-tile"' in document
    assert 'class="page lesson-page"' in document
    assert "← На уровень выше" in document
    assert "← К списку уроков" in document
    assert "<video controls" in document
    assert ".mp4" in document
    assert "<iframe" in document
    assert ".html" in document
    assert "Описание и материалы урока" in document
