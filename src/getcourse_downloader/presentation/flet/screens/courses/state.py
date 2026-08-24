from dataclasses import dataclass, field


@dataclass(slots=True)
class CoursesViewState:
    save_path: str
    quality: str = "auto"
    downloading: bool = False
    cancelling: bool = False
    selected_lesson_urls: set[str] = field(default_factory=set)
    expanded_course_urls: set[str] = field(default_factory=set)
    search_query: str = ""
