"""A connection wrapper: thread-safe send that never raises into game logic."""
import threading

from . import log


class Conn:
    def __init__(self, sock, kind, session=None):
        self.sock = sock
        self.kind = kind              # "user" or "game"
        self.session = session
        self.closed = False
        self._lock = threading.Lock()

    def send(self, data, label=""):
        """Send one message; returns False (and marks the connection closed)
        if the socket is gone instead of raising."""
        if self.closed:
            return False
        try:
            with self._lock:
                self.sock.sendall(data)
        except OSError as e:
            self.closed = True
            log.info(f"{self.kind} connection lost while sending {label or 'data'}: {e}", self.session)
            return False
        if label is not None:          # None = high-rate updates (walking), not logged
            log.traffic(f"{self.kind} >>", label, data, self.session)
        return True

    def send_all(self, labelled):
        for label, data in labelled:
            if not self.send(data, label):
                return False
        return True

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
