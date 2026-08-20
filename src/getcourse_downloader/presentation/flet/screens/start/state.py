from dataclasses import dataclass


@dataclass(slots=True)
class StartViewState:
    parse_running: bool = False
    discovery_visible: bool = False
    total_parsed: int = 0
