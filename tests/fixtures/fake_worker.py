import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--request-file", required=True)
parser.add_argument("--events-file", required=True)
parser.add_argument("--commands-file", required=True)
args = parser.parse_args()

events = [
    {
        "protocol_version": 2,
        "type": "lesson_failed",
        "message": "Не удалось скачать: Урок",
        "lesson": "Урок",
    },
    {
        "protocol_version": 2,
        "type": "summary",
        "message": "Загружено: 0 из 1",
        "current": 0,
        "total": 1,
        "downloaded": 0,
        "already_present": 0,
        "no_video": 0,
        "failed_count": 1,
        "cancelled": 0,
    },
]
with open(args.events_file, "a", encoding="utf-8") as stream:
    for event in events:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
