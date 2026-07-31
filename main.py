import asyncio
import io
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _prepare_worker_stdio() -> None:
    for fd, name in ((0, "stdin"), (1, "stdout"), (2, "stderr")):
        stream = getattr(sys, name, None)
        if stream is not None and hasattr(stream, "fileno"):
            try:
                if stream.fileno() >= 0:
                    continue
            except Exception:
                pass
        try:
            mode = "rb" if name == "stdin" else "wb"
            setattr(sys, name, io.TextIOWrapper(os.fdopen(fd, mode), encoding="utf-8"))
        except OSError:
            pass


if __name__ == "__main__":
    if "--download-worker" in sys.argv:
        from app.services.givereq import main as worker_main

        _prepare_worker_stdio()
        sys.argv = [arg for arg in sys.argv if arg != "--download-worker"]
        raise SystemExit(asyncio.run(worker_main()))

    import flet as ft

    from app.main import main

    ft.run(main)
