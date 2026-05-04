# Changelog

## [2026-04-16]
### Added Features
- Made the "**Start Frame**" text box editable, updating the current clip range when editing is finished. You can now manually edit start of your range and even create overlapping ranges.
- Added "**End Frame**" text box next to "Start Frame" text box for range selection to enable you to set your clip range based on a specific end frame instead of just duration.
- **Range logic synchronization**: start frame, end frame, and duration are now linked and recalculate based on the most recently modified property. When recalculation is triggered, the most recently modified properties are preserved while the oldest one is synced to the other two.
- Support for keyboard shortcut `Y` for "Preview Range" alongside existing `Z` key (to accommodate QWERTZ keyboards).
- Implemented global keyboard shortcuts for "**Preview Range**" (Z/Y) to ensure they work regardless of widget focus.
- Frame navigation sub-controls added: "**Start Frame**", "**End Frame**" jump buttons to quickly navigate to the start and end frames of the current clip range.
- **Range boundary update controls added**: "Update Start F." and "Update End F." to make it easy to quickly change the start and end frames of the range to match the current frame.
- Added "**Export Current Frame**" button to export the current frame with applied crop and fixed resolution settings. Useful if you want to extract specific frames from your footage for captioning or to include it as a high res image in your dataset.
- Added "**Delete Video**" button that moves the selected video to the Recycle Bin and updates the session.

### Minor UI Improvements
- Redesigned the right panel, creating space-efficient, minimizable Tabs for **Crop Settings** and **Captioning Settings**.
- The UI layout was reorganized to reduce space wastage, moving export buttons into a single row.
- Added a minimizable container for "**Crop**" and "**Captioning**" tabs.
- Added a minimizable container for "**Workflow**" and "**Attribution**" labels to free up vertical space in the left pane.
- Improved tab minimization logic to trigger a video canvas re-render, allowing the video to occupy the newly available window space.
- Reorganized top control buttons: "**Select Folder**" and "**Convert FPS**" are now in a single row.
- Adjusted list widgets (**Video List** and **Clip Range List**) to expand and occupy all available vertical space in the left pane.

### Bug Fixes
- Normalized paths across entire app to prevent "file not found" errors and ensured session data is sanitized as well.


## [2026-04-18]
### Bug Fixes
- Crop region usage no longer causes "random" crashes.
- Crop region can now be properly resized and moved after creation.

## [2026-04-19]
### Added Features
- Added "**Export All Ranges as Defined**" checkbox to the export options in the left pane. This should be more useful than the other two export options, as it exports all defined ranges once - cropped if they have a crop rect defined, and uncropped if they don't. This is the new default export method.

### UX Improvements
- Renamed existing Export checkboxes to better reflect their function. Also added tooltips to clarify their function.
- Added icons to the main buttons for better UX
- Rewrote shortcut instructions to be more visually pleasing and easier to read
- Moved **"Clear Crop"** button from the left panel into the **Crop tab**, placed next to the "Update Crop" button for a more logical grouping.

### Bug Fixes
- **Delete Video** no longer raises `WinError 32` ("file in use by another process"). The fix stops active playback via the timer and correctly releases the `cv2.VideoCapture` handle held by `VideoCropper.cap` (previously the code was checking a non-existent `editor.cap` attribute).
- **Session data sanitation**: `VideoLoader.load_session()` now calls `_sanitize_session_paths()` after loading, which removes stale entries from `folder_sessions`, `video_files`, and `video_data`, removing any folders or files that no longer exist on disk. The active folder path is also cleared if it has been deleted.
- **Close with no folder selected** no longer raises `AttributeError: 'VideoCropper' object has no attribute 'longest_edge'`. Fixed in two places: `longest_edge` is now initialized to `1024` in `VideoCropper.__init__`, and `save_session` uses `getattr(..., 1024)` as a safe fallback.
- **"Clear" (fixed resolution) button** no longer raises `AttributeError: 'VideoCropper' object has no attribute 'on_aspect_ratio_changed'`. The call in `toggle_fixed_resolution_mode(False)` is corrected to `self.set_aspect_ratio(...)`, which is the actual method name.

## [2026-04-20]
### Added Features
- The app now remembers the last opened folder and automatically reopens it on startup.
- Opening a previously opened folder now scans for newly added videos and includes them, instead of only loading previous session data.

### UX Improvements
- Added global keyboard shortcuts for all frame navigation controls in the top row. They will now trigger regardless of widget focus.
- Added spacebar as a global keyboard shortcut for play/pause normal playback.
- **Delete Video** button now doesn't need confirmation before deletion. Since it moves the selected video to the Recycle Bin instead of permanently deleting it anyway, why not save that extra click?

