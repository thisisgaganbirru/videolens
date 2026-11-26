import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def configure_worker_logging() -> None:
    """`configure_logging` for the arq worker. arq's CLI has already given
    the `arq` logger its own plain-text handler, which would print each of
    its lines a second time once the root logger has one; dropping it sends
    arq's lines through the same JSON handler, once."""
    configure_logging()
    logging.getLogger("arq").handlers = []
