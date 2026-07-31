from pathlib import Path

from app.scripts.parse_courses import clean_title, parse_course_row, parse_lesson_item

FIXTURES = Path(__file__).parent / "fixtures"


def test_clean_title_removes_status_words():
    assert clean_title("Введение Просмотрено") == "Введение"
    assert clean_title("Модуль 1 Пройдено") == "Модуль 1"
    assert clean_title("Заключение Завершено") == "Заключение"


def test_clean_title_collapses_whitespace():
    assert clean_title("Лекция   1") == "Лекция 1"
    assert clean_title("  Введение  ") == "Введение"


def test_parse_course_row_from_fixture():
    html = (FIXTURES / "course_row.html").read_text(encoding="utf-8")
    title, href = parse_course_row(html)
    assert title == "Курс по Python"
    assert href == "/teach/control/stream/view/id/123"


def test_parse_lesson_item_from_fixture():
    html = (FIXTURES / "lesson_item.html").read_text(encoding="utf-8")
    title, href = parse_lesson_item(html)
    assert title == "Урок 1 — Введение"
    assert href == "/teach/control/lesson/view/id/456"


def test_parse_course_row_with_status_word():
    html = (
        '<tr class="training-row">'
        '<span class="stream-title">Курс Просмотрено</span>'
        '<a href="/course/1">x</a>'
        "</tr>"
    )
    title, href = parse_course_row(html)
    assert title == "Курс"
    assert href == "/course/1"


def test_parse_lesson_item_cleans_title():
    html = '<li><div class="link title">Урок 2 Завершено</div><a href="/lesson/2">x</a></li>'
    title, href = parse_lesson_item(html)
    assert title == "Урок 2"
    assert href == "/lesson/2"


def test_parse_course_row_missing_elements():
    html = '<tr class="training-row"><td>просто текст</td></tr>'
    title, href = parse_course_row(html)
    assert title == "Без названия"
    assert href == "#"


def test_parse_lesson_item_missing_elements():
    html = "<li><span>текст</span></li>"
    title, href = parse_lesson_item(html)
    assert title == "Без названия"
    assert href == "#"


def test_parse_course_row_extra_whitespace():
    html = (
        '<tr class="training-row">'
        '<span class="stream-title">  Курс   с  пробелами  </span>'
        '<a href="/course/1">x</a>'
        "</tr>"
    )
    title, _ = parse_course_row(html)
    assert title == "Курс с пробелами"
