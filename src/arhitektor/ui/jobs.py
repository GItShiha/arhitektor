"""One serial worker: writes and subsequent reads preserve submission order."""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger(__name__)


class Jobs(QObject):
    completed = Signal(object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arhitektor-db")
        self.completed.connect(self.deliver)

    def submit(self, operation: Callable[[], Any], success: Callable, failure: Callable) -> None:
        def run():
            try:
                result = operation()
            except Exception as error:
                log.exception("Операция не выполнена")
                self.completed.emit(failure, str(error), None)
            else:
                self.completed.emit(success, result, None)

        self.pool.submit(run)

    @Slot(object, object, object)
    def deliver(self, callback, result, _unused):
        callback(result)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True)
