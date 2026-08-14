<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white" alt="Windows 10/11"/>
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white" alt="Python 3.12+"/>
  <img src="https://img.shields.io/badge/Flet-0.85-purple?logo=flutter&logoColor=white" alt="Flet 0.85"/>
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"/>
</p>

<h1 align="center">GetCourse Video Downloader</h1>

<p align="center">
  Windows-приложение для сохранения доступных пользователю видеоуроков GetCourse.
</p>

<p align="center">
  <img
    src="https://raw.githubusercontent.com/markpekun/getcourse-downloader-assets/main/picture/courses.png"
    alt="Интерфейс GetCourse Video Downloader"
    width="1200"
  />
</p>

## Возможности

- Авторизация через отдельный профиль Firefox.
- Получение курсов и уроков из старой и современной разметки GetCourse.
- Выбор отдельных уроков и качества видео.
- Загрузка HLS-сегментов с повторами и контролем целостности.
- Сборка MP4 через FFmpeg.
- Изолированный worker-процесс с типизированным JSONL-протоколом.
- Автоматическая сборка Windows-релизов, SHA-256 и SBOM.

> [!IMPORTANT]
> Используйте приложение только для материалов, к которым у вас есть законный доступ,
> и соблюдайте правила платформы и автора курса. Проект не предназначен для обхода
> авторизации или технических ограничений доступа.

## Установка и запуск

1. Скачайте `GetCourseVideoDownloader-win-x64.zip` из
   [последнего релиза](https://github.com/markpekun/getcourse-downloader/releases/latest).
2. При желании проверьте архив по расположенному рядом `.sha256` файлу.
3. Полностью распакуйте ZIP-архив в отдельную папку: нажмите на него правой кнопкой
   мыши и выберите **«Извлечь всё»**.
4. Откройте распакованную папку и запустите `GetCourseVideoDownloader.exe`.

> [!NOTE]
> Не запускайте приложение прямо из ZIP-архива - сначала обязательно распакуйте
> всё его содержимое.

Python, Firefox и FFmpeg входят в release-архив.

## Использование

1. Вставьте ссылку на курс или страницу списка курсов.
2. При первом запуске войдите в GetCourse в открывшемся Firefox.
3. Отметьте нужные уроки.
4. Выберите качество и папку сохранения.
5. Нажмите **«Скачать выбранное»**.

Профиль браузера и настройки хранятся в пользовательской папке приложения, а не
внутри установленного каталога. Существующие данные старых версий автоматически
подхватываются при первом запуске.

## Запуск из исходного кода

Требуются Windows, [Python 3.12+](https://www.python.org/downloads/) и
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
git clone https://github.com/markpekun/getcourse-downloader.git
cd getcourse-downloader
uv sync --locked --group dev
uv run playwright install firefox
uv run getcourse-downloader
```

Проверки качества:

```powershell
uv run ruff check src tests main.py
uv run ruff format --check src tests main.py
uv run mypy src main.py
uv run pytest
```

## Сборка EXE

```powershell
.\build.ps1
```

Скрипт синхронизирует зависимости из `uv.lock`, проверит Firefox и FFmpeg, соберёт
приложение, выполнит smoke-test worker’а и создаст:

```text
dist/GetCourseVideoDownloader-win-x64.zip
dist/GetCourseVideoDownloader-win-x64.zip.sha256
```

## Архитектура

Проект построен как модульный монолит с ports & adapters:

```text
Flet / CLI -> application use cases -> domain
                         ^
Playwright / HLS / FFmpeg / JSON adapters
```

Подробное описание находится в [ARCHITECTURE.md](ARCHITECTURE.md).

## Лицензия

[MIT](LICENSE). Вопросы по использованию: [@No_Resp_404](https://t.me/No_Resp_404).
