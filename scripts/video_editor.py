# video_editor.py
import cv2, time, av
import numpy as np
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QTimer, QRectF, QThread, QObject, pyqtSignal
from scripts.interactive_crop_region import InteractiveCropRegion
from scripts.pyav_seek_worker import PyAVSeekWorker
from scripts.thumbnail_seek_worker import PyAVThumbnailWorker


class _SeekProxy(QObject):
    """
    Thin ``QObject`` that lives on the main thread and owns the signals used
    to send work to ``PyAVSeekWorker`` on the background thread.

    ``VideoEditor`` is not a ``QObject``, so it cannot define ``pyqtSignal``
    directly.  This proxy bridges that gap without changing ``VideoEditor``'s
    class hierarchy.
    """
    seek_requested = pyqtSignal(int)    # → PyAVSeekWorker.seek_to
    video_opened   = pyqtSignal(str)    # → PyAVSeekWorker.open_video
    worker_release = pyqtSignal()       # → PyAVSeekWorker.release


class _ThumbProxy(QObject):
    """
    Companion proxy for ``PyAVThumbnailWorker`` signals.
    Kept separate from ``_SeekProxy`` to preserve single-responsibility and
    allow independent thread lifecycle management.
    """
    # (path, original_width, original_height) → PyAVThumbnailWorker.open_video
    video_opened    = pyqtSignal(str, int, int)
    seek_requested  = pyqtSignal(int)   # → PyAVThumbnailWorker.seek_to
    worker_release  = pyqtSignal()      # → PyAVThumbnailWorker.release