### Bug Fixes
- Fixed the issue where the app would crash when opening a folder with no videos in it.

## [2026-04-21]
### Added Features
- Added Playback Speed controls. A float spinner and reset button were added to the right panel next to the Clip Length label, allowing adjustment of playback speed for both normal and range preview playback.
- Updated Global Shortcuts: `A` to decrease playback speed, `S` to reset speed to 1.0, and `D` to increase playback speed.
- Reassigned nudge shortcuts: `Q`/`W` now nudge the start frame, and `E`/`R` now nudge the end frame.
- **Loop Toggle Button**: The 🔁 button (next to the speed controls) is now a functional toggle. Click it to enable or disable playback looping.
  - When **Loop is ON**, normal playback (C / Space) restarts from frame 0 when the video ends; Range preview (Z / Y) restarts from the range's start frame when it reaches the range's end frame.
  - When **Loop is OFF** (default), playback stops as before.
  - The button changes colour (blue highlight = ON, muted = OFF) and its tooltip dynamically describes the current state and what clicking will do.

## [2026-04-23]
### Added Features
- **Video Editing Tab**: A new dedicated **"Video Editing"** tab has been added to the right-panel tab widget, providing non-destructive tools for rearranging video footage without opening an external editor.
- **Trim Section** (Video Editing tab):
  - **Overwrite current video** checkbox (checked by default): when enabled the original file is replaced in-place; when unchecked a `_trimmed` copy is created alongside it and added to the video list.
  - **Trim Start / Trim End** mode selector: choose whether to cut from the beginning or the end of the video.
  - **Boundary Frame spinner**: clamped to `0 – (frame count – 1)` and automatically updated whenever a new video is loaded. Represents the *first good frame* (Trim Start) or *last good frame* (Trim End).
  - **Trim button**: executes the trim via ffmpeg stream-copy (no re-encode — fast and lossless). When overwriting, the video capture handle is released beforehand (same safe pattern as Delete Video) and the video is reloaded automatically afterwards with its ranges reset.
- **Split Video Section** (Video Editing tab):
  - **Delete original video** checkbox (checked by default): moves the source file to the Recycle Bin after a successful split.
  - **Frame numbers text field**: accepts one or more frame numbers (first frame of each target part) separated by commas or spaces. Frame 0 is always implicitly the start of the first part.
  - **Split button**: writes each segment as `_part01`, `_part02`, … using ffmpeg stream-copy, then adds each part to the video list. The original is only deleted once all parts are confirmed written.
- **Folder Monitoring** (`VideoLoader`): a `QFileSystemWatcher` now monitors the currently open folder for filesystem changes. When a video file is added externally (e.g. copied into the folder), it automatically appears in the video list. When a video file is deleted externally it is automatically removed. No extra dependency — `QFileSystemWatcher` ships with PyQt6.
- **`scripts/video_file_operator.py`** [new module]: encapsulates all trim and split ffmpeg logic in a clean, reusable, stateless class (`VideoFileOperator`). Uses ffmpeg-python with the `-nostdin` flag (consistent with the rest of the app). Temporary files are used for in-place overwrites to prevent data loss on failure.
- All new widgets include descriptive rich-text tooltips.
- **Delete All Selected Videos** button added next to **Delete Video**. Deletes every video whose checkbox is checked in the video list and moves each to the Recycle Bin. After mass deletion the selection lands on the item just before the first deleted entry.
- **Right-click context menu** on video list entries:
  - **📋 Copy Path** — copies the full absolute file path (including filename and extension) to the clipboard.
  - **📂 Open in Windows Explorer** — opens the video's parent folder in Windows Explorer with the file pre-selected.

### UX Improvements
- Loop is now on by default
- **Compact video list** — row height reduced by tightening the item padding in `dark_mode.css`, allowing more videos to be visible at once without scrolling.
- **Autoplay on selection** — clicking a video in the list now automatically starts playback immediately after the video loads.
- **Delete preserves position** — deleting the currently selected video (via the Delete Video button, the Delete All Selected button, or an external file deletion detected by the folder watcher) now moves the selection to `index - 1` instead of resetting it to the top of the list.
- **Enter key clears focus on all text inputs** — pressing Enter in any text field (Start Frame, End Frame, Duration, Crop X/Y/W/H, Go To Frame, Prefix, Trigger Word, Character Name, Gemini API Key, Custom AR Width/Height, Split Frames) now removes focus from the field so global keyboard shortcuts (`C`, `Space`, arrow keys, etc.) immediately work again without needing an extra click.
- **New Range inherits crop** — clicking **➕ Add Range** while a range with a crop rectangle is selected now creates the new range with that same crop rect pre-applied, avoiding repetitive manual re-drawing of the same crop region for each clip.
- Fixed `QSpinBox` and `QDoubleSpinBox` up/down buttons display in dark mode by implementing proper CSS positioning and custom triangle arrow icons.
- Made buttons more compact.

