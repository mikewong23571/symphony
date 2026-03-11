import os

from .base import *  # noqa: F403

DEBUG = True

_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts.split(",") if host.strip()]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "dev": {
            "format": "[{levelname}] {name}: {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "dev",
        }
    },
    "loggers": {
        "symphony": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        }
    },
}
