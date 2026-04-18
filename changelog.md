# Changelog

## [2026-04-16]
### Added Features
- Made the "Start Frame" text box editable, updating the current clip range when editing is finished. You can now manually edit start of your range and even create overlapping ranges.
- Added "End Frame" text box next to "Start Frame" text box for range selection to enable you to set your clip range based on a specific end frame instead of just duration.
- Range logic synchronization: start frame, end frame, and duration are now linked and recalculate based on the most recently modified property. When recalculation is triggered, the most recently modified properties are preserved while the oldest one is synced to the other two.
- Support for keyboard shortcut `Y` for "Preview Range" alongside existing `Z` key (to accommodate QWERTZ keyboards).
- Implemented global keyboard shortcuts for "Preview Range" (Z/Y) to ensure they work regardless of widget focus.
- Frame navigation sub-controls added: "Start Frame", "End Frame" jump buttons to quickly navigate to the start and end frames of the current clip range.
- Range boundary update controls added: "Update Start F." and "Update End F." to make it easy to quickly change the start and end frames of the range to match the current frame.
- Added "Export Current Frame" button to export the current frame with applied crop and fixed resolution settings. Useful if you want to extract specific frames from your footage for captioning or to include it as a high res image in your dataset.
- [WIP] Added "Delete Video" button that moves the selected video to the Recycle Bin and updates the session.

### Minor UI Improvements
- Redesigned the right panel, creating space-efficient, minimizable Tabs for Crop Settings and Captioning Settings.
- The UI layout was reorganized to reduce space wastage, moving export buttons into a single row.
- Added a minimizable container for "Crop" and "Captioning" tabs.
- Added a minimizable container for "Workflow" and "Attribution" labels to free up vertical space in the left pane.
- Improved tab minimization logic to trigger a video canvas re-render, allowing the video to occupy the newly available window space.
- Reorganized top control buttons: "Select Folder" and "Convert FPS" are now in a single row.
- Adjusted list widgets (Video List and Clip Range List) to expand and occupy all available vertical space in the left pane.

### Bug Fixes
- Normalized paths across entire app to prevent "file not found" errors and ensured session data is sanitized as well.


## [2026-04-18]
### Bug Fixes
- Crop region usage no longer causes "random" crashes.
- Crop region can now be properly resized and moved after creation.