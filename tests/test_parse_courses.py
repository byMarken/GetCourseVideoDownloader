import asyncio
from pathlib import Path
from typing import Any

from getcourse_downloader.infrastructure.getcourse.discovery import (
    GetCourseDiscoverer,
    clean_title,
    extract_stream_urls,
    normalize_lesson_url,
    normalize_stream_url,
    parse_course_row,
    parse_lesson_item,
)

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


def test_extract_stream_urls_from_widget_javascript():
    html = r"""
        <script>
            params = {"link":"https:\/\/school.example\/teach\/control\/stream\/view\/id\/100"};
            duplicate = "/teach/control/stream/view/id/100";
            nested = "/pl/teach/control/stream/view?id=200&editMode=0";
            foreign = "https:\/\/another.example\/teach\/control\/stream\/view\/id\/300";
        </script>
    """

    assert extract_stream_urls(html, "https://school.example/teach/control") == [
        "https://school.example/teach/control/stream/view/id/100",
        "https://school.example/teach/control/stream/view/id/200",
    ]


def test_normalize_getcourse_content_urls():
    base_url = "https://school.example/teach/control"

    assert (
        normalize_stream_url(
            base_url,
            "/pl/teach/control/stream/view?id=123&editMode=0",
        )
        == "https://school.example/teach/control/stream/view/id/123"
    )
    assert (
        normalize_lesson_url(
            base_url,
            "/pl/teach/control/lesson/view?id=456",
        )
        == "https://school.example/teach/control/lesson/view/id/456"
    )
    assert (
        normalize_stream_url(
            base_url,
            "https://another.example/teach/control/stream/view/id/999",
        )
        is None
    )


class _FakeElement:
    def __init__(self, *, html: str = "", text: str = "") -> None:
        self._html = html
        self._text = text

    async def inner_html(self) -> str:
        return self._html

    async def inner_text(self) -> str:
        return self._text


class _FakePage:
    def __init__(self, pages: dict[str, dict[str, Any]], start_url: str) -> None:
        self._pages = pages
        self.url = start_url

    async def goto(self, url: str, **_: object) -> None:
        self.url = url

    async def wait_for_load_state(self, *_: object, **__: object) -> None:
        return None

    async def wait_for_selector(self, *_: object, **__: object) -> None:
        return None

    async def content(self) -> str:
        return str(self._pages[self.url].get("content", ""))

    async def query_selector_all(self, selector: str) -> list[_FakeElement]:
        current = self._pages[self.url]
        if selector == "tr.training-row":
            return [_FakeElement(html=str(html)) for html in current.get("stream_rows", [])]
        if selector == "ul.lesson-list li":
            return [_FakeElement(html=str(html)) for html in current.get("lessons", [])]
        return []

    async def query_selector(self, selector: str) -> _FakeElement | None:
        if selector == "h1" and (title := self._pages[self.url].get("title")):
            return _FakeElement(text=str(title))
        return None


def _lesson_html(identifier: int, title: str) -> str:
    return (
        '<li><a href="/teach/control/lesson/view/id/'
        f'{identifier}"><div class="link title">{title}</div></a></li>'
    )


def _stream_row_html(identifier: int, title: str) -> str:
    return (
        '<tr class="training-row"><a href="/teach/control/stream/view/id/'
        f'{identifier}"><span class="stream-title">{title}</span></a></tr>'
    )


def test_recursive_discovery_from_main_page_keeps_hierarchy_and_removes_duplicates():
    base = "https://school.example"
    main_url = f"{base}/teach/control"
    course_a = f"{base}/teach/control/stream/view/id/100"
    course_b = f"{base}/teach/control/stream/view/id/200"
    module_b = f"{base}/teach/control/stream/view/id/201"
    pages: dict[str, dict[str, Any]] = {
        main_url: {
            "content": (
                r'params={"link":"https:\/\/school.example\/teach\/control\/stream\/view\/id\/100"};'
                r'params={"link":"https:\/\/school.example\/teach\/control\/stream\/view\/id\/200"};'
            )
        },
        course_a: {
            "title": "Курс A",
            "content": "",
            "lessons": [
                _lesson_html(1001, "Урок A"),
                "<li><span>Служебный пункт без ссылки</span></li>",
            ],
        },
        course_b: {
            "title": "Курс B",
            "content": "",
            "lessons": [_lesson_html(2001, "Введение")],
            "stream_rows": [_stream_row_html(201, "Модуль")],
        },
        module_b: {
            "title": "Модуль",
            "content": r'parent="\/teach\/control\/stream\/view\/id\/200"',
            "lessons": [
                _lesson_html(2001, "Введение повторно"),
                _lesson_html(2011, "Практика"),
            ],
        },
    }
    discoverer = GetCourseDiscoverer(browser_factory=None)  # type: ignore[arg-type]
    page: Any = _FakePage(pages, main_url)
    courses = asyncio.run(discoverer._parse_page(page, main_url))

    assert [(course.title, [lesson.title for lesson in course.lessons]) for course in courses] == [
        ("Курс A", ["Урок A"]),
        ("Курс B", ["Введение"]),
        ("Курс B → Модуль", ["Практика"]),
    ]
