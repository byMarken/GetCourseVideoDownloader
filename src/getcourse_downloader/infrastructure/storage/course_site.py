# ruff: noqa: E501
from __future__ import annotations

import hashlib
import html
from pathlib import Path
from urllib.parse import quote

from getcourse_downloader.domain.models import DownloadRequest, SelectedLesson
from getcourse_downloader.infrastructure.storage.download_catalog import (
    DownloadedMedia,
    JsonDownloadCatalog,
)


def _anchor(parts: tuple[str, ...]) -> str:
    identity = "\x1f".join(parts).encode("utf-8")
    return f"section-{hashlib.sha256(identity).hexdigest()[:12]}"


def _relative_url(path: Path, root: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return quote(relative.as_posix(), safe="/")


def _existing_media(
    item: SelectedLesson,
    stem: Path,
    catalog: JsonDownloadCatalog | None,
) -> tuple[DownloadedMedia, ...]:
    if catalog:
        media = catalog.find(item.lesson.url, stem)
        if media:
            return media

    discovered: list[DownloadedMedia] = []
    direct_video = stem.with_suffix(".mp4")
    if direct_video.is_file():
        discovered.append(DownloadedMedia(direct_video))
    if stem.is_dir():
        discovered.extend(DownloadedMedia(path) for path in sorted(stem.glob("*.mp4")))
    page = stem.with_suffix(".html")
    if page.is_file():
        discovered.append(DownloadedMedia(page, "HTML"))
    return tuple(discovered)


def generate_course_site(
    request: DownloadRequest,
    output_stems: list[Path],
    catalog: JsonDownloadCatalog | None,
) -> Path | None:
    """Create a dependency-free local course navigator for downloaded lessons."""

    groups: dict[tuple[str, ...], list[tuple[SelectedLesson, Path]]] = {}
    for item, stem in zip(request.lessons, output_stems, strict=True):
        groups.setdefault(item.course_path, []).append((item, stem))
    if not groups:
        return None

    root = request.save_path
    children: dict[tuple[str, ...], list[tuple[str, ...]]] = {(): []}
    for course_path in groups:
        for depth in range(1, len(course_path) + 1):
            parent = course_path[: depth - 1]
            child = course_path[:depth]
            children.setdefault(parent, [])
            children.setdefault(child, [])
            if child not in children[parent]:
                children[parent].append(child)

    def lesson_count(prefix: tuple[str, ...]) -> int:
        return sum(
            len(lessons) for path, lessons in groups.items() if path[: len(prefix)] == prefix
        )

    def breadcrumbs(path: tuple[str, ...]) -> str:
        links = [f'<a href="#{_anchor(())}">Главная</a>']
        for depth, title in enumerate(path, start=1):
            links.append(f'<a href="#{_anchor(path[:depth])}">{html.escape(title)}</a>')
        return '<span class="chevron">›</span>'.join(links)

    pages: list[str] = []
    for path, child_paths in children.items():
        title = path[-1] if path else "Содержание курса"
        parent = path[:-1] if path else ()
        tiles: list[str] = []
        for child in child_paths:
            count = lesson_count(child)
            tiles.append(
                f'<a class="tile folder" href="#{_anchor(child)}">'
                '<span class="tile-icon">▣</span>'
                f"<strong>{html.escape(child[-1])}</strong>"
                f"<small>{count} уроков</small></a>"
            )
        for lesson_index, (item, _stem) in enumerate(groups.get(path, []), start=1):
            lesson_anchor = _anchor((*path, item.lesson.url))
            media = _existing_media(item, _stem, catalog)
            quality = next(
                (entry.quality for entry in media if entry.path.suffix.casefold() == ".mp4"),
                "",
            )
            badge = html.escape(quality or ("материалы" if media else "не скачано"))
            tiles.append(
                f'<a class="tile lesson-tile" href="#{lesson_anchor}">'
                f'<span class="lesson-number">{lesson_index:02}</span>'
                f"<strong>{html.escape(item.lesson.title)}</strong>"
                f"<small>{badge}</small></a>"
            )
        back = f'<a class="back" href="#{_anchor(parent)}">← На уровень выше</a>' if path else ""
        empty = '<p class="missing">На этом уровне пока нет уроков</p>' if not tiles else ""
        pages.append(
            f'<section class="page" id="{_anchor(path)}">'
            f'<div class="crumbs">{breadcrumbs(path)}</div>{back}'
            f'<h2>{html.escape(title)}</h2><div class="tiles">{"".join(tiles)}</div>{empty}</section>'
        )

    for course_path, lessons in groups.items():
        for item, stem in lessons:
            media = _existing_media(item, stem, catalog)
            players: list[str] = []
            documents: list[str] = []
            for media_item in media:
                url = _relative_url(media_item.path, root)
                if url is None:
                    continue
                suffix = media_item.path.suffix.casefold()
                if suffix == ".mp4":
                    quality = html.escape(media_item.quality or "видео")
                    players.append(
                        '<div class="media"><span class="quality">'
                        f'{quality}</span><video controls preload="metadata" '
                        f'src="{url}"></video></div>'
                    )
                elif suffix == ".html":
                    documents.append(
                        "<details><summary>Описание и материалы урока</summary>"
                        f'<iframe loading="lazy" src="{url}"></iframe></details>'
                    )
            state = "" if players or documents else '<p class="missing">Ещё не скачано</p>'
            lesson_anchor = _anchor((*course_path, item.lesson.url))
            pages.append(
                f'<section class="page lesson-page" id="{lesson_anchor}">'
                f'<div class="crumbs">{breadcrumbs(course_path)}</div>'
                f'<a class="back" href="#{_anchor(course_path)}">← К списку уроков</a>'
                '<article class="lesson">'
                f"<h3>{html.escape(item.lesson.title)}</h3>"
                f'<a class="source" href="{html.escape(item.lesson.url)}">Оригинал урока</a>'
                f"{''.join(players)}{''.join(documents)}{state}</article></section>"
            )

    document = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Локальная библиотека курса</title>
<style>
:root{{--bg:#0b0b18;--panel:#17172d;--card:#222241;--text:#f5f3ff;--muted:#aaa7c2;--accent:#8b4dff}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}}
header{{position:sticky;top:0;z-index:2;padding:18px 5vw;background:#101021f2;border-bottom:1px solid #343252}}
header a{{color:var(--text);text-decoration:none}} main{{width:min(1500px,92vw);margin:0 auto;padding:34px 0 80px}}
.page{{display:none}} .page.active{{display:block}} h2{{font-size:clamp(26px,3vw,42px);margin:18px 0 26px}}
.crumbs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}} .crumbs a,.source,.quality{{color:#bda7ff;font-size:13px}}
.chevron{{color:#67627d}} .back{{display:inline-block;color:#ddd5ff;text-decoration:none;margin:8px 0}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:18px}}
.tile{{min-height:180px;padding:22px;display:flex;flex-direction:column;gap:10px;color:var(--text);text-decoration:none;background:linear-gradient(145deg,#252344,#17172d);border:1px solid #3a3762;border-radius:20px;transition:.18s transform,.18s border-color}}
.tile:hover{{transform:translateY(-4px);border-color:var(--accent)}} .tile strong{{font-size:20px}} .tile small{{margin-top:auto;color:var(--muted)}}
.tile-icon{{font-size:34px;color:var(--accent)}} .lesson-number{{font-size:30px;font-weight:800;color:#9a69ff}}
.lesson{{background:var(--card);padding:20px;margin:14px 0;border:1px solid #37345c;border-radius:16px}}
.lesson h3{{font-size:clamp(24px,3vw,38px);margin:0 0 4px}} .source{{display:inline-block;margin-bottom:16px}} video{{width:100%;max-height:76vh;background:#000;border-radius:12px}}
.media{{position:relative;margin-top:12px}} .quality{{display:inline-block;margin-bottom:5px}} details{{margin-top:14px}}
summary{{cursor:pointer;color:#d7c8ff}} iframe{{width:100%;height:70vh;margin-top:10px;background:white;border:0;border-radius:12px}}
.missing{{color:#d9a35f}} @media(max-width:600px){{.tiles{{grid-template-columns:1fr}}main{{width:90vw}}}}
</style></head><body><header><a href="#{_anchor(())}"><h1>Локальная библиотека курса</h1></a></header>
<main>{"".join(pages)}</main>
<script>
function route(){{const id=location.hash.slice(1)||'{_anchor(())}';const pages=[...document.querySelectorAll('.page')];let target=document.getElementById(id);if(!target)target=document.getElementById('{_anchor(())}');pages.forEach(p=>p.classList.toggle('active',p===target));document.querySelectorAll('video').forEach(v=>{{if(!target.contains(v))v.pause()}});scrollTo(0,0)}}
addEventListener('hashchange',route);route();
</script></body></html>
"""
    output = root / "index.html"
    root.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output
