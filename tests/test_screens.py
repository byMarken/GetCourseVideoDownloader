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


def test_format_summary():
    lines = ["Загружено: 2 из 3", "Не удалось: 1", "  ✗ Урок 5. Катионные ПАВ"]
    assert CoursesScreen._format_summary(lines) == (
        "Загружено: 2 из 3\nНе удалось: 1\n  ✗ Урок 5. Катионные ПАВ"
    )


def test_format_summary_empty():
    assert CoursesScreen._format_summary([]) is None


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
