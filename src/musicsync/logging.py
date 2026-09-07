import logging
from logging.handlers import RotatingFileHandler
import re
from musicsync.settings import state_dir


def clean(text):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).encode("utf-8", "backslashreplace").decode("utf-8")


def setup_logging():
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("musicsync")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(folder / "musicsync.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger
