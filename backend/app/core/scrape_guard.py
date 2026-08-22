"""进程内抓取互斥，避免手动同步与后台同步同时撞淘宝接口。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator


_SCRAPE_LOCK = threading.RLock()


@contextmanager
def exclusive_scrape() -> Iterator[None]:
    with _SCRAPE_LOCK:
        yield
