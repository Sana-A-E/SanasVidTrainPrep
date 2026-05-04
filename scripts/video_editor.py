# video_editor.py
import cv2, time
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QTimer, QRectF
from scripts.interactive_crop_region import InteractiveCropRegion  # New interactive crop region

class VideoEditor:
    def __init__(self, main_app):
        self.main_app = main_app
        self.playback_timer = QTimer() # Use a persistent timer
        self.playback_timer.timeout.connect(self._playback_step)
        # Add state flag for range playback
        self.is_playing_range = False
        self.current_range_end_frame = -1 # Store end frame for range playback
        # FPS cache to avoid repeated cap.get calls
        self.current_fps = 0.0
        # Viewport size cache — avoids redundant fitInView calls every frame.
        # Stores the last (width, height) at which fitInView was computed.
        self._last_viewport_size: tuple[int, int] = (-1, -1)
        # Debounce timer for slider-hover thumbnail generation.
        # Fires 80 ms after the mouse stops moving to avoid decoding frames on
        # every tiny mouse movement, which causes seek hitches on H.264/HEVC.
        self._thumb_debounce_timer = QTimer()
        self._thumb_debounce_timer.setSingleShot(True)
        self._thumb_debounce_timer.setInterval(80)
        # Connected once here; show_thumbnail only (re)starts the timer.
        self._thumb_debounce_timer.timeout.connect(self._render_thumbnail)
        # Pending thumbnail data — populated synchronously from the hover event
        # so we never hold a reference to a temporary Qt event object past the
        # lifetime of the event handler (which would cause a silent segfault).
        self._pending_thumb_frame_pos: int = 0    # target frame index
        self._pending_thumb_slider_pos = None     # QPoint for tooltip placement

    def load_video_properties(self, video_path):
        """Opens video, gets properties, displays first frame. Returns True on success."""
        try:
            if self.main_app.cap:
                 self.main_app.cap.release()
            self.main_app.cap = cv2.VideoCapture(video_path)
            if not self.main_app.cap.isOpened():
                print(f"Error: Could not open video file: {video_path}")
                self.main_app.cap = None
                self.current_fps = 0.0 # Reset FPS cache
                return False
                
            self.main_app.frame_count = int(self.main_app.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.main_app.original_width = int(self.main_app.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.main_app.original_height = int(self.main_app.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.current_fps = self.main_app.cap.get(cv2.CAP_PROP_FPS) # Cache FPS
            if self.current_fps <= 0:
                print("Warning: Could not determine video FPS. Using fallback 30.")
                self.current_fps = 30.0 # Fallback FPS
            
            if self.main_app.frame_count <= 0:
                 print(f"Warning: Video has {self.main_app.frame_count} frames. Cannot process.")
                 self.main_app.cap.release()
                 self.main_app.cap = None
                 self.current_fps = 0.0
                 return False
                 
            # Set slider range and enable
            self.main_app.slider.setMaximum(self.main_app.frame_count - 1)
            self.main_app.slider.setEnabled(True)
            self.main_app.slider.setValue(0) # Start slider at 0

            # Invalidate the viewport cache so fitInView is called at least once
            # for the first frame of this new video (aspect ratio may differ from
            # the previous video, so the scene rect must be re-established).
            self._last_viewport_size = (-1, -1)

            # Display the first frame (this now updates the label too)
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
        """Called when slider is moved interactively OR value changes."""
        if self.main_app.cap:
            # Stop any playback when scrubbing starts
            if self.playback_timer.isActive():
                self.stop_playback()
            # Update the frame display based on slider position
            self.update_frame_display(position)

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
        Uses ``_pending_thumb_frame_pos`` and ``_pending_thumb_slider_pos``
        populated synchronously by ``show_thumbnail``.
        """
        if self._pending_thumb_slider_pos is None:
            return
        if not self.main_app.cap or not self.main_app.cap.isOpened():
            return
        # Double-check: don't seek during live playback
        if self.playback_timer.isActive():
            return
        try:
            frame_pos = self._pending_thumb_frame_pos
            slider_global_pos = self._pending_thumb_slider_pos

            # Save the current decode position so we can restore it after the
            # thumbnail seek without disturbing normal scrub/navigation state.
            saved_cap_pos = int(self.main_app.cap.get(cv2.CAP_PROP_POS_FRAMES))

            self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = self.main_app.cap.read()

            # Restore the previous position immediately.
            self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, saved_cap_pos)

            if not ret or frame is None:
                self.main_app.thumbnail_label.hide()
                return

            thumbnail_width  = 160
            thumbnail_height = 90

            # Pre-scale in OpenCV to avoid a full-resolution QPixmap
            thumb     = cv2.resize(frame, (thumbnail_width, thumbnail_height),
                                   interpolation=cv2.INTER_LINEAR)
            thumb_rgb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
            h, w, ch  = thumb_rgb.shape
            # QPixmap.fromImage copies the buffer, so thumb_rgb lifetime is fine
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
                print("Range playback looping back to start frame...")
            else:
                print("Range playback finished.")
                self.stop_playback()
                self.update_frame_display(self.current_playback_start_frame)
                return

        elif self.main_app.is_playing and current_frame_pos >= self.current_playback_end_frame:
            if self.main_app.loop_enabled:
                # Loop: seek back to the very first frame of the video
                self.main_app.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                current_frame_pos = 0
                print("Normal playback looping back to frame 0...")
            else:
                print("Normal playback finished.")
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
