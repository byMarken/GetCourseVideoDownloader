import asyncio
import contextlib
import json
import threading
from functools import partial
from pathlib import Path
from typing import cast

import flet as ft

from app.theme import Color, Gradient, Shadow, accent_button, body_text, divider
from app.utils.paths import data_dir

_COURSES_PATH = data_dir() / "courses.json"
_SETTINGS_PATH = data_dir() / "settings.json"

# Префикс итоговой сводки воркера — должен совпадать с givereq.py
_SUMMARY_PREFIX = "[SUMMARY]"
# Репозиторий проекта — для блока поддержки
_GITHUB_URL = "https://github.com/markpekun/getcourse-downloader"


_COURSE_COLORS = [
    "#7C3AED",
    "#EC4899",
    "#10B981",
    "#F59E0B",
    "#3B82F6",
    "#EF4444",
    "#14B8A6",
    "#F97316",
]


class CoursesScreen:
    @staticmethod
    def has_courses() -> bool:
        file = _COURSES_PATH
        if not file.exists():
            return False
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            return isinstance(data, list) and len(data) > 0
        except Exception:
            return False

    def __init__(self, page: ft.Page):
        self.page = page
        self._downloading = False
        self._scroll_task: asyncio.Task | None = None
        self._open_task: asyncio.Task | None = None
        self._download_title = ft.Text(
            "Подготовка",
            size=18,
            weight=ft.FontWeight.W_600,
            color=Color.TEXT,
        )

        with open(_COURSES_PATH, encoding="utf-8") as f:
            self.data: list = json.load(f)

        self.expanded_courses: set[int] = set(range(len(self.data)))
        self.lesson_refs: dict[int, list[ft.Checkbox]] = {}
        self._register: list[ft.Checkbox] = []

        self._quality = "auto"
        self._save_path = self._load_save_path()

        self.file_picker = ft.FilePicker()

        self._search_query = ft.TextField(
            hint_text="Поиск уроков...",
            hint_style=ft.TextStyle(color=Color.TEXT_MUTED, size=14),
            color=Color.TEXT,
            bgcolor="rgba(255,255,255,0.04)",
            border_color=Color.BORDER,
            border_width=1,
            border_radius=10,
            focused_border_color=Color.ACCENT,
            focused_bgcolor="rgba(124,58,237,0.06)",
            cursor_color=Color.ACCENT,
            text_style=ft.TextStyle(size=14),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            prefix_style=ft.TextStyle(color=Color.TEXT_MUTED),
            height=44,
            expand=True,
            on_change=self._on_search,
        )

        self.selected_label = ft.Text(
            "0",
            size=24,
            weight=ft.FontWeight.W_800,
            color=Color.ACCENT_LIGHT,
        )

        self.selected_hint = body_text("уроков выбрано", size=13)

        self.course_list = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        self._build_course_list()

        self.side_content = ft.Column(spacing=16)
        self._build_side_panel()

        self.log_lines: list[str] = []
        self._log_column = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True, spacing=1)
        self._log_container = ft.Container(
            width=440,
            height=180,
            border_radius=10,
            bgcolor="rgba(0,0,0,0.3)",
            border=ft.Border.all(1, "rgba(255,255,255,0.06)"),
            padding=ft.Padding.all(12),
            content=self._log_column,
        )
        self._continue_btn = ft.Container(
            visible=False,
            padding=ft.Padding.symmetric(horizontal=20, vertical=8),
            border_radius=8,
            gradient=Gradient.ACCENT,
            ink=True,
            on_click=self._send_continue,
            content=ft.Text("Продолжить", size=14, weight=ft.FontWeight.W_600, color=Color.TEXT),
        )

        self._auth_icon = ft.Container(
            width=38,
            height=38,
            border_radius=11,
            gradient=Gradient.ACCENT,
            shadow=Shadow.GLOW_PRIMARY,
            content=ft.Icon(ft.Icons.LOCK_ROUNDED, size=19, color=Color.TEXT),
        )
        self._auth_title = ft.Text(
            "Требуется вход",
            size=17,
            weight=ft.FontWeight.W_700,
            color=Color.TEXT,
        )
        self._auth_desc = ft.Text(
            "Для доступа к материалам необходимо\nвыполнить вход в аккаунт.",
            size=12,
            color=Color.TEXT_SECONDARY,
            text_align=ft.TextAlign.CENTER,
        )
        _auth_steps = [
            "Дождитесь открытия браузера.",
            "Выполните вход в аккаунт.",
            "Вернитесь в приложение.",
            "Нажмите «Продолжить».",
        ]
        self._auth_instructions = ft.Container(
            padding=ft.Padding.symmetric(vertical=2),
            content=ft.Column(
                spacing=2,
                controls=[
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Text(
                                f"{i + 1}.",
                                size=12,
                                color=Color.ACCENT_LIGHT,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(step, size=12, color=Color.TEXT_SECONDARY),
                        ],
                    )
                    for i, step in enumerate(_auth_steps)
                ],
            ),
        )
        self._auth_status = ft.Text(
            "Ожидаем вход в браузере...",
            size=13,
            color=Color.ACCENT_LIGHT,
            weight=ft.FontWeight.W_500,
            text_align=ft.TextAlign.CENTER,
            height=20,
        )

        self._auth_overlay_task: asyncio.Task | None = None

        self._overlay_card = ft.Container(
            width=500,
            padding=ft.Padding.all(24),
            border_radius=20,
            bgcolor=Color.BG_CARD,
            border=ft.Border.all(1, Color.ACCENT_GLOW),
            shadow=ft.BoxShadow(
                blur_radius=40,
                color=Color.ACCENT_GLOW,
                offset=ft.Offset(0, 8),
            ),
            gradient=Gradient.CARD,
            opacity=0,
            offset=ft.Offset(0, 0.15),
            animate_opacity=ft.Animation(350, ft.AnimationCurve.EASE_OUT),
            animate_offset=ft.Animation(350, ft.AnimationCurve.EASE_OUT),
            animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    ft.ProgressRing(width=40, height=40, color=Color.ACCENT, stroke_width=4),
                    ft.Text(
                        "Загрузка видео",
                        size=18,
                        weight=ft.FontWeight.W_600,
                        color=Color.TEXT,
                    ),
                    self._log_container,
                    self._continue_btn,
                ],
            ),
        )

        self.overlay = ft.Container(
            expand=True,
            bgcolor="rgba(0,0,0,0.7)",
            visible=False,
            content=ft.Row(
                expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[self._overlay_card],
                    ),
                ],
            ),
        )

        self.error_overlay = ft.Container(
            expand=True,
            bgcolor="rgba(0,0,0,0.7)",
            visible=False,
            content=ft.Row(
                expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=420,
                                padding=ft.Padding.all(24),
                                border_radius=20,
                                bgcolor=Color.BG_CARD,
                                border=ft.Border.all(1, Color.BORDER),
                                shadow=Shadow.CARD,
                                gradient=Gradient.CARD,
                                content=ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    spacing=20,
                                    controls=[
                                        ft.Row(
                                            alignment=ft.MainAxisAlignment.END,
                                            controls=[
                                                ft.Container(
                                                    content=ft.Icon(
                                                        ft.Icons.CLOSE,
                                                        size=20,
                                                        color=Color.TEXT_SECONDARY,
                                                    ),
                                                    padding=ft.Padding.all(4),
                                                    border_radius=6,
                                                    ink=True,
                                                    on_click=self._dismiss_error,
                                                ),
                                            ],
                                        ),
                                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=56, color=Color.RED),
                                        ft.Text(
                                            "Папка сохранения не найдена!",
                                            size=20,
                                            weight=ft.FontWeight.W_600,
                                            color=Color.TEXT,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Text(
                                            f"Путь: {self._save_path}",
                                            size=13,
                                            color=Color.TEXT_MUTED,
                                            text_align=ft.TextAlign.CENTER,
                                        ),
                                        ft.Container(
                                            content=ft.Text(
                                                "Выбрать другую папку",
                                                size=15,
                                                weight=ft.FontWeight.W_600,
                                                color=Color.TEXT,
                                            ),
                                            padding=ft.Padding.symmetric(
                                                horizontal=24, vertical=12
                                            ),
                                            border_radius=10,
                                            gradient=Gradient.ACCENT,
                                            ink=True,
                                            on_click=self._dismiss_error_and_pick,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

        self.view = ft.Container(
            expand=True,
            gradient=Gradient.BG_PRIMARY,
            content=ft.Stack(
                expand=True,
                controls=[
                    ft.Column(
                        spacing=0,
                        controls=[
                            self._build_header(),
                            divider(),
                            ft.Container(
                                expand=True,
                                padding=ft.Padding.only(left=32, right=32, top=20, bottom=20),
                                content=ft.Row(
                                    spacing=24,
                                    controls=[
                                        ft.Container(
                                            width=320,
                                            content=self.side_content,
                                        ),
                                        ft.Container(
                                            expand=True,
                                            content=ft.Column(
                                                spacing=16,
                                                controls=[
                                                    self._build_toolbar(),
                                                    self.course_list,
                                                ],
                                            ),
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    self.overlay,
                    self.error_overlay,
                ],
            ),
        )
        self._update_selected_count()

    def _build_header(self) -> ft.Container:
        total_lessons = sum(len(c["lessons"]) for c in self.data)
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=32, vertical=16),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        spacing=16,
                        controls=[
                            ft.Container(
                                width=40,
                                height=40,
                                border_radius=12,
                                gradient=Gradient.ACCENT,
                                content=ft.Icon(
                                    ft.Icons.DOWNLOAD_ROUNDED,
                                    size=20,
                                    color=Color.TEXT,
                                ),
                            ),
                            ft.Column(
                                spacing=0,
                                controls=[
                                    ft.Text(
                                        "Мои курсы",
                                        size=22,
                                        weight=ft.FontWeight.W_700,
                                        color=Color.TEXT,
                                    ),
                                    body_text(
                                        f"{len(self.data)} курсов · {total_lessons} уроков",
                                        size=12,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    ft.Container(
                        content=ft.Row(
                            spacing=8,
                            controls=[
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.DELETE_ROUNDED,
                                        size=20,
                                        color=Color.RED,
                                    ),
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                    border_radius=6,
                                    bgcolor="rgba(239,68,68,0.12)",
                                    ink=True,
                                    on_click=self._delete_courses,
                                    tooltip="Удалить курсы и начать заново",
                                ),
                                ft.Container(
                                    content=ft.Row(
                                        [
                                            ft.Icon(
                                                ft.Icons.FOLDER_OPEN_ROUNDED,
                                                size=14,
                                                color=Color.ACCENT_LIGHT,
                                            ),
                                            ft.Text(
                                                str(len(self.data)),
                                                size=13,
                                                weight=ft.FontWeight.W_600,
                                                color=Color.ACCENT_LIGHT,
                                            ),
                                        ],
                                        spacing=4,
                                    ),
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                    border_radius=6,
                                    bgcolor="rgba(124,58,237,0.12)",
                                ),
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.TELEGRAM,
                                        size=19,
                                        color="#2AABEE",
                                    ),
                                    padding=ft.Padding.all(7),
                                    border_radius=8,
                                    bgcolor="rgba(42,171,238,0.10)",
                                    ink=True,
                                    tooltip="Написать в поддержку",
                                    on_click=lambda _: asyncio.create_task(
                                        self.page.launch_url("https://t.me/No_Resp_404")
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )

    def _build_toolbar(self) -> ft.Container:
        return ft.Container(
            padding=ft.Padding.symmetric(vertical=2),
            content=ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[self._search_query],
            ),
        )

    def _build_course_list(self):
        self.course_list.controls.clear()
        self.lesson_refs.clear()
        self._register.clear()
        for idx, course in enumerate(self.data):
            card = self._build_course_card(idx, course)
            self.course_list.controls.append(card)

    def _build_course_card(self, idx: int, course: dict) -> ft.Container:
        accent = _COURSE_COLORS[idx % len(_COURSE_COLORS)]
        lessons = course.get("lessons", [])
        is_expanded = idx in self.expanded_courses

        lesson_checks: list[ft.Checkbox] = []
        for lesson in lessons:
            cb = ft.Checkbox(
                label=lesson.get("title", "Без названия"),
                value=False,
                tristate=False,
                on_change=self._update_selected_count,
                active_color=accent,
                check_color=Color.TEXT,
                fill_color={
                    ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.08, accent),
                    ft.ControlState.SELECTED: accent,
                },
                label_style=ft.TextStyle(
                    size=14,
                    color=Color.TEXT,
                    weight=ft.FontWeight.W_400,
                ),
                semantics_label=lesson.get("title", ""),
            )
            lesson_checks.append(cb)

        self.lesson_refs[idx] = lesson_checks
        self._register.extend(lesson_checks)

        lesson_list = ft.Column(spacing=2, controls=cast(list[ft.Control], lesson_checks))
        body = lesson_list if is_expanded else ft.Container(height=0)

        selected_count = sum(1 for c in lesson_checks if c.value)

        return ft.Container(
            border_radius=16,
            bgcolor=Color.BG_CARD,
            border=ft.Border.all(1, Color.BORDER),
            shadow=Shadow.CARD,
            gradient=Gradient.CARD,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=20, vertical=14),
                        ink=True,
                        on_click=lambda _, i=idx: self._toggle_course(i),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Row(
                                    spacing=14,
                                    controls=[
                                        ft.Container(
                                            width=4,
                                            height=32,
                                            border_radius=2,
                                            bgcolor=accent,
                                        ),
                                        ft.Column(
                                            spacing=2,
                                            controls=[
                                                ft.Text(
                                                    course.get("course_title", "Без названия"),
                                                    size=16,
                                                    weight=ft.FontWeight.W_600,
                                                    color=Color.TEXT,
                                                ),
                                                body_text(
                                                    f"{len(lessons)} уроков",
                                                    size=12,
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                ft.Row(
                                    spacing=12,
                                    controls=[
                                        ft.Container(
                                            content=ft.Text(
                                                str(selected_count),
                                                size=13,
                                                weight=ft.FontWeight.W_600,
                                                color=accent,
                                            ),
                                            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                            border_radius=8,
                                            bgcolor=ft.Colors.with_opacity(0.12, accent),
                                        ),
                                        ft.Icon(
                                            ft.Icons.EXPAND_MORE_ROUNDED
                                            if is_expanded
                                            else ft.Icons.CHEVRON_RIGHT_ROUNDED,
                                            size=22,
                                            color=Color.TEXT_SECONDARY,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ),
                    body,
                ],
            ),
        )

    def _toggle_course(self, idx: int):
        if idx in self.expanded_courses:
            self.expanded_courses.discard(idx)
        else:
            self.expanded_courses.add(idx)
        self._build_course_list()
        self.page.update()

    def _on_search(self, e):
        query = e.control.value.strip().lower()
        if not query:
            for card in self.course_list.controls:
                card.visible = True
            for refs in self.lesson_refs.values():
                for cb in refs:
                    cb.visible = True
            self.page.update()
            return

        for idx, course in enumerate(self.data):
            lessons = course.get("lessons", [])
            refs = self.lesson_refs.get(idx, [])
            course_matches = any(query in lesson.get("title", "").lower() for lesson in lessons)
            card = self.course_list.controls[idx] if idx < len(self.course_list.controls) else None
            if card:
                card.visible = course_matches or any(query in cb.label.lower() for cb in refs)
            for cb in refs:
                cb.visible = cb.label and query in cb.label.lower()
        self.page.update()

    def _build_side_panel(self):
        total_lessons = sum(len(c["lessons"]) for c in self.data)

        def _stat_card() -> ft.Container:
            return ft.Container(
                padding=20,
                border_radius=16,
                bgcolor=Color.BG_CARD,
                border=ft.Border.all(1, Color.BORDER),
                shadow=Shadow.CARD,
                gradient=Gradient.CARD,
                content=ft.Column(
                    spacing=16,
                    controls=[
                        ft.Row(
                            spacing=10,
                            controls=[
                                ft.Container(
                                    width=40,
                                    height=40,
                                    border_radius=12,
                                    gradient=Gradient.ACCENT,
                                    content=ft.Icon(
                                        ft.Icons.DOWNLOAD_DONE_ROUNDED,
                                        size=20,
                                        color=Color.TEXT,
                                    ),
                                ),
                                ft.Text(
                                    "Загрузка",
                                    size=18,
                                    weight=ft.FontWeight.W_700,
                                    color=Color.TEXT,
                                ),
                            ],
                        ),
                        divider(),
                        ft.Container(
                            padding=16,
                            border_radius=12,
                            bgcolor="rgba(124,58,237,0.06)",
                            border=ft.Border.all(1, "rgba(124,58,237,0.12)"),
                            content=ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=4,
                                controls=[
                                    ft.Row(
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        spacing=6,
                                        controls=[
                                            self.selected_label,
                                            ft.Text(
                                                f"/ {total_lessons}",
                                                size=18,
                                                color=Color.TEXT_MUTED,
                                                weight=ft.FontWeight.W_500,
                                            ),
                                        ],
                                    ),
                                    body_text("уроков выбрано", size=13),
                                ],
                            ),
                        ),
                    ],
                ),
            )

        def _quality_card() -> ft.Container:
            return ft.Container(
                padding=20,
                border_radius=16,
                bgcolor=Color.BG_CARD,
                border=ft.Border.all(1, Color.BORDER),
                shadow=Shadow.CARD,
                gradient=Gradient.CARD,
                content=ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text(
                            "Качество видео",
                            size=16,
                            weight=ft.FontWeight.W_600,
                            color=Color.TEXT,
                        ),
                        divider(),
                        ft.Dropdown(
                            value=self._quality,
                            options=[
                                ft.DropdownOption(key="auto", text="Авто"),
                                ft.DropdownOption(key="1080", text="1080p"),
                                ft.DropdownOption(key="720", text="720p"),
                                ft.DropdownOption(key="480", text="480p"),
                                ft.DropdownOption(key="360", text="360p"),
                            ],
                            on_select=self._on_quality_change,
                            text_style=ft.TextStyle(size=14, color=Color.TEXT),
                            bgcolor="rgba(255,255,255,0.04)",
                            border_color=Color.BORDER,
                            border_width=1,
                            border_radius=10,
                            focused_border_color=Color.ACCENT,
                            color=Color.TEXT,
                            height=48,
                        ),
                    ],
                ),
            )

        def _save_path_card() -> ft.Container:
            return ft.Container(
                padding=20,
                border_radius=16,
                bgcolor=Color.BG_CARD,
                border=ft.Border.all(1, Color.BORDER),
                shadow=Shadow.CARD,
                gradient=Gradient.CARD,
                content=ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text(
                            "Папка сохранения",
                            size=16,
                            weight=ft.FontWeight.W_600,
                            color=Color.TEXT,
                        ),
                        divider(),
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.TextField(
                                    value=self._save_path,
                                    read_only=True,
                                    expand=True,
                                    hint_text="Выберите папку...",
                                    hint_style=ft.TextStyle(color=Color.TEXT_MUTED, size=13),
                                    color=Color.TEXT,
                                    bgcolor="rgba(255,255,255,0.04)",
                                    border_color=Color.BORDER,
                                    border_width=1,
                                    border_radius=10,
                                    text_style=ft.TextStyle(size=13),
                                    height=44,
                                ),
                                ft.Container(
                                    content=ft.Icon(
                                        ft.Icons.FOLDER_OPEN_ROUNDED,
                                        size=20,
                                        color=Color.TEXT,
                                    ),
                                    width=44,
                                    height=44,
                                    border_radius=10,
                                    gradient=Gradient.ACCENT,
                                    ink=True,
                                    on_click=self._pick_directory,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                ),
            )

        def _actions_card() -> ft.Container:
            return ft.Container(
                padding=20,
                border_radius=16,
                bgcolor=Color.BG_CARD,
                border=ft.Border.all(1, Color.BORDER),
                shadow=Shadow.CARD,
                gradient=Gradient.CARD,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text(
                            "Действия",
                            size=16,
                            weight=ft.FontWeight.W_600,
                            color=Color.TEXT,
                        ),
                        divider(),
                        ft.Container(
                            content=ft.Row(
                                spacing=10,
                                controls=[
                                    ft.Container(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.SELECT_ALL_ROUNDED,
                                                    size=18,
                                                    color=Color.TEXT_SECONDARY,
                                                ),
                                                ft.Text(
                                                    "Выбрать все",
                                                    size=14,
                                                    weight=ft.FontWeight.W_500,
                                                    color=Color.TEXT,
                                                ),
                                            ],
                                            spacing=6,
                                            alignment=ft.MainAxisAlignment.CENTER,
                                        ),
                                        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
                                        border_radius=10,
                                        border=ft.Border.all(1, Color.BORDER_STRONG),
                                        bgcolor="rgba(255,255,255,0.03)",
                                        ink=True,
                                        on_click=self._select_all,
                                        expand=True,
                                    ),
                                    ft.Container(
                                        content=ft.Row(
                                            [
                                                ft.Icon(
                                                    ft.Icons.DESELECT_ROUNDED,
                                                    size=18,
                                                    color=Color.TEXT_SECONDARY,
                                                ),
                                                ft.Text(
                                                    "Убрать все",
                                                    size=14,
                                                    weight=ft.FontWeight.W_500,
                                                    color=Color.TEXT,
                                                ),
                                            ],
                                            spacing=6,
                                            alignment=ft.MainAxisAlignment.CENTER,
                                        ),
                                        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
                                        border_radius=10,
                                        border=ft.Border.all(1, Color.BORDER_STRONG),
                                        bgcolor="rgba(255,255,255,0.03)",
                                        ink=True,
                                        on_click=self._unselect_all,
                                        expand=True,
                                    ),
                                ],
                            ),
                        ),
                        accent_button(
                            "Скачать выбранное",
                            on_click=self._start_download,
                            icon=ft.Icons.DOWNLOAD_ROUNDED,
                            height=48,
                        ),
                    ],
                ),
            )

        self.side_content.controls = [
            _stat_card(),
            _quality_card(),
            _save_path_card(),
            _actions_card(),
        ]

    def _on_quality_change(self, e):
        self._quality = e.control.value

    async def _pick_directory(self, e):
        kwargs = {"dialog_title": "Выберите папку для сохранения видео"}
        if Path(self._save_path).is_absolute():
            kwargs["initial_directory"] = self._save_path
        try:
            path = await self.file_picker.get_directory_path(**kwargs)
        except Exception:
            kwargs.pop("initial_directory", None)
            path = await self.file_picker.get_directory_path(**kwargs)
        if path:
            self._save_path = path
            self._save_save_path(path)
            self._build_side_panel()
            self.page.update()

    @staticmethod
    def _load_save_path() -> str:
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
                save_path = data.get("save_path", "downloads")
                return save_path if isinstance(save_path, str) else "downloads"
        except (FileNotFoundError, json.JSONDecodeError):
            return "downloads"

    @staticmethod
    def _save_save_path(path: str) -> None:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"save_path": path}, f)

    async def _delete_courses(self, e):
        if _COURSES_PATH.exists():
            _COURSES_PATH.unlink()
        self.page.clean()
        self.page.window.width = 680
        self.page.window.height = 460
        from app.screens.start_screen import StartScreen

        screen = StartScreen(self.page)
        self.page.add(screen.view)
        await self.page.window.center()
        self.page.update()

    def _update_selected_count(self, e=None):
        selected = sum(1 for cb in self._register if cb.value)
        self.selected_label.value = str(selected)
        for idx, refs in self.lesson_refs.items():
            count = sum(1 for cb in refs if cb.value)
            card = self.course_list.controls[idx] if idx < len(self.course_list.controls) else None
            if card:
                accent = _COURSE_COLORS[idx % len(_COURSE_COLORS)]
                self._update_card_badge(card, count, accent)
        self.page.update()

    def _update_card_badge(self, card: ft.Container, count: int, accent: str):
        column = card.content
        if not isinstance(column, ft.Column) or not column.controls:
            return
        header = column.controls[0]
        if not isinstance(header, ft.Container):
            return
        row = header.content
        if not isinstance(row, ft.Row):
            return
        right_side = row.controls[-1]
        if not isinstance(right_side, ft.Row):
            return
        badge = right_side.controls[0]
        if isinstance(badge, ft.Container) and isinstance(badge.content, ft.Text):
            badge.content.value = str(count)

    def _select_all(self, e):
        for cb in self._register:
            cb.value = True
        self._update_selected_count()

    def _unselect_all(self, e):
        for cb in self._register:
            cb.value = False
        self._update_selected_count()

    def _dismiss_error(self, e):
        self.error_overlay.visible = False
        self.page.update()

    async def _dismiss_error_and_pick(self, e):
        self.error_overlay.visible = False
        await self._pick_directory(None)
        self.page.update()

    @staticmethod
    def _log_color(line: str) -> str:
        if "Сегменты" in line or "сегмент" in line.lower():
            return "#F59E0B"
        if line.startswith(("✅", "✓")):
            return Color.GREEN
        if line.startswith("❌") or "Ошибка" in line:
            return Color.RED
        return Color.TEXT_SECONDARY

    @staticmethod
    def _parse_summary(summary_lines: list[str]) -> tuple[list[str], list[str]]:
        """Разделяет строки сводки воркера на заголовок и список неудавшихся уроков."""
        header: list[str] = []
        failed: list[str] = []
        for line in summary_lines:
            if line.startswith("✗"):
                failed.append(line)
            else:
                header.append(line)
        return header, failed

    def _scroll_smooth(self):
        try:
            loop = asyncio.get_running_loop()
            self._scroll_task = loop.create_task(
                self._log_column.scroll_to(
                    delta=1000000,
                    duration=250,
                    curve=ft.AnimationCurve.EASE_OUT,
                )
            )
        except Exception:
            pass

    @staticmethod
    def _is_progress_line(text: str) -> bool:
        return "Сегменты:" in text or "Сегментов:" in text

    def _should_log(self, line: str) -> bool:
        if line.startswith("Старт скачивания"):
            return True
        if "▶" in line and "Урок" in line:
            return True
        return self._is_progress_line(line)

    def _update_download_title(self, line: str) -> bool:
        check = line.lower()
        if "сегмент" in check and "нет" not in check:
            title = "Загрузка видео"
        elif "не получен" in check:
            title = "Плейлист не найден"
        elif "получение запроса" in check:
            title = "Получение запроса"
        elif "▶" in line:
            title = "Загрузка страницы урока"
        elif "авторизац" in check:
            title = "Проверка авторизации"
        else:
            return False
        if self._download_title.value != title:
            self._download_title.value = title
            return True
        return False

    def _refresh_title(self, changed: bool):
        if changed:
            with contextlib.suppress(IndexError, RuntimeError):
                self.page.update()

    def _add_log(self, line: str):
        title_changed = self._update_download_title(line)
        if not self._should_log(line):
            self._refresh_title(title_changed)
            return
        self.log_lines.append(line)
        color = self._log_color(line)
        self._log_column.controls.append(ft.Text(line, size=13, color=color, selectable=False))
        try:
            self.page.update()
            self._scroll_smooth()
        except (IndexError, RuntimeError):
            pass

    def _update_last_log(self, line: str):
        title_changed = self._update_download_title(line)
        if not self._should_log(line):
            self._refresh_title(title_changed)
            return
        if self._log_column.controls:
            last = self._log_column.controls[-1]
            if (
                isinstance(last, ft.Text)
                and self._is_progress_line(line)
                and self._is_progress_line(last.value)
            ):
                last.value = line
                last.color = self._log_color(line)
                if self.log_lines:
                    self.log_lines[-1] = line
                try:
                    self.page.update()
                    self._scroll_smooth()
                except (IndexError, RuntimeError):
                    pass
                return
        self._add_log(line)

    def _show_continue_btn(self):
        self._continue_btn.visible = True
        self.page.update()

    def _switch_overlay_to_download(self):
        if self._auth_overlay_task is not None:
            self._auth_overlay_task.cancel()
            self._auth_overlay_task = None

        self._download_title.value = "Подготовка"
        self._overlay_card.content = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            controls=[
                ft.ProgressRing(width=40, height=40, color=Color.ACCENT, stroke_width=4),
                self._download_title,
                self._log_container,
                self._continue_btn,
            ],
        )
        self.page.update()

    def _switch_overlay_to_auth(self):
        if self._auth_overlay_task is not None:
            self._auth_overlay_task.cancel()
            self._auth_overlay_task = None

        self._continue_btn.visible = False
        self._auth_status.value = "Требуется авторизация"
        self._overlay_card.content = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
            controls=[
                self._auth_icon,
                self._auth_title,
                self._auth_desc,
                self._auth_instructions,
                self._auth_status,
                self._continue_btn,
            ],
        )
        self.page.update()

        try:
            loop = asyncio.get_running_loop()
            self._auth_overlay_task = loop.create_task(self._auth_overlay_countdown())
        except RuntimeError:
            self._continue_btn.visible = True
            self.page.update()

    async def _auth_overlay_countdown(self):
        try:
            for i in range(5, 0, -1):
                self._auth_status.value = f"Браузер откроется через {i} сек."
                try:
                    self.page.update()
                except Exception:
                    return
                await asyncio.sleep(1)

            self._auth_status.value = "Войдите в аккаунт в браузере"
            self._continue_btn.visible = True
            with contextlib.suppress(Exception):
                self.page.update()
        except asyncio.CancelledError:
            pass

    def _send_continue(self, e):
        self._continue_btn.visible = False
        self._switch_overlay_to_download()
        self.page.update()
        if hasattr(self, "_proc_stdin") and self._proc_stdin:
            try:
                self._proc_stdin.write("\n")
                self._proc_stdin.flush()
            except Exception:
                pass

    def _start_download(self, e):
        selected = [cb for cb in self._register if cb.value]
        if not selected:
            self._show_snack("Нет выбранных уроков", is_error=True)
            return
        if self._downloading:
            return

        if not Path(self._save_path).is_dir():
            self.error_overlay.visible = True
            self.page.update()
            return

        self._downloading = True
        self.log_lines.clear()
        self._log_column.controls.clear()
        self._continue_btn.visible = False
        self._proc_stdin = None

        self._switch_overlay_to_download()
        self._overlay_card.opacity = 0
        self._overlay_card.offset = ft.Offset(0, 0.15)
        self.overlay.visible = True
        self.page.update()
        self._overlay_card.opacity = 1
        self._overlay_card.offset = ft.Offset(0, 0)
        self.page.update()

        self._add_log(f"Старт скачивания: {len(selected)} уроков")
        print(f"\n🚀 Старт скачивания: {len(selected)} уроков")
        print(f"   Качество: {self._quality}")
        print(f"   Папка: {self._save_path}")

        lessons_to_download = []
        for idx, course in enumerate(self.data):
            refs = self.lesson_refs.get(idx, [])
            for i, cb in enumerate(refs):
                if cb.value and i < len(course["lessons"]):
                    lessons_to_download.append(
                        {
                            "course_title": course["course_title"],
                            "lesson": course["lessons"][i],
                        }
                    )

        threading.Thread(
            target=self._run_download,
            args=(lessons_to_download,),
            daemon=True,
        ).start()

    def _run_download(self, lessons: list):
        import json
        import os
        import subprocess
        import sys
        import tempfile

        page = self.page
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(lessons, tmp, ensure_ascii=False)
            lessons_file = tmp.name
        try:
            if getattr(sys, "frozen", False):
                entry = [sys.executable]
            else:
                entry = [
                    sys.executable,
                    str(Path(__file__).resolve().parent.parent.parent / "main.py"),
                ]
            print(f"▶ Запуск воркера: {entry} --download-worker")
            proc = subprocess.Popen(
                [
                    *entry,
                    "--download-worker",
                    "--quality",
                    self._quality,
                    "--save-path",
                    self._save_path,
                    "--lessons-file",
                    lessons_file,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            self._proc_stdin = proc.stdin
            download_issue: str | None = None
            summary_lines: list[str] = []

            for raw_line in proc.stdout or []:
                line = raw_line.rstrip("\n\r")
                if not line:
                    continue

                if line.startswith(_SUMMARY_PREFIX):
                    line = line[len(_SUMMARY_PREFIX) :].strip()
                    summary_lines.append(line)

                print(line)

                check = line.lower()

                if "master playlist не получен" in check:
                    download_issue = "Master playlist не получен"

                if "открываю браузер" in check and "входа" in check:
                    page.run_thread(lambda: self._switch_overlay_to_auth())
                    continue

                if "\r" in line:
                    parts = line.split("\r")
                    clean = parts[-1].strip()
                    if clean:
                        page.run_thread(partial(self._update_last_log, clean))
                else:
                    page.run_thread(partial(self._add_log, line))

                if "нажмите enter" in check and "выполнен" not in check:
                    page.run_thread(lambda: self._show_continue_btn())

            proc.wait()

            summary_header, failed = CoursesScreen._parse_summary(summary_lines)

            if proc.returncode == 0:
                print("✅ Загрузка завершена")
                print("Сэкономил время? Поддержи проект")
                print(f"   {_GITHUB_URL}")
                message = "\n".join(summary_header) or "Загрузка завершена"
                page.run_thread(lambda: self._finish_download(message, failed=failed))
            elif proc.returncode == 2:
                message = (
                    "\n".join(summary_header)
                    or download_issue
                    or ("Не удалось скачать все выбранные уроки")
                )
                page.run_thread(
                    lambda: self._finish_download(message, failed=failed, is_warning=True)
                )
            else:
                err = f"Код ошибки: {proc.returncode}"
                print(f"❌ {err}")
                page.run_thread(lambda: self._finish_download(f"Ошибка: {err}", is_error=True))
        except Exception as ex:
            err = str(ex)
            print(f"❌ Ошибка загрузки: {err}")
            page.run_thread(lambda: self._finish_download(f"Ошибка: {err}", is_error=True))
        finally:
            self._proc_stdin = None
            with contextlib.suppress(OSError):
                os.unlink(lessons_file)

    def _finish_download(
        self,
        message: str,
        is_error: bool = False,
        is_warning: bool = False,
        failed: list[str] | None = None,
    ):
        self._downloading = False
        self._show_completion_overlay(message, is_error, is_warning, failed)

    def _show_completion_overlay(
        self,
        message: str,
        is_error: bool = False,
        is_warning: bool = False,
        failed: list[str] | None = None,
    ):
        if is_error:
            icon_name, icon_color, title = ft.Icons.ERROR_ROUNDED, Color.RED, "Ошибка"
        elif is_warning:
            icon_name, icon_color, title = (
                ft.Icons.WARNING_AMBER_ROUNDED,
                Color.YELLOW,
                "Ошибка загрузки",
            )
        else:
            icon_name, icon_color, title = (
                ft.Icons.CHECK_CIRCLE_ROUNDED,
                Color.GREEN,
                "Загружено",
            )

        close_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=20,
            icon_color=Color.TEXT_SECONDARY,
            padding=8,
            hover_color="rgba(255,77,79,0.12)",
            splash_color="rgba(255,77,79,0.18)",
            mouse_cursor=ft.MouseCursor.CLICK,
            on_click=self._close_completion_overlay,
        )
        close_container = ft.Container(
            content=close_button,
            border_radius=10,
            bgcolor="rgba(255,255,255,0.0)",
            scale=1.0,
            animate_scale=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        def _on_close_hover(e):
            if e.data == "true":
                close_button.icon_color = "#ff4d4f"
                close_container.scale = 1.1
                close_container.bgcolor = "rgba(255,77,79,0.12)"
                close_container.shadow = ft.BoxShadow(
                    blur_radius=24,
                    color="rgba(255,77,79,0.45)",
                    offset=ft.Offset(0, 0),
                )
            else:
                close_button.icon_color = Color.TEXT_SECONDARY
                close_container.scale = 1.0
                close_container.bgcolor = "rgba(255,255,255,0.0)"
                close_container.shadow = None
            self.page.update()

        close_container.on_hover = _on_close_hover

        controls: list[ft.Control] = [
            ft.Container(
                margin=ft.Margin.only(right=-5, top=-5),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.END,
                    controls=[close_container],
                ),
            ),
            ft.Container(height=12),
            ft.Container(
                width=64,
                height=64,
                border_radius=32,
                bgcolor=ft.Colors.with_opacity(0.15, icon_color),
                content=ft.Icon(icon_name, size=36, color=icon_color),
            ),
            ft.Container(height=18),
            ft.Text(
                title,
                size=22,
                weight=ft.FontWeight.W_700,
                color=Color.TEXT,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(height=8),
        ]
        if failed:
            controls.append(
                ft.Text(
                    message,
                    size=14,
                    color=Color.TEXT_SECONDARY,
                    text_align=ft.TextAlign.CENTER,
                ),
            )
            controls.append(ft.Container(height=10))
            controls.append(self._build_failed_lessons(failed))
        else:
            controls.append(
                ft.Text(
                    message,
                    size=14,
                    color=Color.TEXT_SECONDARY,
                    text_align=ft.TextAlign.CENTER,
                ),
            )

        if not is_error:
            controls.append(ft.Container(height=18))
            controls.append(
                ft.Container(
                    height=1,
                    width=380,
                    bgcolor="rgba(255,255,255,0.07)",
                ),
            )
            controls.append(ft.Container(height=20))
            controls.extend(self._build_support_block())

        controls.append(ft.Container(height=8))

        self._overlay_card.content = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
            controls=controls,
        )
        self.overlay.visible = True
        self.page.update()

    def _build_failed_lessons(self, failed: list[str]) -> ft.Container:
        """Скроллируемый список уроков, которые не удалось скачать."""
        rows: list[ft.Control] = []
        for line in failed:
            title = line[1:].strip() if line.startswith("✗") else line
            rows.append(
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.CLOSE_ROUNDED, size=14, color=Color.RED),
                        ft.Text(title, size=13, color=Color.TEXT_SECONDARY, selectable=False),
                    ],
                )
            )
        return ft.Container(
            width=420,
            height=180,
            border_radius=10,
            bgcolor="rgba(0,0,0,0.3)",
            border=ft.Border.all(1, "rgba(255,255,255,0.06)"),
            padding=ft.Padding.all(12),
            content=ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, controls=rows),
        )

    def _open_github(self, e=None):
        self._open_task = asyncio.create_task(self.page.launch_url(_GITHUB_URL))

    def _build_support_block(self) -> list[ft.Control]:
        """Блок «Поддержи проект»: ссылка на репозиторий + подсказка о звёздах."""
        link = ft.Text(
            spans=[
                ft.TextSpan(
                    text="Сэкономил время? ",
                    style=ft.TextStyle(size=14, color=Color.TEXT_SECONDARY),
                ),
                ft.TextSpan(
                    text="Поддержи проект",
                    style=ft.TextStyle(
                        size=14,
                        color=Color.ACCENT_LIGHT,
                        weight=ft.FontWeight.W_600,
                    ),
                    on_click=self._open_github,
                ),
            ],
            text_align=ft.TextAlign.CENTER,
        )
        return [
            ft.Column(
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.STAR_ROUNDED, size=18, color="#F59E0B"),
                            link,
                        ],
                    ),
                    ft.Text(
                        "Звёздочка помогает развитию проекта",
                        size=12,
                        color=Color.TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
            )
        ]

    def _close_completion_overlay(self, e=None):
        self.overlay.visible = False
        self.page.update()

    def _show_snack(self, message: str, is_error: bool = False):
        bg = "#1A0A0A" if is_error else "#0A1A15"
        icon = ft.Icons.ERROR_OUTLINE if is_error else ft.Icons.CHECK_CIRCLE_OUTLINE
        icon_color = Color.RED if is_error else Color.GREEN

        self.page.snack_bar = ft.SnackBar(  # type: ignore[attr-defined]
            content=ft.Row(
                [
                    ft.Icon(icon, color=icon_color, size=18),
                    ft.Text(message, color=Color.TEXT, size=13, expand=True),
                ],
                spacing=6,
            ),
            bgcolor=bg,
            shape=ft.RoundedRectangleBorder(radius=10),
            duration=4000,
            margin=ft.Margin.only(bottom=16, left=16, right=16),
            behavior=ft.SnackBarBehavior.FLOATING,
            elevation=8,
        )
        self.page.snack_bar.open = True  # type: ignore[attr-defined]
        self.page.update()