class VideoEditor:
    def __init__(self, main_app):
        self.main_app = main_app
        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self._playback_step)
        self.is_playing_range = False
        self.current_range_end_frame = -1
        self.current_fps = 0.0
        # Viewport size cache — avoids redundant fitInView calls every frame.
        self._last_viewport_size: tuple[int, int] = (-1, -1)
        # Debounce timer for slider-hover thumbnail generation.
        # Reduced from 80 ms to 50 ms: the thumbnail worker is off-thread,
        # so the debounce is the dominant contributor to perceived latency.
        self._thumb_debounce_timer = QTimer()
        self._thumb_debounce_timer.setSingleShot(True)
        self._thumb_debounce_timer.setInterval(50)
        self._thumb_debounce_timer.timeout.connect(self._dispatch_thumbnail_seek)
        self._pending_thumb_frame_pos: int = 0
        self._pending_thumb_slider_pos = None
        # Scrub throttle: increased from 33 ms to 50 ms to reduce redundant
        # worker seeks during very fast slider drags.
        self._scrub_min_interval: float = 0.050
        self._last_scrub_time: float = 0.0

        # ------------------------------------------------------------------
        # Background seek worker — PyAVSeekWorker uses libavformat/libavcodec
        # (same as VLC) for ~56 ms avg frame-accurate seeking vs ~348 ms MSMF.
        # ------------------------------------------------------------------
        self._seek_proxy  = _SeekProxy()
        self._seek_worker = PyAVSeekWorker()
        self._seek_thread = QThread()
        self._seek_thread.setObjectName("PyAVSeekThread")

        self._seek_worker.moveToThread(self._seek_thread)

        # Cross-thread signal connections (all QueuedConnections)
        self._seek_proxy.seek_requested.connect(self._seek_worker.seek_to)
        self._seek_proxy.video_opened.connect(self._seek_worker.open_video)
        self._seek_proxy.worker_release.connect(self._seek_worker.release)

        # frame_ready delivered to main thread via queued connection
        self._seek_worker.frame_ready.connect(self._on_async_frame_ready)

        self._seek_thread.start()

        # Single-in-flight gate (same contract as before)
        self._latest_requested_frame: int = -1
        self._seek_in_flight: bool = False

        # ------------------------------------------------------------------
        # PyAV sequential-playback container (main-thread only).
        # Kept separate from the background seek worker so the worker thread
        # is never starved by playback I/O, and so sequential reads stay fast
        # (libavcodec just decodes the next compressed frame — no seeking).
        # ------------------------------------------------------------------
        self._video_path: str = ""              # last successfully opened path
        self._pyav_play_container = None        # av.InputContainer | None
        self._pyav_play_stream    = None        # av.VideoStream  | None
        self._pyav_play_iter      = None        # frame iterator  | None
        self._pyav_play_fps:   float = 0.0
        self._pyav_play_tb:    float = 0.0

        # ------------------------------------------------------------------
        # Thumbnail worker — PyAVThumbnailWorker uses keyframe-only seeking
        # (~5.7 ms avg) with a 16-entry LRU cache (~0 ms on cache hit).
        # Emits QImage (thread-safe); main thread converts to QPixmap.
        # ------------------------------------------------------------------
        self._thumb_proxy  = _ThumbProxy()
        self._thumb_worker = PyAVThumbnailWorker()
        self._thumb_thread = QThread()
        self._thumb_thread.setObjectName("PyAVThumbnailThread")

        self._thumb_worker.moveToThread(self._thumb_thread)

        self._thumb_proxy.video_opened.connect(self._thumb_worker.open_video)
        self._thumb_proxy.seek_requested.connect(self._thumb_worker.seek_to)
        self._thumb_proxy.worker_release.connect(self._thumb_worker.release)

        self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)

        self._thumb_thread.start()

    # ------------------------------------------------------------------ #
    #  Helper: open a VideoCapture trying hardware-accelerated backends   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _open_capture(video_path: str) -> cv2.VideoCapture | None:
        """
        Opens a ``cv2.VideoCapture`` for ``video_path`` using the fastest
        available backend on the current platform.

        Priority:
        1. ``CAP_MSMF`` (Windows Media Foundation) — uses the OS hardware
           H.264/H.265 decoder (Intel QSV, NVIDIA NVDEC, AMD VCE) and performs
           keyframe-approximate seeking, matching VLC's behaviour.
        2. ``CAP_FFMPEG`` — software decoder, slower seeking but universal.
        3. ``CAP_ANY`` — last-resort fallback.

        Args:
            video_path (str): Absolute path to the video file.

        Returns:
            cv2.VideoCapture | None: An opened capture, or None on failure.
        """
        for backend in (cv2.CAP_MSMF, cv2.CAP_FFMPEG, cv2.CAP_ANY):
            cap = cv2.VideoCapture(video_path, backend)
            if cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) > 0:
                return cap
            cap.release()
        return None

    def load_video_properties(self, video_path):
        """
        Opens the video, reads its properties, displays the first frame,
        and notifies both background workers (seek and thumbnail) to
        re-open this video on their respective threads.

        Args:
            video_path (str): Absolute path to the video file.

        Returns:
            bool: True if the video was opened and the first frame displayed.
        """
        try:
            # Release existing main cap and old PyAV playback container so the
            # next play action opens a fresh container for the new video file.
            if self.main_app.cap:
                self.main_app.cap.release()
            self._close_pyav_playback()

            cap = self._open_capture(video_path)
            if cap is None:
                print(f"Error: Could not open video file: {video_path}")
                self.main_app.cap = None
                self.current_fps = 0.0
                return False

            self.main_app.cap = cap
            self.main_app.frame_count  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.main_app.original_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.main_app.original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.current_fps = cap.get(cv2.CAP_PROP_FPS)
            if self.current_fps <= 0:
                print("Warning: Could not determine video FPS. Using fallback 30.")
                self.current_fps = 30.0

            if self.main_app.frame_count <= 0:
                print(f"Warning: Video has {self.main_app.frame_count} frames. Cannot process.")
                cap.release()
                self.main_app.cap = None
                self.current_fps = 0.0
                return False

            # Track the path so the playback container can be (re-)opened.
            self._video_path = video_path

            # Notify the background seek worker (PyAV frame-accurate)
            self._seek_proxy.video_opened.emit(video_path)

            # Notify the thumbnail worker (PyAV keyframe-only + LRU cache)
            self._thumb_proxy.video_opened.emit(
                video_path,
                self.main_app.original_width,
                self.main_app.original_height,
            )

            # Set slider range and enable
            self.main_app.slider.setMaximum(self.main_app.frame_count - 1)
            self.main_app.slider.setEnabled(True)
            self.main_app.slider.setValue(0)

            # Invalidate the viewport cache so fitInView is called at least once
            # for the first frame of this new video (aspect ratio may differ).
            self._last_viewport_size = (-1, -1)

            return self.update_frame_display(0)

        except Exception as e:
            print(f"Error loading video properties: {e}")
            if self.main_app.cap:
                self.main_app.cap.release()
            self.main_app.cap = None
            self.current_fps = 0.0
            return False

    def update_frame_display(self, frame_number):
        """
        Seeks the video capture to ``frame_number``, decodes the frame, and
        renders it to the graphics view.

        Args:
            frame_number (int): Zero-based frame index to display.

        Returns:
            bool: True if the frame was read and displayed successfully.
        """
        if not self.main_app.cap or not self.main_app.cap.isOpened():
             print("⚠️ Cannot update display: Video capture not ready.")
             return False

        # Clamp frame number to valid range
        frame_number = int(round(frame_number))
        frame_number = max(0, min(frame_number, self.main_app.frame_count - 1))

        try:
            # CAP_PROP_POS_FRAMES gives the *next* frame index to be decoded.
            # Only seek if we are not already positioned at the desired frame.
            current_pos = int(self.main_app.cap.get(cv2.CAP_PROP_POS_FRAMES))
            if current_pos != frame_number and current_pos != frame_number + 1:
                self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

            ret, frame = self.main_app.cap.read()
            if ret:
                self.display_frame(frame)

                # Block signals to prevent slider.valueChanged from triggering
                # scrub_video again and causing a redundant second frame decode.
                self.main_app.slider.blockSignals(True)
                self.main_app.slider.setValue(frame_number)
                self.main_app.slider.blockSignals(False)

                self.main_app.update_current_frame_label(
                    frame_number, self.main_app.frame_count, self.current_fps
                )
                return True
            else:
                print(f"Error: Could not read frame {frame_number}.")
                return False
        except Exception as e:
             print(f"Error updating frame display for frame {frame_number}: {e}")
             return False

    def display_frame(self, frame):
        """
        Renders a raw OpenCV BGR frame to the graphics view.

        Performance strategy:
        - The frame is pre-scaled to the current viewport dimensions using
          ``cv2.resize`` **before** being wrapped in a ``QImage``. This avoids
          allocating a full-resolution ``QPixmap`` and eliminates the costly
          CPU-side bicubic scaling that ``QPixmap.scaled()`` would perform.
        - ``fitInView`` and ``setSceneRect`` are called only when the viewport
          dimensions have actually changed (e.g. window resize), not on every
          frame. The last known viewport size is cached in
          ``self._last_viewport_size``.

        Args:
            frame (numpy.ndarray): BGR frame array from ``cv2.VideoCapture.read()``.
        """
        if frame is None:
             print("⚠️ display_frame called with None frame.")
             return
        try:
            vp = self.main_app.graphics_view.viewport()
            view_width  = max(1, vp.width()  - 2)
            view_height = max(1, vp.height() - 2)

            # --- Pre-scale in NumPy/OpenCV (SIMD-optimised, no full-res QPixmap) ---
            src_h, src_w = frame.shape[:2]
            # Compute letterbox dimensions preserving aspect ratio
            scale = min(view_width / src_w, view_height / src_h)
            dst_w = max(1, int(src_w * scale))
            dst_h = max(1, int(src_h * scale))

            # INTER_LINEAR is fast and gives good quality at display sizes
            resized = cv2.resize(frame, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)
            frame_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

            h, w, ch = frame_rgb.shape
            q_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            # QImage does NOT copy frame_rgb.data; keep a reference until setPixmap
            pixmap = QPixmap.fromImage(q_img)

            self.main_app.pixmap_item.setPixmap(pixmap)

            # fitInView is expensive (recomputes view transform + triggers layout).
            # Only call it when the viewport has actually been resized.
            current_vp_size = (view_width, view_height)
            if current_vp_size != self._last_viewport_size:
                self._last_viewport_size = current_vp_size
                self.main_app.graphics_view.fitInView(
                    self.main_app.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio
                )
                self.main_app.scene.setSceneRect(
                    self.main_app.pixmap_item.boundingRect()
                )
        except Exception as e:
            print(f"Error displaying frame: {e}")

    def scrub_video(self, position):
        """
        Called when the slider is dragged by the user (``sliderMoved`` signal).

        Posts an async seek request to ``PyAVSeekWorker`` so the main thread
        is never blocked.  A lightweight time-throttle prevents flooding the
        worker queue during very fast drags.

        Args:
            position (int): Current slider value (frame index).
        """
        if not self.main_app.cap:
            return
        if self.playback_timer.isActive():
            self.stop_playback()
        now = time.monotonic()
        if now - self._last_scrub_time < self._scrub_min_interval:
            return
        self._last_scrub_time = now
        self.request_seek(position)

    def _on_slider_released(self):
        """
        Slot connected to ``QSlider.sliderReleased``.

        Guarantees a seek is posted for the final slider position after any
        interaction — drag (possibly throttled) or groove click (which does not
        emit ``sliderMoved``).
        """
        if not self.main_app.cap:
            return
        self._last_scrub_time = 0.0
        self.request_seek(self.main_app.slider.value())

    def request_seek(self, frame_number: int) -> None:
        """
        Posts a non-blocking frame-seek request to ``PyAVSeekWorker``.

        Enforces a single-in-flight policy: if the worker is already decoding a
        frame, the new frame number is stored in ``_latest_requested_frame`` but
        no additional signal is sent.  When the in-flight decode completes,
        ``_on_async_frame_ready`` checks whether a newer request arrived and
        immediately posts it — so we always converge to the final position in at
        most one extra decode after the user stops interacting.

        Args:
            frame_number (int): Zero-based frame index to display.
        """
        if not self.main_app.cap:
            return
        self._latest_requested_frame = max(
            0, min(int(frame_number), self.main_app.frame_count - 1)
        )
        if not self._seek_in_flight:
            self._post_seek(self._latest_requested_frame)

    def _post_seek(self, frame_number: int) -> None:
        """
        Internal helper: marks a seek as in-flight and emits the cross-thread
        signal to the worker.  Must only be called when ``_seek_in_flight`` is
        False.

        Args:
            frame_number (int): Zero-based frame index to decode.
        """
        self._seek_in_flight = True
        self._seek_proxy.seek_requested.emit(frame_number)

    def _on_async_frame_ready(self, frame, frame_number: int) -> None:
        """
        Slot called on the main thread when ``PyAVSeekWorker`` finishes
        decoding a requested frame.

        After displaying the frame, clears ``_seek_in_flight`` and immediately
        posts one follow-up seek if ``_latest_requested_frame`` is different
        from the just-decoded frame (i.e., the user moved the slider while the
        worker was busy).  This guarantees convergence to the final position
        in exactly one additional decode, with no stale intermediate frames
        queued.

        The slider is only updated when the user is not mid-drag
        (``isSliderDown()`` is False) and the decoded frame is still the most
        recently requested one, preventing visual hop-back during a drag.

        Args:
            frame (numpy.ndarray): Decoded BGR frame from the worker.
            frame_number (int): Zero-based index of the decoded frame.
        """
        # Clear in-flight flag BEFORE potentially posting a follow-up
        self._seek_in_flight = False

        self.display_frame(frame)

        is_latest = (frame_number == self._latest_requested_frame)
        if is_latest and not self.main_app.slider.isSliderDown():
            self.main_app.slider.blockSignals(True)
            self.main_app.slider.setValue(frame_number)
            self.main_app.slider.blockSignals(False)

        self.main_app.update_current_frame_label(
            frame_number, self.main_app.frame_count, self.current_fps
        )

        # If the user moved the slider while the worker was busy, post exactly
        # one more seek for the latest position.  No backlog ever builds up.
        if not is_latest and self.main_app.cap:
            self._post_seek(self._latest_requested_frame)

    def cleanup(self) -> None:
        """
        Stops both background worker threads gracefully.  Must be called
        before the application exits (e.g. from ``VideoCropper.closeEvent``)
        to avoid QThread destruction warnings.
        """
        # Seek worker
        self._seek_proxy.worker_release.emit()
        self._seek_thread.quit()
        self._seek_thread.wait(2000)

        # Thumbnail worker
        self._thumb_proxy.worker_release.emit()
        self._thumb_thread.quit()
        self._thumb_thread.wait(2000)

        # PyAV playback container
        self._close_pyav_playback()

    def show_thumbnail(self, event):
        """
        Queues a hover-thumbnail render for the slider position under the mouse.

        All data is extracted from ``event`` synchronously before this handler
        returns and Qt frees the event object.  The actual decode is dispatched
        to ``PyAVThumbnailWorker`` (background thread) after a 50 ms debounce,
        achieving ~5.7 ms seek + decode vs 400+ ms with the old on-thread path.

        Args:
            event (QMouseEvent): Hover-move event from the slider event filter.
        """
        if self.playback_timer.isActive():
            return
        if not self.main_app.cap or not self.main_app.cap.isOpened():
            return

        slider_width = self.main_app.slider.width()
        if slider_width <= 0:
            return
        pos = event.position().toPoint()
        frame_pos = int((pos.x() / slider_width) * self.main_app.frame_count)
        self._pending_thumb_frame_pos = max(
            0, min(frame_pos, self.main_app.frame_count - 1)
        )
        self._pending_thumb_slider_pos = self.main_app.slider.mapToGlobal(pos)

        # (Re)start the 50 ms debounce timer.
        self._thumb_debounce_timer.start()

    def _dispatch_thumbnail_seek(self) -> None:
        """
        Called by the 50 ms debounce timer after the last mouse-move event.
        Emits a cross-thread signal to ``PyAVThumbnailWorker`` to decode and
        return the thumbnail for the pending frame position.
        """
        if self._pending_thumb_slider_pos is None:
            return
        if self.playback_timer.isActive():
            return
        self._thumb_proxy.seek_requested.emit(self._pending_thumb_frame_pos)

    def _on_thumbnail_ready(self, q_img, frame_number: int) -> None:
        """
        Slot called on the main thread when ``PyAVThumbnailWorker`` has
        finished decoding a thumbnail.

        Converts the ``QImage`` (thread-safe, emitted from worker) to a
        ``QPixmap`` (GUI-thread only) and positions the thumbnail label
        above the slider at the hovered position.

        Args:
            q_img: ``QImage`` of the pre-scaled thumbnail from the worker.
            frame_number (int): Frame number that was originally requested.
        """
        if self._pending_thumb_slider_pos is None:
            return
        try:
            pixmap = QPixmap.fromImage(q_img)
            thumb_w = pixmap.width()
            thumb_h = pixmap.height()

            self.main_app.thumbnail_label.setFixedSize(thumb_w, thumb_h)
            self.main_app.thumbnail_image_label.setGeometry(0, 0, thumb_w, thumb_h)
            self.main_app.thumbnail_image_label.setPixmap(pixmap)

            slider_global_pos = self._pending_thumb_slider_pos
            tooltip_x = slider_global_pos.x() - thumb_w // 2
            tooltip_y = slider_global_pos.y() - thumb_h - 10
            self.main_app.thumbnail_label.move(tooltip_x, tooltip_y)
            self.main_app.thumbnail_label.show()
        except Exception as e:
            print(f"Error displaying thumbnail: {e}")
            self.main_app.thumbnail_label.hide()


    def toggle_loop_playback(self):
        """
        Legacy stub — looping is now controlled by the loop toggle button
        (VideoCropper.toggle_loop).  This method is kept for compatibility
        but performs no action.
        """
        pass

    # ------------------------------------------------------------------ #
    #  PyAV sequential-playback helpers (main-thread, no QThread needed)  #
    # ------------------------------------------------------------------ #

    def _close_pyav_playback(self) -> None:
        """Releases the dedicated PyAV playback container if open."""
        if self._pyav_play_container is not None:
            try:
                self._pyav_play_container.close()
            except Exception:
                pass
            self._pyav_play_container = None
            self._pyav_play_stream    = None
            self._pyav_play_iter      = None

    def _open_pyav_playback(self) -> bool:
        """
        Opens (or re-opens) a dedicated ``av.InputContainer`` for sequential
        playback using the current ``_video_path``.

        Returns:
            bool: True if the container was opened successfully.
        """
        self._close_pyav_playback()
        if not self._video_path:
            return False
        try:
            container = av.open(self._video_path)
            stream = container.streams.video[0]
            fps = float(stream.average_rate)
            tb  = float(stream.time_base)
            if fps <= 0 or tb <= 0:
                container.close()
                print("VideoEditor._open_pyav_playback: invalid fps/time_base.")
                return False
            self._pyav_play_container = container
            self._pyav_play_stream    = stream
            self._pyav_play_fps       = fps
            self._pyav_play_tb        = tb
            return True
        except Exception as e:
            print(f"VideoEditor._open_pyav_playback: failed to open '{self._video_path}': {e}")
            return False

    def _seek_pyav_playback(self, frame_number: int) -> bool:
        """
        Seeks the playback container to the nearest I-frame at or before
        ``frame_number`` and resets the sequential frame iterator.

        Uses ``container.seek()`` with ``backward=True`` — same strategy as
        ``PyAVSeekWorker`` (~56 ms avg vs ~640 ms for MSMF).

        Args:
            frame_number (int): Zero-based target frame index.

        Returns:
            bool: True if the seek succeeded and the iterator was reset.
        """
        if self._pyav_play_container is None:
            return False
        try:
            target_pts = int(frame_number / self._pyav_play_fps / self._pyav_play_tb)
            self._pyav_play_container.seek(
                target_pts,
                stream=self._pyav_play_stream,
                backward=True,
                any_frame=False,
            )
            self._pyav_play_iter = self._pyav_play_container.decode(self._pyav_play_stream)
            return True
        except Exception as e:
            print(f"VideoEditor._seek_pyav_playback: seek error at frame {frame_number}: {e}")
            return False

    def toggle_play_forward(self):
        """Toggles normal playback from the current slider position."""
        if self.is_playing_range:  # Stop range playback before starting normal playback
            self.stop_playback()

        self.main_app.is_playing = not self.main_app.is_playing
        if self.main_app.is_playing:
            print("Starting normal playback...")
            self._start_playback()
        else:
            print("Stopping normal playback...")
            self.stop_playback()
            
    def toggle_range_playback(self, start_frame, end_frame):
        """Starts or stops playback limited to the given start/end frames."""
        if self.is_playing_range:  # Already playing this range — stop it
            print("Stopping range playback...")
            self.stop_playback()
        else:
            if self.main_app.is_playing:  # Stop normal playback before starting range playback
                print("Stopping normal playback before starting range playback...")
                self.stop_playback()
            self._start_playback(range_playback=True, start_frame=start_frame, end_frame=end_frame)

    def _start_playback(self, range_playback=False, start_frame=None, end_frame=None):
        """
        Begins the playback timer using a dedicated PyAV sequential-read
        container so the main thread is never blocked by MSMF seeking.

        Strategy:
        - Open (or reuse) a PyAV container for the current video.
        - Seek to ``start_frame`` via PyAV (avg ~56 ms vs ~640 ms for MSMF).
        - Iterate frames sequentially in ``_playback_step`` — no seeking needed
          between frames, so each step is just one H.264/HEVC frame decode.

        Args:
            range_playback (bool): If True, confine playback to [start_frame, end_frame).
            start_frame (int | None): First frame for range playback.
            end_frame (int | None): Exclusive last frame for range playback.

        Looping behaviour (for both modes) is controlled by
        ``self.main_app.loop_enabled`` — a passive flag set by the UI toggle
        button.  ``_playback_step`` checks this flag at the end of each mode.
        """
        if not self.main_app.cap or not self.main_app.cap.isOpened():
            print("Cannot start playback: Video not ready.")
            self.main_app.is_playing = False
            self.is_playing_range = False
            return

        self.main_app.is_playing = not range_playback
        self.is_playing_range = range_playback

        # Determine start/end frame boundaries
        self.current_playback_start_frame = 0
        self.current_playback_end_frame = self.main_app.frame_count  # Default: full video
        playback_mode_msg = "normal"

        if range_playback:
            playback_mode_msg = "range"
            if start_frame is not None and end_frame is not None and start_frame < end_frame:
                self.current_playback_start_frame = start_frame
                self.current_playback_end_frame = end_frame
                self.current_range_end_frame = end_frame
            else:
                print(f"Cannot start range playback: Invalid start/end frames ({start_frame}, {end_frame})")
                self.stop_playback()
                return
        else:  # Normal playback — start from current slider position
            self.current_playback_start_frame = self.main_app.slider.value()

        loop_hint = " [looping]" if self.main_app.loop_enabled else ""
        print(f"Starting {playback_mode_msg}{loop_hint} playback from "
              f"{self.current_playback_start_frame} to {self.current_playback_end_frame}")

        # ── Open PyAV playback container (if not already open for this video) ──
        if self._pyav_play_container is None:
            if not self._open_pyav_playback():
                print("Cannot start playback: failed to open PyAV playback container.")
                self.stop_playback()
                return

        # ── Seek PyAV container to start frame (~56 ms, no UI freeze) ──────────
        if not self._seek_pyav_playback(self.current_playback_start_frame):
            print(f"Cannot start playback: PyAV seek to frame "
                  f"{self.current_playback_start_frame} failed.")
            self.stop_playback()
            return

        # ── Start timer at the correct speed ────────────────────────────────────
        speed = self.main_app.playback_speed_spinner.value()
        interval = max(1, int((1000 / self.current_fps) / speed)) if self.current_fps > 0 \
            else max(1, int(33 / speed))
        self.playback_timer.start(interval)

    def _playback_step(self):
        """
        Reads and displays the next frame during playback.

        Frame data comes from the dedicated PyAV sequential-read container
        (``_pyav_play_iter``).  Sequential PyAV decoding is fast because there
        is no seeking — libavcodec just decompresses the next packet in the
        bitstream.  The slider and frame label are updated after each frame.
        """
        is_active = self.main_app.is_playing or self.is_playing_range
        if not self._pyav_play_iter or not is_active:
            self.stop_playback()
            return

        try:
            av_frame = next(self._pyav_play_iter)
        except StopIteration:
            # End of stream
            if (self.main_app.is_playing and self.main_app.loop_enabled) or \
               (self.is_playing_range and self.main_app.loop_enabled):
                start = self.current_playback_start_frame
                if not self._seek_pyav_playback(start):
                    self.stop_playback()
                    return
                try:
                    av_frame = next(self._pyav_play_iter)
                except StopIteration:
                    self.stop_playback()
                    return
            else:
                self.stop_playback()
                return
        except Exception as e:
            print(f"Playback error: {e}")
            self.stop_playback()
            return

        # Convert PyAV frame → BGR ndarray → display
        frame_bgr = av_frame.to_ndarray(format='bgr24')

        # Derive the zero-based frame number from the frame's PTS
        if av_frame.pts is not None and self._pyav_play_tb > 0 and self._pyav_play_fps > 0:
            actual_read_frame = int(av_frame.pts * self._pyav_play_tb * self._pyav_play_fps)
            actual_read_frame = max(0, min(actual_read_frame, self.main_app.frame_count - 1))
        else:
            actual_read_frame = self.main_app.slider.value()

        # --- End-of-range check for range playback ---
        if self.is_playing_range and actual_read_frame >= self.current_range_end_frame:
            if self.main_app.loop_enabled:
                if not self._seek_pyav_playback(self.current_playback_start_frame):
                    self.stop_playback()
                    return
            else:
                self.stop_playback()
                return

        self.display_frame(frame_bgr)

        # Update slider (block signals to avoid re-triggering scrub)
        self.main_app.slider.blockSignals(True)
        self.main_app.slider.setValue(actual_read_frame)
        self.main_app.slider.blockSignals(False)

        self.main_app.update_current_frame_label(
            actual_read_frame, self.main_app.frame_count, self.current_fps
        )

    def stop_playback(self):
        """Stops any active playback timer and resets transient playback flags.

        Note: ``loop_enabled`` is intentionally NOT reset here because it is a
        persistent user preference controlled by the loop toggle button.
        The PyAV playback container is kept open so that restarting playback
        on the same video skips the ``av.open()`` overhead.
        """
        was_active = self.playback_timer.isActive()
        if was_active:
            self.playback_timer.stop()
            print("Playback timer stopped.")

        # Reset transient flags only
        self.main_app.is_playing = False
        self.is_playing_range = False
        self.current_range_end_frame = -1
        # Keep _pyav_play_container alive for quick restart

    def next_clip(self):
        """
        Advances the video list selection to the next item.
        Setting the current row triggers VideoCropper._on_video_selection_changed.
        """
        current_row = self.main_app.video_list.currentRow()
        if current_row < self.main_app.video_list.count() - 1:
             self.main_app.video_list.setCurrentRow(current_row + 1)
        else:
             print("Already at the last video.")

    def navigate_clip(self, direction):
        """
        Navigates the video list in the specified direction (-1: prev, 1: next).
        """
        if direction < 0: # Previous video
             current_row = self.main_app.video_list.currentRow()
             if current_row > 0:
                 self.main_app.video_list.setCurrentRow(current_row - 1)
             else:
                 print("Already at the first video.")
        else: # Next video
             self.next_clip()

    # --- NEW Frame Navigation Methods ---

    def step_frame(self, delta):
        """
        Steps forward or backward by ``delta`` frames.

        Routing: all steps are dispatched asynchronously to ``PyAVSeekWorker``
        via ``request_seek``.  This eliminates the ~350 ms MSMF seek block
        that occurred when this called ``update_frame_display`` directly.

        Args:
            delta (int): Number of frames to advance (negative = backward).
        """
        if not self.main_app.cap or not self.main_app.slider.isEnabled():
            return
        if self.playback_timer.isActive():
            self.stop_playback()
        target_frame = self.main_app.slider.value() + delta
        self.request_seek(target_frame)

    def jump_frames(self, delta_seconds):
        """
        Jumps forward or backward by ``delta_seconds`` seconds.

        Routing: dispatched asynchronously to ``PyAVSeekWorker`` via
        ``request_seek`` to avoid blocking the UI thread.

        Args:
            delta_seconds (float): Seconds to advance (negative = backward).
        """
        if not self.main_app.cap or not self.main_app.slider.isEnabled() or self.current_fps <= 0:
            return
        if self.playback_timer.isActive():
            self.stop_playback()
        frame_delta = int(round(delta_seconds * self.current_fps))
        if frame_delta == 0:
            frame_delta = 1 if delta_seconds > 0 else -1
        target_frame = self.main_app.slider.value() + frame_delta
        self.request_seek(target_frame)

    def goto_frame(self, frame_number):
        """
        Jumps directly to ``frame_number``.

        Routing: dispatched asynchronously to ``PyAVSeekWorker`` via
        ``request_seek`` to avoid blocking the UI thread.

        Args:
            frame_number (int): Zero-based target frame index.
        """
        if not self.main_app.cap or not self.main_app.slider.isEnabled():
            return
        if self.playback_timer.isActive():
            self.stop_playback()
        self.request_seek(frame_number)
