import logging
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logging(settings):
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger("pipeline")
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
    fh = TimedRotatingFileHandler(settings.LOG_FILE, when="midnight", backupCount=30)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    return root
