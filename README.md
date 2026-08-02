<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white"/>
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/Flet-0.85-purple?logo=flutter&logoColor=white"/>
  <img src="https://img.shields.io/badge/Playwright-1.61-green?logo=playwright&logoColor=white"/>
  <img src="https://img.shields.io/badge/aiohttp-3.14-yellow?logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FFmpeg-red?logo=ffmpeg&logoColor=white"/>
  <img src="https://img.shields.io/badge/License-MIT-green"/>
</p>

<h1 align="center">GetCourse Video Downloader</h1>

<p align="center">
  Скачивайте видео с GetCourse на компьютер — просто и быстро.
</p>

<p align="center">
</p>



## Как скачать

1. **Скачайте** [GetCourseVideoDownloader-win-x64.zip](https://github.com/markpekun/getcourse-downloader/releases/latest/download/GetCourseVideoDownloader-win-x64.zip).
2. **Распакуйте** архив в любую папку.
3. **Запустите** `GetCourseVideoDownloader.exe`.

Ничего устанавливать не нужно - Python, FFmpeg и браузер уже внутри.

## Как пользоваться

1. Вставьте ссылку на страницу курса в поле и нажмите **«Загрузить курсы»**.
   Например: `https://school.example/teach/control/stream/view/id/123456789`
2. Потребуется вход - откроется браузер, войдите в аккаунт и нажмите **«Продолжить»**. В следующий раз вход не понадобится.
3. Отметьте нужные уроки галочками.
4. Выберите качество видео и папку для сохранения.
5. Нажмите **«Скачать выбранное»** и дождитесь завершения.

Готово — видео лежат в выбранной папке.

## Частые вопросы

**Windows пишет «Неизвестный издатель»?**
Нажмите **«Подробнее» → «Выполнить в любом случае»**. Это нормально — программа не подписана.

**Первый запуск долгий?**
Приложение распаковывает нужные файлы.

## Запуск из исходного кода

Для разработчиков. Требуется [Python 3.12+](https://www.python.org/downloads/).

```bash
# клонируйте репозиторий
git clone https://github.com/markpekun/getcourse-downloader.git
cd getcourse-downloader

# создайте и активируйте виртуальное окружение
python -m venv .venv
.venv\Scripts\activate

# установите зависимости
pip install -r req.txt

# установите браузер для Playwright
playwright install firefox

# установите FFmpeg (если ещё нет) — через winget:
winget install --id Gyan.FFmpeg -e
# или скачайте с официального сайта: https://ffmpeg.org/download.html
# FFmpeg должен быть добавлен в PATH (winget делает это автоматически)
```

Запуск:

```bash
python -m app.main
```



*Исходный код проекта: [markpekun/getcourse-downloader](https://github.com/markpekun/getcourse-downloader).*
*Лицензия: MIT.*
*Вопросы: [@No_Resp_404](https://t.me/No_Resp_404)*