## [2026-04-23 — Captioning Tab]
### Added Features
- **Caption editor in Captioning tab**: A multiline text editor (`QTextEdit`) now appears in the Captioning tab. It automatically loads the `.txt` file that shares the same name as the selected video (e.g. `clip.mp4` → `clip.txt`). If no file exists yet, starting to type creates it.
- **English US spellchecking**: Misspelled words are underlined in red using a `QSyntaxHighlighter` backed by the `pyspellchecker` library.
- **Auto-save with data-safety guarantees**:
  - Saves are debounced — the disk write fires 800 ms after the last keystroke, so rapid typing never hammers the disk.
  - Writes use an atomic strategy: text is first written to a sibling `.tmp` file with `flush()` + `os.fsync()` (forces OS write-cache to physical disk), then swapped in via `os.replace()` (NTFS-atomic). The caption file is therefore never left in a corrupt or truncated state — safe even through a hard power cut.
  - On app close any pending debounced save is flushed immediately, so no work is lost even if the window is closed right after the last keystroke.
- **📄 Create Copy of the Caption File** button: creates a numbered duplicate (`<stem>_01.txt`, `_02.txt`, …, first free suffix) and shows a confirmation dialog with the new filename.
- **📂 Open Caption File in Windows Explorer** button: opens the video folder in Explorer with the `.txt` file pre-selected.
- **📝 Open Caption File in Windows Explorer** right-click context-menu entry added to the video list: shown only when a caption file actually exists for the right-clicked video.
- `scripts/caption_manager.py` [new module]: pure I/O helper with `get_caption_path`, `load_caption`, `save_caption_atomic`, `copy_caption`, and `caption_exists`.
- `scripts/spellcheck_highlighter.py` [new module]: `QSyntaxHighlighter` subclass wrapping `pyspellchecker`.  Degrades gracefully (no-op + warning) when the library is missing.

## [2026-04-23] - Bug Fix - Video Selection Shortcut (X)
- **Unified Video Selection Logic**: Transitioned from `itemClicked` to `currentRowChanged` for the main video list. This ensures that video loading, canvas updates, and caption loading occur consistently regardless of whether the selection was changed by mouse, keyboard (Up/Down arrows), or the "X" shortcut.
- **Fixed "X" Shortcut**: The "Next Video" shortcut (X) now correctly triggers the full video activation sequence, including autoplay and caption loading.
- **Refactored `VideoCropper`**: Extracted video activation logic into `_activate_video_item` for cleaner internal reuse.
- **Cleaned Up `VideoEditor`**: Removed obsolete manual loading calls in `next_clip` and `navigate_clip`, relying instead on the `currentRowChanged` signal.
- Made spell checker not flag curly (’) apostrophes as misspelled when used in words like "don't"

## [2026-04-27]
### Changed
- Workflow and Attribution section now starts minimized on app start
- **Clip frame-sync default changed to "duration-only"**:
  - Editing **Start Frame** or **End Frame** now always recalculates **Duration** (the other boundary frame is kept fixed). This is the default.
  - **Exception — duration lock**: if the user manually typed a value into the **Duration** field within the last **20 seconds** for the *same clip and range*, the duration is preserved and the *other* boundary frame slides:
    - Editing **Start Frame** → **End Frame** slides to `start + duration` (clamped to video length).
    - Editing **End Frame** → **Start Frame** slides to `end - duration` (clamped to ≥ 0).
  - If a slid boundary hits the video edge it is clamped, and Duration is recalculated from the actual boundaries.
  - The lock expires automatically after 20 s or when a different clip or range is selected.
  - Implemented via `_is_duration_locked()` using `time.monotonic()` + a `video_path|range_id` context key, replacing the old `last_changed_sync` string flag.

