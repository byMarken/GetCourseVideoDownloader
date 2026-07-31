from app.scripts.parse_courses import clean_title


def test_clean_title_removes_status_words():
    assert clean_title("Введение Просмотрено") == "Введение"
    assert clean_title("Модуль 1 Пройдено") == "Модуль 1"
    assert clean_title("Заключение Завершено") == "Заключение"


def test_clean_title_collapses_whitespace():
    assert clean_title("Лекция   1") == "Лекция 1"
    assert clean_title("  Введение  ") == "Введение"
