# video_editor.py
import cv2, time
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QTimer, QRectF, QThread, QObject, pyqtSignal
from scripts.interactive_crop_region import InteractiveCropRegion  # New interactive crop region
from scripts.frame_seek_worker import FrameSeekWorker


class _SeekProxy(QObject):
    """
    Thin ``QObject`` that lives on the main thread and owns the signals used
    to send work to ``FrameSeekWorker`` on the background thread.

    ``VideoEditor`` is not a ``QObject``, so it cannot define ``pyqtSignal``
    directly.  This proxy bridges that gap without changing ``VideoEditor``'s
    class hierarchy.
    """
    seek_requested  = pyqtSignal(int)   # → FrameSeekWorker.seek_to
    video_opened    = pyqtSignal(str)   # → FrameSeekWorker.open_video
    worker_release  = pyqtSignal()      # → FrameSeekWorker.release

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
        self._thumb_debounce_timer = QTimer()
        self._thumb_debounce_timer.setSingleShot(True)
        self._thumb_debounce_timer.setInterval(80)
        self._thumb_debounce_timer.timeout.connect(self._render_thumbnail)
        self._pending_thumb_frame_pos: int = 0
        self._pending_thumb_slider_pos = None
        # Scrub throttle (kept for compatibility; less critical now that seeks
        # are async, but still useful to avoid over-flooding the worker queue).
        self._scrub_min_interval: float = 0.033
        self._last_scrub_time: float = 0.0
        # Dedicated VideoCapture for thumbnail rendering.
        self._thumb_cap = None

        # ------------------------------------------------------------------
        # Background seek worker — owns its own VideoCapture and processes
        # frame-decode requests without blocking the main UI thread.
        # ------------------------------------------------------------------
        self._seek_proxy  = _SeekProxy()
        self._seek_worker = FrameSeekWorker()
        self._seek_thread = QThread()
        self._seek_thread.setObjectName("FrameSeekThread")

        # Move the worker to the background thread
        self._seek_worker.moveToThread(self._seek_thread)

        # Cross-thread signal connections (all become QueuedConnections)
        self._seek_proxy.seek_requested.connect(self._seek_worker.seek_to)
        self._seek_proxy.video_opened.connect(self._seek_worker.open_video)
        self._seek_proxy.worker_release.connect(self._seek_worker.release)

        # Worker → main thread: frame_ready is delivered on the main thread
        # because the connection was established from the main thread.
        self._seek_worker.frame_ready.connect(self._on_async_frame_ready)

        self._seek_thread.start()

        # Single-in-flight gate: at most ONE seek request is ever queued in the
        # worker at a time.  When a new request arrives while the worker is busy,
        # _latest_requested_frame is updated but no new signal is posted.
        # _on_async_frame_ready posts a single follow-up seek if the latest frame
        # has changed since the completed seek, converging in exactly one extra
        # decode after the user stops interacting.
        self._latest_requested_frame: int = -1
        self._seek_in_flight: bool = False

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
        and initialises a dedicated thumbnail capture.

        Uses the fastest available backend (MSMF → FFMPEG → CAP_ANY).

        Args:
            video_path (str): Absolute path to the video file.

        Returns:
            bool: True if the video was opened and the first frame displayed.
        """
        try:
            # Release existing captures
            if self.main_app.cap:
                self.main_app.cap.release()
            if self._thumb_cap:
                self._thumb_cap.release()
                self._thumb_cap = None

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

            # Open a dedicated capture for thumbnails so hover seeks never
            # disturb the main cap’s decode position.
            self._thumb_cap = self._open_capture(video_path)

            # Notify the background seek worker to re-open this video
            # (uses a queued signal so the worker thread handles it safely).
            self._seek_proxy.video_opened.emit(video_path)

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
            if self._thumb_cap:
                self._thumb_cap.release()
                self._thumb_cap = None
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

        Posts an async seek request to ``FrameSeekWorker`` so the main thread
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
        Posts a non-blocking frame-seek request to ``FrameSeekWorker``.

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
        Slot called on the main thread when ``FrameSeekWorker`` finishes
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
        Stops the background seek thread gracefully.  Must be called before the
        application exits (e.g. from ``VideoCropper.closeEvent``) to avoid
        QThread destruction warnings.
        """
        self._seek_proxy.worker_release.emit()
        self._seek_thread.quit()
        self._seek_thread.wait(2000)   # wait up to 2 s for clean shutdown

    def show_thumbnail(self, event):
        """
        Queues a hover-thumbnail render for the slider position under the mouse.

        Seeking on compressed video (H.264/HEVC) can take 30–300 ms per seek.
        To avoid hitches, the actual frame decode is debounced: ``_render_thumbnail``
        is called only once the mouse has been idle for 80 ms.

        **Important:** All data extracted from ``event`` is stored as plain Python
        values (int, QPoint) immediately.  The ``QMouseEvent`` object itself is
        **never** stored, because Qt destroys event objects after the handler
        returns, which would cause a silent C-level segfault if accessed later.

        Args:
            event (QMouseEvent): Hover-move event from the slider event filter.
        """
        # Skip entirely during active playback — seeking for a thumbnail would
        # disturb the decoder position that the playback timer depends on.
        if self.playback_timer.isActive():
            return
        if not self.main_app.cap or not self.main_app.cap.isOpened():
            return

        # Extract all required data from the event *synchronously* before
        # this handler returns and Qt frees the event object.
        slider_width = self.main_app.slider.width()
        if slider_width <= 0:
            return
        pos = event.position().toPoint()  # local coords within slider widget
        frame_pos = int((pos.x() / slider_width) * self.main_app.frame_count)
        self._pending_thumb_frame_pos = max(
            0, min(frame_pos, self.main_app.frame_count - 1)
        )
        # mapToGlobal must also be called now while the slider widget is valid
        self._pending_thumb_slider_pos = self.main_app.slider.mapToGlobal(pos)

        # (Re)start the debounce timer; the actual decode happens in _render_thumbnail.
        self._thumb_debounce_timer.start()

    def _render_thumbnail(self):
        """
        Decodes and displays the hover-thumbnail for the queued frame position.
        Called by the debounce timer 80 ms after the last mouse-move event.

        Uses the dedicated ``_thumb_cap`` so the main cap’s decode position is
        never disturbed.  No restore-seek is needed after reading the thumbnail
        frame, halving the seek overhead compared to using the main cap.
        """
        if self._pending_thumb_slider_pos is None:
            return
        thumb_cap = self._thumb_cap
        if thumb_cap is None or not thumb_cap.isOpened():
            return
        # Don’t seek during live playback — the thumb cap is shared with nothing,
        # but a slow seek would still block the UI thread.
        if self.playback_timer.isActive():
            return
        try:
            frame_pos       = self._pending_thumb_frame_pos
            slider_global_pos = self._pending_thumb_slider_pos

            thumb_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = thumb_cap.read()
            # No position restoration needed — thumbnail has its own capture.

            if not ret or frame is None:
                self.main_app.thumbnail_label.hide()
                return

            thumbnail_height = 90
            src_aspect = (
                self.main_app.original_width / self.main_app.original_height
                if self.main_app.original_height > 0 else 16 / 9
            )
            thumbnail_width = max(1, int(thumbnail_height * src_aspect))

            thumb     = cv2.resize(frame, (thumbnail_width, thumbnail_height),
                                   interpolation=cv2.INTER_LINEAR)
            thumb_rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
            h, w, ch  = thumb_rgb.shape
            q_img  = QImage(thumb_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)

            self.main_app.thumbnail_label.setFixedSize(thumbnail_width, thumbnail_height)
            self.main_app.thumbnail_image_label.setGeometry(0, 0, thumbnail_width, thumbnail_height)
            self.main_app.thumbnail_image_label.setPixmap(pixmap)

            tooltip_x = slider_global_pos.x() - thumbnail_width  // 2
            tooltip_y = slider_global_pos.y() - thumbnail_height - 10
            self.main_app.thumbnail_label.move(tooltip_x, tooltip_y)
            self.main_app.thumbnail_label.show()
        except Exception as e:
            print(f"Error rendering thumbnail: {e}")
            self.main_app.thumbnail_label.hide()

    def toggle_loop_playback(self):
        """
        Legacy stub — looping is now controlled by the loop toggle button
        (VideoCropper.toggle_loop).  This method is kept for compatibility
        but performs no action.
        """
        pass

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
        Begins the playback timer.

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
                self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                self.main_app.slider.setValue(start_frame)
            else:
                print(f"Cannot start range playback: Invalid start/end frames ({start_frame}, {end_frame})")
                self.stop_playback()
                return
        else:  # Normal playback — start from current slider position
            self.current_playback_start_frame = self.main_app.slider.value()

        loop_hint = " [looping]" if self.main_app.loop_enabled else ""
        print(f"Starting {playback_mode_msg}{loop_hint} playback from {self.current_playback_start_frame} to {self.current_playback_end_frame}")

        if not self.update_frame_display(self.current_playback_start_frame):
            print(f"Error seeking to start frame {self.current_playback_start_frame}. Aborting playback.")
            self.stop_playback()
            return

        speed = self.main_app.playback_speed_spinner.value()
        interval = int((1000 / self.current_fps) / speed) if self.current_fps > 0 else int(33 / speed)
        self.playback_timer.start(interval)

    def _playback_step(self):
        """Reads and displays the next frame during playback."""
        is_active = self.main_app.is_playing or self.is_playing_range
        if not self.main_app.cap or not self.main_app.cap.isOpened() or not is_active:
            self.stop_playback()
            return

        # Position *before* reading the next frame (cv2 POS_FRAMES = next-to-read index)
        current_frame_pos = int(self.main_app.cap.get(cv2.CAP_PROP_POS_FRAMES))

        # --- End-of-stream checks ---
        if self.is_playing_range and current_frame_pos >= self.current_range_end_frame:
            if self.main_app.loop_enabled:
                # Loop: seek back to range start and continue
                self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_playback_start_frame)
                current_frame_pos = self.current_playback_start_frame
            else:
                self.stop_playback()
                self.update_frame_display(self.current_playback_start_frame)
                return

        elif self.main_app.is_playing and current_frame_pos >= self.current_playback_end_frame:
            if self.main_app.loop_enabled:
                # Loop: seek back to the very first frame of the video
                self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                current_frame_pos = 0
            else:
                self.stop_playback()
                return

        # --- Read and Display Frame ---
        ret, frame = self.main_app.cap.read()
        if ret and frame is not None:
            # Calculate the frame index that was just *read*
            actual_read_frame = current_frame_pos # Since POS_FRAMES is next index before read
            if actual_read_frame >= self.main_app.frame_count: # Handle potential off-by-one at end
                actual_read_frame = self.main_app.frame_count - 1

            # Display frame first
            self.display_frame(frame)

            # Update slider (block signals)
            self.main_app.slider.blockSignals(True)
            self.main_app.slider.setValue(actual_read_frame)
            self.main_app.slider.blockSignals(False)

            # Update label
            self.main_app.update_current_frame_label(actual_read_frame, self.main_app.frame_count, self.current_fps)

        else:
            print("End of stream or read error during playback.")
            self.stop_playback()
            # Update label to show the last successfully read frame?
            last_known_frame = current_frame_pos -1 if current_frame_pos > 0 else 0
            last_known_frame = max(0, min(last_known_frame, self.main_app.frame_count - 1))
            self.main_app.update_current_frame_label(last_known_frame, self.main_app.frame_count, self.current_fps)

    def stop_playback(self):
        """Stops any active playback timer and resets transient playback flags.

        Note: ``loop_enabled`` is intentionally NOT reset here because it is a
        persistent user preference controlled by the loop toggle button.
        """
        was_active = self.playback_timer.isActive()
        if was_active:
            self.playback_timer.stop()
            print("Playback timer stopped.")

        # Reset transient flags only
        self.main_app.is_playing = False
        self.is_playing_range = False
        self.current_range_end_frame = -1

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
        """Steps forward or backward by a specific number of frames (delta)."""
        if not self.main_app.cap or not self.main_app.slider.isEnabled():
            return
        if self.playback_timer.isActive(): # Stop playback if active
            self.stop_playback()

        current_frame = self.main_app.slider.value()
        target_frame = current_frame + delta
        # Clamping happens inside update_frame_display
        self.update_frame_display(target_frame)

    def jump_frames(self, delta_seconds):
        """Jumps forward or backward by a number of seconds."""
        if not self.main_app.cap or not self.main_app.slider.isEnabled() or self.current_fps <= 0:
            return
        if self.playback_timer.isActive(): # Stop playback if active
            self.stop_playback()

        frame_delta = int(round(delta_seconds * self.current_fps))
        if frame_delta == 0: # If jump is less than one frame, step at least one
             frame_delta = 1 if delta_seconds > 0 else -1

        current_frame = self.main_app.slider.value()
        target_frame = current_frame + frame_delta
        # Clamping happens inside update_frame_display
        self.update_frame_display(target_frame)

    def goto_frame(self, frame_number):
        """Jumps directly to a specific frame number."""
        if not self.main_app.cap or not self.main_app.slider.isEnabled():
            return
        if self.playback_timer.isActive(): # Stop playback if active
            self.stop_playback()

        # Clamping happens inside update_frame_display
        self.update_frame_display(frame_number)
