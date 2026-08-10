from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import flet as ft

from getcourse_downloader.domain.models import Course
from getcourse_downloader.presentation.flet.theme import (
    Color,
    Gradient,
    Shadow,
    body_text,
)


@dataclass(frozen=True, slots=True)
class CourseCardView:
    control: ft.Container
    checkboxes: list[ft.Checkbox]


def build_course_card(
    course: Course,
    *,
    index: int,
    accent: str,
    expanded: bool,
    on_toggle: Callable[[int], None],
    on_selection_changed: Callable,
) -> CourseCardView:
    checkboxes = [
        ft.Checkbox(
            label=lesson.title,
            value=False,
            tristate=False,
            on_change=on_selection_changed,
            active_color=accent,
            check_color=Color.TEXT,
            fill_color={
                ft.ControlState.DEFAULT: ft.Colors.with_opacity(0.08, accent),
                ft.ControlState.SELECTED: accent,
            },
            label_style=ft.TextStyle(size=14, color=Color.TEXT, weight=ft.FontWeight.W_400),
            semantics_label=lesson.title,
        )
        for lesson in course.lessons
    ]
    lesson_list = ft.Column(spacing=2, controls=cast(list[ft.Control], checkboxes))
    body: ft.Control = lesson_list if expanded else ft.Container(height=0)
    selected_count = sum(1 for checkbox in checkboxes if checkbox.value)

    control = ft.Container(
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
                    on_click=lambda _: on_toggle(index),
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
                                                course.title,
                                                size=16,
                                                weight=ft.FontWeight.W_600,
                                                color=Color.TEXT,
                                            ),
                                            body_text(f"{len(course.lessons)} уроков", size=12),
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
                                        if expanded
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
    return CourseCardView(control=control, checkboxes=checkboxes)