## [2026-05-04]
### Performance
- **Fixed severe frame-navigation and playback lag on large (1000+ frame) videos.** Three root causes were identified and resolved:

  1. **Eliminated full-resolution CPU pixmap scaling on every frame** (`video_editor.py` — `display_frame`):
     Previously, every rendered frame was uploaded to Qt as a full-resolution `QPixmap` (e.g., 1920 × 1080) and then downscaled using Qt's `SmoothTransformation` (bicubic) on the CPU. This was the largest bottleneck. The fix pre-scales the raw NumPy frame with `cv2.resize(INTER_LINEAR)` — OpenCV's SIMD-optimised resize — *before* wrapping it in `QImage`. The full-resolution `QPixmap` allocation and the Qt-side bicubic pass are now completely avoided.

  2. **Eliminated redundant `fitInView` calls on every frame** (`video_editor.py` — `display_frame`):
     `graphics_view.fitInView()` was called unconditionally on every frame render, forcing Qt to recompute the view transform matrix and trigger a layout pass each time. The last rendered viewport size is now cached in `_last_viewport_size`; `fitInView` and `setSceneRect` are called only when the viewport dimensions actually change (e.g., window resize). The cache is reset on each video load so the first frame always initialises the scene rect correctly.

  3. **Fixed double frame-decode on every keyboard navigation step** (`video_cropper.py` — `initUI`):
     The slider was connected to `scrub_video` via both `sliderMoved` *and* `valueChanged`. `valueChanged` also fires on programmatic `setValue` calls inside `update_frame_display`, causing a redundant second `cap.set` + `cap.read` on every ←/→ key press or nudge. The `valueChanged → scrub_video` connection was removed; only `sliderMoved` (user drag) remains.

- **Added thumbnail hover debounce** (`video_editor.py` — `show_thumbnail` / new `_render_thumbnail`):
  Hovering over the slider previously triggered an immediate seek + frame decode on every mouse-move event, causing hitches on H.264/HEVC video (each seek can decompress an entire GOP). A single-shot 80 ms debounce timer now delays the thumbnail decode until the mouse settles, and the thumbnail frame is pre-scaled with `cv2.resize` before QImage creation — consistent with the main display path.

- **Fixed slider drag still being slow** (`video_editor.py` — `scrub_video`):
  `scrub_video` was called on every pixel of mouse movement with no rate limiting, causing H.264/HEVC seek calls to queue faster than they could be processed. A time-based throttle of ≈ 30 fps (33 ms minimum between seeks) was added. The final position is always rendered via `_on_slider_released` so the displayed frame never lags behind where the user stopped.

- **Fixed clicking on the slider groove not updating the frame** (`video_cropper.py` — `initUI`; `video_editor.py` — new `_on_slider_released`):
  Clicking a position on the slider groove emits only `valueChanged` (not wired) and `sliderReleased`. Since `sliderMoved` does not fire for groove clicks, the frame display was never updated. A new `_on_slider_released` slot is now connected to `slider.sliderReleased`; it force-updates to the current slider value and resets the scrub throttle for the next drag.

- **Fixed thumbnail aspect ratio being wrong** (`video_editor.py` — `_render_thumbnail`):
  The thumbnail was always resized to a fixed 160 × 90 pixels regardless of the video's aspect ratio, causing stretching. The thumbnail width is now computed from the original video's `original_width / original_height` ratio at a fixed height of 90 px.

- **Removed verbose `print()` calls from the playback hot path** (`video_editor.py` — `_playback_step`):
  "Looping back to start frame…" and "Normal playback finished." were printed on every loop iteration or end-of-stream event, adding unnecessary I/O overhead to the tight playback timer callback. These messages are removed; error conditions are still printed.

- **Switched VideoCapture to hardware-accelerated backend** (`video_editor.py` — new `_open_capture` / `load_video_properties`):
  The root cause of the 4-second seek delay was OpenCV's FFMPEG backend doing **software H.264 decode-and-discard**: to reach frame N in a compressed GOP, it decodes and discards every intermediate frame from the nearest keyframe. For 60fps H.264 video with a 2-second keyframe interval, this means decoding up to 119 frames in software (~3–5 s on a typical CPU). The new `_open_capture()` helper tries backends in order: **`CAP_MSMF`** (Windows Media Foundation — uses the system's hardware H.264/H.265 decoder via Intel QSV, NVIDIA NVDEC, or AMD VCE, the same path VLC uses) → `CAP_FFMPEG` → `CAP_ANY`. MSMF performs keyframe-approximate seeking natively, eliminating the decode-and-discard pass.

- **Dedicated thumbnail VideoCapture** (`video_editor.py` — `_thumb_cap` / `_render_thumbnail`):

