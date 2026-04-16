# Changelog

## [2026-04-16]
### Added
- Added "End Frame" text box next to "Start Frame" text box for range selection.
- Range logic synchronization: start frame, end frame, and duration are now linked and recalculate based on the most recently modified property.
- Support for keyboard shortcut `Y` for "Preview Range" alongside existing `Z` key (to accommodate QWERTZ keyboards).
- Frame navigation sub-controls added: "Start Frame", "End Frame" jump buttons.
- Range boundary update controls added: "Update Start F." and "Update End F." to precisely set crop slice boundaries to current frame.
- Add minimize/maximize toggle button in the tabs header area.

### Changed
- Made the "Start Frame" text box editable, updating the current clip range when editing is finished.
- Redesigned the right panel, creating space-efficient, minimizable Tabs for Crop Settings and Captioning Settings.
- The UI layout was reorganized to reduce space wastage, moving export buttons into a single row.
