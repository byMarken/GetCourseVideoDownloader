import flet as ft

from app.screens import courses_screen
from app.screens.courses_screen import CoursesScreen
from app.theme import Color


def test_log_color_segments():
    assert CoursesScreen._log_color("Сегменты: 5/10") == "#F59E0B"


def test_log_color_success():
    assert CoursesScreen._log_color("✅ Готово") == Color.GREEN
    assert CoursesScreen._log_color("✓ ok") == Color.GREEN


def test_log_color_error():
    assert CoursesScreen._log_color("❌ Ошибка") == Color.RED
    assert CoursesScreen._log_color("Ошибка загрузки") == Color.RED


def test_log_color_default():
    assert CoursesScreen._log_color("обычная строка") == Color.TEXT_SECONDARY


def test_parse_summary():
    lines = ["Загружено: 2 из 3", "Не удалось: 1", "✗ Урок 5. Катионные ПАВ"]
    header, failed = CoursesScreen._parse_summary(lines)
    assert header == ["Загружено: 2 из 3", "Не удалось: 1"]
    assert failed == ["✗ Урок 5. Катионные ПАВ"]


def test_parse_summary_empty():
    assert CoursesScreen._parse_summary([]) == ([], [])


def test_parse_summary_all_failed():
    lines = [f"✗ Урок {i}" for i in range(1, 15)]
    header, failed = CoursesScreen._parse_summary(lines)
    assert header == []
    assert len(failed) == 14


def test_update_download_title_stages():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs._download_title = ft.Text("Подготовка")
    cs._update_download_title("  ⏳ Получение запроса...")
    assert cs._download_title.value == "Получение запроса"
    cs._update_download_title("  📡 Получение запроса")
    assert cs._download_title.value == "Получение запроса"
    cs._update_download_title("  ▶ Скачивание сегментов...")
    assert cs._download_title.value == "Загрузка видео"


def test_should_log_lessons_and_segments():
    cs = CoursesScreen.__new__(CoursesScreen)
    assert cs._should_log("Старт скачивания: 2 уроков") is True
    assert cs._should_log("  ▶ Урок 3. Что такое INCI?") is True
    assert cs._should_log("  Сегменты: 1/239 (0%)") is True
    assert cs._should_log("  Сегментов: 239/239 (100%)") is True


def test_should_log_filters_stage_lines():
    cs = CoursesScreen.__new__(CoursesScreen)
    assert cs._should_log("  ✓ Авторизация активна") is False
    assert cs._should_log("  ⏳ Получение запроса...") is False
    assert cs._should_log("  ⏳ Конвертация видео...") is False


def test_should_log_logs_stage_markers():
    cs = CoursesScreen.__new__(CoursesScreen)
    assert cs._should_log("  ▶ Урок 3. Что такое INCI?") is True
    assert cs._should_log("  ▶ Скачивание сегментов...") is True
    assert cs._should_log("  ▶ ZOOM от 03.02.2026: Разбор") is True


def test_is_progress_line():
    assert CoursesScreen._is_progress_line("Сегменты: 3/10 (30%)") is True
    assert CoursesScreen._is_progress_line("Сегментов: 10/10 (100%)") is True
    assert CoursesScreen._is_progress_line("▶ Урок 3. Что такое INCI?") is False


def test_update_download_title_auth_not_confused_with_request():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs._download_title = ft.Text("Подготовка")
    cs._update_download_title("  ⚠ Страница запросила авторизацию")
    assert cs._download_title.value == "Проверка авторизации"


def test_update_download_title_playlist_not_found():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs._download_title = ft.Text("Подготовка")
    cs._update_download_title("  ⚠ Master playlist не получен")
    assert cs._download_title.value == "Плейлист не найден"


def test_update_download_title_page_then_waiting():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs._download_title = ft.Text("Подготовка")
    cs._update_download_title("  ▶ Урок 5. Катионные ПАВ")
    assert cs._download_title.value == "Загрузка страницы урока"
    cs._update_download_title("  ⏳ Получение запроса...")
    assert cs._download_title.value == "Получение запроса"


