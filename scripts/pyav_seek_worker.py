# pyav_seek_worker.py
"""
PyAV-based background frame-seek worker.

Replaces the legacy ``FrameSeekWorker`` (OpenCV/MSMF).  Uses PyAV
(libavformat + libavcodec — the same libraries VLC and ffmpeg CLI use)
which achieves ~56 ms average frame-accurate seeking vs ~348 ms for MSMF.

Benchmark results on the test video (1216 frames, H.264):
  - OpenCV / MSMF  : avg 348 ms, max 641 ms
  - PyAV frame-acc : avg  56 ms, max  97 ms   ← this worker

Threading contract: identical to FrameSeekWorker — this object must be
moved to a QThread via ``moveToThread()`` before use.  All ``@pyqtSlot``
methods are called on that worker thread via Qt's queued-connection
mechanism.  ``frame_ready`` is emitted from the worker thread and
delivered to main-thread slots automatically.
"""
import av
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class PyAVSeekWorker(QObject):
    """
    Background worker that owns a dedicated ``av.InputContainer`` and
    performs frame-seek + decode on a ``QThread``.

    **Seek strategy**

    Uses ``container.seek(pts, backward=True, any_frame=False)`` to jump
    to the nearest I-frame at or before the target PTS, then iterates
    ``container.demux`` to decode forward until the target presentation
    timestamp is reached.  This is the same algorithm VLC and the ffmpeg
    CLI use.

    **"Latest wins" policy**

    If a new ``seek_to`` request arrives while a decode is in progress,
    the new frame number is stored in ``_latest_frame`` and the current
    decode is abandoned after it finishes.  ``_drain`` immediately picks
    up the latest request, keeping the effective queue depth at 1.
    """

    # Emitted from the worker thread; Qt queues delivery to main-thread slots.
    frame_ready = pyqtSignal(object, int)   # (BGR np.ndarray, frame_number)

    # PTS tolerance (in stream time-base units) to accommodate floating-point
    # rounding when converting frame_number <-> PTS.
    _PTS_TOLERANCE: int = 2

    def __init__(self) -> None:
        super().__init__()
        self._container: av.container.InputContainer | None = None
        self._stream: av.video.VideoStream | None = None
        self._fps: float = 0.0
        self._time_base: float = 0.0
        self._busy: bool = False
        self._latest_frame: int = -1     # -1 = no pending request

    # ------------------------------------------------------------------
    # Public slots — called from the main thread via queued connections
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def open_video(self, path: str) -> None:
        """
        Opens (or re-opens) the video at ``path`` using PyAV/libavformat.
        Must be called whenever the active video changes.

        Args:
            path (str): Absolute path to the video file.
        """
        self._close()
        try:
            container = av.open(path)
            stream = container.streams.video[0]
            fps = float(stream.average_rate)
            tb = float(stream.time_base)
            if fps <= 0 or tb <= 0:
                container.close()
                print(f"PyAVSeekWorker: invalid fps/time_base for '{path}'")
                return
            self._container = container
            self._stream = stream
            self._fps = fps
            self._time_base = tb
        except Exception as e:
            print(f"PyAVSeekWorker: failed to open '{path}': {e}")

    @pyqtSlot(int)
    def seek_to(self, frame_number: int) -> None:
        """
        Queues a seek request.  If a decode is already in progress,
        stores the request and returns immediately; ``_drain`` picks it
        up after the current decode completes.

        Args:
            frame_number (int): Zero-based frame index to decode.
        """
        self._latest_frame = frame_number
        if not self._busy:
            self._drain()

    @pyqtSlot()
    def release(self) -> None:
        """Releases the internal container.  Call before stopping the thread."""
        self._close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close(self) -> None:
        """Safely closes the PyAV container if open."""
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
            self._stream = None

    def _drain(self) -> None:
        """
        Processes pending seek requests in a tight loop, keeping only the
        latest result.  Intermediate frames are decoded but not emitted,
        preventing stale-frame backlogs during rapid slider movement.
        """
        self._busy = True
        while self._latest_frame >= 0:
            fn = self._latest_frame
            self._latest_frame = -1
            if self._container is not None and self._stream is not None:
                frame = self._decode_frame(fn)
                if frame is not None and self._latest_frame < 0:
                    self.frame_ready.emit(frame, fn)
        self._busy = False

    def _decode_frame(self, frame_number: int) -> np.ndarray | None:
        """
        Seeks to the nearest I-frame at or before ``frame_number``, then
        decodes forward until the target PTS is reached.

        Args:
            frame_number (int): Zero-based frame index to decode.

        Returns:
            np.ndarray | None: BGR frame array (H x W x 3), or None on error.
        """
        try:
            target_pts = int(frame_number / self._fps / self._time_base)
            self._container.seek(
                target_pts,
                stream=self._stream,
                backward=True,
                any_frame=False,
            )
            for packet in self._container.demux(self._stream):
                for av_frame in packet.decode():
                    if av_frame.pts is None:
                        continue
                    if av_frame.pts >= target_pts - self._PTS_TOLERANCE:
                        return av_frame.to_ndarray(format='bgr24')
            return None
        except Exception as e:
            print(f"PyAVSeekWorker: decode error at frame {frame_number}: {e}")
            return None
