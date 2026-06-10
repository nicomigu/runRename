from pathlib import Path

from fastapi.templating import Jinja2Templates

_static_dir = Path(__file__).resolve().parent / "static"


def _static_url(path: str) -> str:
    file = _static_dir / path
    try:
        mtime = int(file.stat().st_mtime)
    except OSError:
        mtime = 0
    return f"/static/{path}?v={mtime}"


def register_globals(templates: Jinja2Templates) -> None:
    templates.env.globals["static_url"] = _static_url
