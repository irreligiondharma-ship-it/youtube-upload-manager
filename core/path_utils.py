import os
from typing import Iterable, Optional


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def first_existing_path(candidates: Iterable[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return normalize_path(candidate)
    return None