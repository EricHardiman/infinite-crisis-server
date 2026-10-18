"""One scheduler thread for every delayed or repeating action.

The old server started a new threading.Timer for each delay; nothing cancelled
them, so a timer from a previous match could fire into the next one. Here
every job belongs to a group (a session or a match) and closing the group
cancels all its jobs at once.
"""
import heapq
import itertools
import threading
import time
import traceback


class Group:
    def __init__(self, name):
        self.name = name
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Scheduler:
    def __init__(self):
        self._heap = []
        self._counter = itertools.count()
        self._cv = threading.Condition()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()

    def after(self, delay, fn, group):
        """Run fn() once after delay seconds unless the group is cancelled."""
        with self._cv:
            heapq.heappush(self._heap, (time.monotonic() + delay, next(self._counter), fn, group, None))
            self._cv.notify()

    def every(self, interval, fn, group, first_delay=None):
        """Run fn() every interval seconds until the group is cancelled or fn returns False."""
        with self._cv:
            start = time.monotonic() + (interval if first_delay is None else first_delay)
            heapq.heappush(self._heap, (start, next(self._counter), fn, group, interval))
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._heap or self._heap[0][0] > time.monotonic():
                    timeout = self._heap[0][0] - time.monotonic() if self._heap else None
                    self._cv.wait(timeout)
                when, _, fn, group, interval = heapq.heappop(self._heap)
            if group.cancelled:
                continue
            try:
                result = fn()
            except Exception:
                traceback.print_exc()
                result = None
            if interval is not None and result is not False and not group.cancelled:
                with self._cv:
                    nxt = max(when + interval, time.monotonic())
                    heapq.heappush(self._heap, (nxt, next(self._counter), fn, group, interval))
                    self._cv.notify()
