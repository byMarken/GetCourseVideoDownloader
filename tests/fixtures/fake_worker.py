import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--request-file", required=True)
parser.parse_args()

print(
    json.dumps(
        {
            "protocol_version": 1,
            "type": "lesson_failed",
            "message": "Не удалось скачать: Урок",
            "lesson": "Урок",
        },
        ensure_ascii=False,
    ),
    flush=True,
)
print(
    json.dumps(
        {
            "protocol_version": 1,
            "type": "summary",
            "message": "Загружено: 0 из 1",
            "current": 0,
            "total": 1,
        },
        ensure_ascii=False,
    ),
    flush=True,
)
