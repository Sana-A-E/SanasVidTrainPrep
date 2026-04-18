# Changelog

## [2026-04-16]
### Added
- Added "End Frame" text box next to "Start Frame" text box for range selection.
- Range logic synchronization: start frame, end frame, and duration are now linked and recalculate based on the most recently modified property.
- Support for keyboard shortcut `Y` for "Preview Range" alongside existing `Z` key (to accommodate QWERTZ keyboards).
- Frame navigation sub-controls added: "Start Frame", "End Frame" jump buttons.
- Range boundary update controls added: "Update Start F." and "Update End F." to precisely set crop slice boundaries to current frame.
- Added a minimizable container for "Crop" and "Captioning" tabs.
- Added "Export Current Frame" button to export the current frame with applied crop and fixed resolution settings.
- Added "Delete Video" button that moves the selected video to the Recycle Bin and updates the session.
- Added a minimizable container for "Workflow" and "Attribution" labels to free up vertical space in the left pane.
- Implemented global keyboard shortcuts for "Preview Range" (Z/Y) to ensure they work regardless of widget focus.

### Changed
- Made the "Start Frame" text box editable, updating the current clip range when editing is finished.
- Redesigned the right panel, creating space-efficient, minimizable Tabs for Crop Settings and Captioning Settings.
- The UI layout was reorganized to reduce space wastage, moving export buttons into a single row.
- Improved tab minimization logic to trigger a video canvas re-render, allowing the video to occupy the newly available window space.
- Reorganized top control buttons: "Select Folder" and "Convert FPS" are now in a single row.
- Adjusted list widgets (Video List and Clip Range List) to expand and occupy all available vertical space in the left pane.
- Refined "Preview Range" shortcut mapping to accommodate both QWERTY and QWERTZ keyboards (Z/Y keys).
- Updated project requirements to include `send2trash`.
- Normalized paths across entire app to prevent "file not found" errors and ensured session data is sanitized as well.

## [2026-04-18]
### Bug Fixes