class _FakePage:
    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


def test_add_log_updates_page_for_filtered_stage_line():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs.page = _FakePage()
    cs._download_title = ft.Text("Подготовка")
    cs._log_column = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True, spacing=1)
    cs.log_lines = []
    cs._add_log("  ⏳ Получение запроса...")
    assert cs._download_title.value == "Получение запроса"
    assert cs.page.updates >= 1
    assert len(cs._log_column.controls) == 0


def test_add_log_filtered_no_title_change_no_update():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs.page = _FakePage()
    cs._download_title = ft.Text("Загрузка видео")
    cs._log_column = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True, spacing=1)
    cs.log_lines = []
    cs._add_log("  ⚠ Нет сегментов")
    assert cs.page.updates == 0
    assert len(cs._log_column.controls) == 0


def test_update_download_title_ignores_unrelated():
    cs = CoursesScreen.__new__(CoursesScreen)
    cs._download_title = ft.Text("Подготовка")
    cs._update_download_title("  ⚠ Нет сегментов")
    assert cs._download_title.value == "Подготовка"


def test_build_support_block_github_star_clickable():
    cs = CoursesScreen.__new__(CoursesScreen)
    block = cs._build_support_block()
    assert len(block) == 1
    column = block[0]
    assert isinstance(column, ft.Column)
    text = column.controls[0]
    assert isinstance(text, ft.Text)
    spans = text.spans
    assert len(spans) == 2
    assert spans[0].text == "⭐ "
    link = spans[1]
    assert link.text == "Star on GitHub"
    assert link.style.decoration != ft.TextDecoration.UNDERLINE
    assert link.style.color == Color.ACCENT_LIGHT
    assert all(span.on_click is not None for span in spans)


def test_build_failed_lessons_scrollable():
    cs = CoursesScreen.__new__(CoursesScreen)
    container = cs._build_failed_lessons([f"✗ Урок {i}" for i in range(1, 12)])
    assert isinstance(container, ft.Container)
    inner = container.content
    assert isinstance(inner, ft.Column)
    assert inner.scroll == ft.ScrollMode.AUTO
    assert len(inner.controls) == 11


def test_has_courses_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(courses_screen, "_COURSES_PATH", tmp_path / "courses.json")
    assert CoursesScreen.has_courses() is False


def test_has_courses_with_data(monkeypatch, tmp_path):
    path = tmp_path / "courses.json"
    path.write_text('[{"course_title": "C", "lessons": []}]', encoding="utf-8")
    monkeypatch.setattr(courses_screen, "_COURSES_PATH", path)
    assert CoursesScreen.has_courses() is True


def test_has_courses_empty_list(monkeypatch, tmp_path):
    path = tmp_path / "courses.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(courses_screen, "_COURSES_PATH", path)
    assert CoursesScreen.has_courses() is False


def test_has_courses_invalid_json(monkeypatch, tmp_path):
    path = tmp_path / "courses.json"
    path.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(courses_screen, "_COURSES_PATH", path)
    assert CoursesScreen.has_courses() is False


def test_load_save_path_default(monkeypatch, tmp_path):
    monkeypatch.setattr(courses_screen, "_SETTINGS_PATH", tmp_path / "settings.json")
    assert CoursesScreen._load_save_path() == "downloads"


def test_load_save_path_from_file(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"save_path": "D:/videos"}', encoding="utf-8")
    monkeypatch.setattr(courses_screen, "_SETTINGS_PATH", path)
    assert CoursesScreen._load_save_path() == "D:/videos"


def test_load_save_path_not_string(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"save_path": 123}', encoding="utf-8")
    monkeypatch.setattr(courses_screen, "_SETTINGS_PATH", path)
    assert CoursesScreen._load_save_path() == "downloads"
