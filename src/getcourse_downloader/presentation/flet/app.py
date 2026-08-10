from __future__ import annotations

import flet as ft

from getcourse_downloader.bootstrap import AppContainer, build_container
from getcourse_downloader.presentation.flet.screens.courses.controller import CoursesController
from getcourse_downloader.presentation.flet.screens.courses.view import CoursesScreen
from getcourse_downloader.presentation.flet.screens.start.controller import StartController
from getcourse_downloader.presentation.flet.screens.start.view import StartScreen
from getcourse_downloader.presentation.flet.theme import Color, build_theme

_START_WIN_W, _START_WIN_H = 680, 460
_COURSES_WIN_W, _COURSES_WIN_H = 1400, 850


class App:
    def __init__(self, page: ft.Page, container: AppContainer | None = None) -> None:
        self.page = page
        self.container = container or build_container()
        page.title = "GetCourse Video Downloader"
        page.dark_theme = build_theme()
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 0
        page.spacing = 0
        page.bgcolor = Color.BG_DARK
        page.window.min_width = 520
        page.window.min_height = 420

    async def show_initial_screen(self) -> None:
        if self.container.courses.has_courses():
            await self.show_courses()
        else:
            await self.show_start()

    async def show_courses(self) -> None:
        self.page.clean()
        self.page.window.width = _COURSES_WIN_W
        self.page.window.height = _COURSES_WIN_H
        controller = CoursesController(
            self.container.courses,
            self.container.settings,
            self.container.download_lessons,
        )
        self.page.add(CoursesScreen(self.page, controller, self.show_start).view)
        await self.page.window.center()
        self.page.update()

    async def show_start(self) -> None:
        self.page.clean()
        self.page.window.width = _START_WIN_W
        self.page.window.height = _START_WIN_H
        controller = StartController(self.container.discover_courses)
        self.page.add(StartScreen(self.page, controller, self.show_courses).view)
        await self.page.window.center()
        self.page.update()


async def main(page: ft.Page) -> None:
    await App(page).show_initial_screen()


def run() -> None:
    ft.run(main)


if __name__ == "__main__":
    run()
