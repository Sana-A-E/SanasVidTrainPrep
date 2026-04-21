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