- **Moved interactive frame-seeking off the main UI thread** (`scripts/frame_seek_worker.py` — new; `video_editor.py` — `_SeekProxy`, `request_seek`, `_on_async_frame_ready`, `cleanup`; `video_cropper.py` — `closeEvent`):
  Even with MSMF hardware decoding, seeking to an exact frame takes ~800 ms because the decoder decompresses all frames between the nearest keyframe and the target. Performing this on the main thread freezes the entire UI. The fix moves all interactive seeking to a `FrameSeekWorker` running on a dedicated `QThread` with its own `VideoCapture`.

  Key design decisions:
  - **"Latest wins" coalescing**: new seek requests arriving while the worker is busy overwrite the pending slot; only the most-recently-requested frame is emitted. This prevents a growing queue backlog during fast slider drags.
  - **`_SeekProxy(QObject)`**: a thin proxy owning the cross-thread `pyqtSignal` definitions, since `VideoEditor` is not a `QObject`.
  - **`request_seek(frame_number)`**: replaces direct `update_frame_display()` calls in `scrub_video` and `_on_slider_released`; posts asynchronously and returns immediately so the UI never freezes.
  - **`_on_async_frame_ready(frame, frame_number)`**: called back on the main thread via Qt queued connection; updates the viewport, slider, and frame label.
  - **`cleanup()`**: stops the thread gracefully; called from `VideoCropper.closeEvent`.
  - Playback (`_playback_step`) continues to use synchronous sequential `cap.read()`, which needs no seek and is fast.

## [2026-05-04 — PyAV Seek Engine Migration]
### Performance

**Root-cause analysis via live benchmarks** revealed that OpenCV/MSMF's
per-seek cost (348 ms avg, 641 ms max) scales with *absolute file position*
and is independent of seek distance — even a ±1 frame step costs ~340 ms.
This is MSMF's COM session flush-and-rebuild overhead, not decode-and-discard.

| Backend | Seek avg | Seek max |
|---------|----------|----------|
| OpenCV / MSMF (old) | 348 ms | 641 ms |
| OpenCV / FFMPEG | 775 ms | 1185 ms |
| **PyAV frame-accurate** | **56 ms** | **97 ms** |
| **PyAV keyframe-only** | **5.7 ms** | **6.2 ms** |

**Changes:**
- Moved to PyAV for faster frame seeking, enabling super-performant video playback, allowing you to **work on longer and larger videos** that were previously unmanageable. There is now virtually no lag when seeking, and the app can handle 4k 60fps videos with ease.

- **`scripts/pyav_seek_worker.py`** [new]: Replaces `FrameSeekWorker`.
  Uses PyAV (libavformat + libavcodec — the same C libraries VLC and the
  ffmpeg CLI use) for frame-accurate seeking at ~56 ms average.
  Seek strategy: `container.seek(pts, backward=True, any_frame=False)` jumps
  to the nearest I-frame using the MP4 container index (O(log n) byte seek),
  then demuxes forward to the exact target frame.  Same "latest wins"
  single-in-flight contract as the old worker.

- **`scripts/thumbnail_seek_worker.py`** [new]: Off-thread thumbnail generator.
  Uses PyAV **keyframe-only** seeking (~5.7 ms avg) — decodes just the first
  frame after the seek (the keyframe itself) with no forward iteration.
  Acceptable visual approximation at 90 px height.
  A **16-entry LRU cache** (`collections.OrderedDict`) stores pre-scaled
  `QImage` objects; cache hits emit immediately with no I/O (~0 ms).
  Emits `QImage` (thread-safe); main thread converts to `QPixmap`.

- **`video_editor.py`**:
  - `_ThumbProxy` QObject added for thumbnail worker signals.
  - `load_video_properties`: removed `_thumb_cap` (old on-thread MSMF cap);
    both workers notified via queued signals on video open.
  - `_render_thumbnail` replaced by `_dispatch_thumbnail_seek` (50 ms
    debounce → cross-thread signal) + `_on_thumbnail_ready` (main-thread slot,
    QImage → QPixmap conversion).
  - `step_frame`, `jump_frames`, `goto_frame` all route through `request_seek`
    (async PyAV) instead of `update_frame_display` (sync MSMF).
  - Thumbnail debounce interval: 80 ms → **50 ms**.
  - Scrub throttle interval: 33 ms → **50 ms**.
  - `cleanup()` now gracefully stops both `_seek_thread` and `_thumb_thread`.

- **`requirements.txt`**: added `av==17.0.1`.
