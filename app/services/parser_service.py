import json

from app.utils.paths import data_dir

COURSES_FILE = data_dir() / "courses.json"


def has_courses() -> bool:
    if not COURSES_FILE.exists():
        return False
    try:
        data = json.loads(COURSES_FILE.read_text(encoding="utf-8"))
        return len(data) > 0
    except Exception:
        return False


def run_parser(url: str) -> None:
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "app/scripts/parse_courses.py", url],
        check=True,
    )
