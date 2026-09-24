#!/usr/bin/env python3
"""Run one ROS node on a dedicated executor thread with bounded shutdown."""

from __future__ import annotations

import threading


class RosExecutorThread:
    """Own an executor thread and expose terminal executor failures."""

    def __init__(self, executor, node, *, name, join_timeout_sec=1.0):
        self.executor = executor
        self.node = node
        self.name = str(name)
        self.join_timeout_sec = float(join_timeout_sec)
        self._error = None
        self._error_lock = threading.Lock()
        self._closed = False
        if not self.executor.add_node(self.node):
            raise RuntimeError(f"failed to add ROS node to executor: {self.name}")
        self.thread = threading.Thread(
            target=self._run,
            name=self.name,
            daemon=True,
        )
        self.thread.start()

    def _run(self):
        try:
            self.executor.spin()
        except Exception as error:  # Report asynchronously on the caller thread.
            with self._error_lock:
                self._error = error

    def error(self):
        with self._error_lock:
            return self._error

    def raise_if_failed(self):
        error = self.error()
        if error is not None:
            raise RuntimeError(
                f"ROS executor {self.name} stopped: "
                f"{type(error).__name__}: {error}"
            ) from error

    def close(self):
        if self._closed:
            return
        self._closed = True
        stopped = self.executor.shutdown(timeout_sec=self.join_timeout_sec)
        self.thread.join(timeout=self.join_timeout_sec)
        if not stopped or self.thread.is_alive():
            raise RuntimeError(
                f"ROS executor did not stop within "
                f"{self.join_timeout_sec:.1f}s: {self.name}"
            )
