from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from getcourse_downloader.application.ports.discovery import CourseDiscoveryUpdate
from getcourse_downloader.bootstrap import build_container


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Получить список курсов GetCourse")
    parser.add_argument("url", help="URL страницы курса или списка курсов")
    return parser


async def _run(url: str) -> int:
    container = build_container()

    async def wait_for_auth(message: str) -> None:
        print(f"[AUTH] {message}")
        await asyncio.get_running_loop().run_in_executor(None, input)

    async def course_found(update: CourseDiscoveryUpdate) -> None:
        status = f"{update.lesson_count} уроков" if update.loaded else "найден"
        print(f"[FOLDER] {update.title}: {status}")

    courses = await container.discover_courses.execute(
        url,
        on_auth_required=wait_for_auth,
        on_course_discovered=course_found,
    )
    print(f"[OK] Сохранено курсов: {len(courses)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args.url))


if __name__ == "__main__":
    raise SystemExit(main())
