from dataclasses import dataclass


@dataclass(slots=True)
class CoursesViewState:
    save_path: str
    quality: str = "auto"
    downloading: bool = False
