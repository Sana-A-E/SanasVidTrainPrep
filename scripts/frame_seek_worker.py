# frame_seek_worker.py
import cv2
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class FrameSeekWorker(QObject):
    """
    Background worker that owns a dedicated ``cv2.VideoCapture`` and performs
    frame-seek + decode operations on a ``QThread`` so the main UI thread is
    never blocked.

    **Threading contract**
    - This object must be moved to a ``QThread`` via ``moveToThread()`` before
      use.  All ``@pyqtSlot``-decorated methods are called on that worker thread
      via Qt's queued-connection mechanism.
    - ``frame_ready`` is emitted from the worker thread; Qt automatically
      delivers it to any main-thread slots via a queued connection.

    **"Latest wins" seek logic**
    If a new ``seek_to`` request arrives while the worker is already decoding a
    previous frame, the new request is stored in ``_latest_frame``.  Once the
    in-progress decode finishes, ``_drain()`` immediately picks up the latest
    request instead of processing the queue in FIFO order.  This ensures rapid
    slider movements only ever show the most recently requested frame.
    """

    # Emitted on the worker thread with (BGR frame as np.ndarray, frame_number).
    # Qt queues delivery to main-thread slots automatically.
    frame_ready = pyqtSignal(object, int)

    def __init__(self) -> None:
        super().__init__()
        self._cap: cv2.VideoCapture | None = None
        self._busy: bool = False
        self._latest_frame: int = -1   # -1 = no pending request

    # ------------------------------------------------------------------
    # Public slots — called from the main thread via queued connections
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def open_video(self, path: str) -> None:
        """
        Opens (or re-opens) the video at ``path`` with the fastest available
        backend.  Must be called whenever the active video changes.

        Args:
            path (str): Absolute path to the video file.
        """
        if self._cap:
            self._cap.release()
        self._cap = None
        for backend in (cv2.CAP_MSMF, cv2.CAP_FFMPEG, cv2.CAP_ANY):
            cap = cv2.VideoCapture(path, backend)
            if cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) > 0:
                self._cap = cap
                return
            cap.release()

    @pyqtSlot(int)
    def seek_to(self, frame_number: int) -> None:
        """
        Queues a seek request.  If the worker is already busy decoding,
        stores the request as the latest pending frame and returns immediately;
        ``_drain()`` will pick it up after the current decode finishes.

        Args:
            frame_number (int): Zero-based frame index to decode.
        """
        self._latest_frame = frame_number
        if not self._busy:
            self._drain()

    @pyqtSlot()
    def release(self) -> None:
        """Releases the internal capture.  Call before stopping the thread."""
        if self._cap:
            self._cap.release()
            self._cap = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drain(self) -> None:
        """
        Processes all pending seek requests in a tight loop, keeping only the
        latest result.  Intermediate requests are decoded but their frames are
        discarded (not emitted) so rapid slider movements don't cause an
        ever-growing backlog of displayed frames.
        """
        self._busy = True
        while self._latest_frame >= 0:
            fn = self._latest_frame
            self._latest_frame = -1
            if self._cap and self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, fn)
                ret, frame = self._cap.read()
                if ret and frame is not None and self._latest_frame < 0:
                    # Only emit if no newer request arrived while decoding
                    self.frame_ready.emit(frame.copy(), fn)
        self._busy = False
