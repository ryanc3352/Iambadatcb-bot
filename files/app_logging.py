"""The app's log file. The page's 🐞 button downloads its last few minutes for troubleshooting."""
import logging
import logging.handlers
import re
from datetime import datetime, timedelta
from pathlib import Path

LOG_FILE = "app.log"
BACKUPS = 2
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_TIME = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ")
_COLOUR = re.compile(r"\x1b\[[0-9;]*m")
_ROUTINE_REQUEST = re.compile(r'"GET [^"]*" [23]\d\d ')
# Libraries that log a lot at INFO level
QUIET_LOGGERS = ("urllib3", "httpx", "httpcore", "chromadb", "posthog", "primp", "ddgs", "hpack")


class _PlainFormatter(logging.Formatter):
    """Log lines without the colour codes the web server adds for the console."""

    def format(self, record):
        return _COLOUR.sub("", super().format(record))


def _not_routine(record):
    """Leave out the web server's lines for page loads and status checks that worked."""
    return not (record.name == "werkzeug" and _ROUTINE_REQUEST.search(_COLOUR.sub("", record.getMessage())))


def setup_logging(log_dir):
    """Log INFO and up to log_dir/app.log (rotated at 1 MB). Warnings and errors, and the
    web server's own lines, also show in the console window."""
    root = logging.getLogger()
    if any(getattr(handler, 'app_log', False) for handler in root.handlers):
        return
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    to_file = logging.handlers.RotatingFileHandler(log_dir / LOG_FILE, maxBytes=1_000_000,
                                                   backupCount=BACKUPS, encoding="utf-8")
    to_file.setFormatter(_PlainFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", TIME_FORMAT))
    to_file.addFilter(_not_routine)
    to_file.app_log = True
    to_console = logging.StreamHandler()
    to_console.setLevel(logging.WARNING)
    to_console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(to_file)
    root.addHandler(to_console)
    root.setLevel(logging.INFO)

    # "Running on http://127.0.0.1:5000" and request lines, as before
    server_console = logging.StreamHandler()
    server_console.addFilter(lambda record: record.levelno < logging.WARNING)
    logging.getLogger("werkzeug").addHandler(server_console)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def recent_lines(log_dir, minutes=5, now=None):
    """The log lines of the last `minutes` minutes, oldest first. Lines without a time
    (a traceback) go with the entry above them."""
    cutoff = (now or datetime.now()) - timedelta(minutes=minutes)
    log_dir = Path(log_dir)
    paths = [log_dir / f"{LOG_FILE}.{n}" for n in range(BACKUPS, 0, -1)] + [log_dir / LOG_FILE]
    lines, keep = [], False
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stamp = _TIME.match(line)
            if stamp:
                keep = datetime.strptime(stamp.group(1), TIME_FORMAT) >= cutoff
            if keep:
                lines.append(line)
    return lines
