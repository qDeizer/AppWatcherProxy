import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_diagnostics(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("network-inspector")
    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        handler = RotatingFileHandler(
            runtime_dir / "diagnostics.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)


def report_exception(event: str, error: BaseException) -> None:
    frames = traceback.extract_tb(error.__traceback__)
    location = " > ".join(f"{Path(frame.filename).name}:{frame.lineno}" for frame in frames)
    logging.getLogger("network-inspector").error("%s %s %s", event, type(error).__name__, location)
