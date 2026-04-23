# Sana's VidTrainPrep
This is Sana's fork of VidTrainPrep, aiming to fix bugs, add quality of life improvements and useful missing functionality.

The code is mostly done with AI assistance as it is faster than doing it by hand, (and because Python isn't my specialty), so while I do check what AI is doing before approving it, it isn't a very thorough check so I can't guarantee that there won't be any regressions or bugs I might have missed. However, as I am actively using the app, the bugs I notice, I will of course fix. (In my personal experience, the app is much more usable and stable than the original.)

If I don't notice the bugs (because they are in the part of the app functionality I rarely use) feel free to report them and I might fix them. No promises though. I just wanted to share this in case anyone else needs their video dataset prep app to be more stable and feature complete.

I will not be upgrading/fixing the Gemini API as there are other apps that do LLM captioning better (I recommend [Vision Captioner](https://github.com/Brekel/VisionCaptioner) for local LLMs or [Klippbok](https://github.com/alvdansen/klippbok) for cloud-based & local LLMs.)

## Notable New Features and Changes:
- Fixed drawing of crop rects to actually work without causing app crashes. Crop rects can now be properly resized and moved after creation as you would expect.
- Added **Playback Speed Controls** allowing adjustment of playback speed for both normal and range preview playback. Added shortcuts to control it (A/S/D), and reassigned existing overlapping shortcuts.
- Playback can now **Loop**. You can toggle looping on/off via 🔁 button to the right of the playback speed controls.
- **Caption editor in Captioning tab**: You can now view and edit the video's caption file, alleviating the need to have another app for editing captions. Since we have a nice video playback and other features, why not leverage them to enhance your reviewing and manual editing of captions as well? App automatically loads the `.txt` file that shares the same name as the selected video (e.g. `clip.mp4` → `clip.txt`). If no file exists yet, starting to type creates it. App autosaves the changes, and the area has spellchecking for English US, with the ability to temporarily whitelist words that it mistakenly thinks is misspelled. 
- Added **"Export All Ranges as Defined"** checkbox to the export options in the left pane. This should be more useful than the other two export options, as it exports all defined ranges once - cropped if they have a crop rect defined, and uncropped if they don't. This is the new default export method
- Session data is now sanitized to remove videos and folders that no longer exist.
- The app now remembers the last opened folder and automatically reopens it on startup.
- Opening a previously opened folder now scans for newly added videos and includes them, instead of only loading previous session data.
- The UI layout was reorganized to reduce space wastage, and tooltips were added to clarify function/usage of elements.
- Made the **"Start Frame"** text box editable, updating the current clip range when editing is finished. You can now manually edit start of your range and even create overlapping ranges.
- Added **"End Frame"** text box next to "Start Frame" text box for range selection to enable you to set your clip range based on a specific end frame instead of just duration.
- **Range logic synchronization:** start frame, end frame, and duration are now linked and recalculate based on the most recently modified property. When recalculation is triggered, the most recently modified properties are preserved while the oldest one is synced to the other two.
- Support for keyboard shortcut `Y` for **"Preview Range"** alongside existing `Z` key (to accommodate QWERTZ keyboards) and `Spacebar` for video playback. Also all keyboard shortcuts are now global, meaning they will work regardless of widget focus.
- Frame navigation sub-controls added: **"Start Frame"**, **"End Frame"** jump buttons to quickly navigate to the start and end frames of the current clip range.
- Range boundary update controls added: **"Update Start F."** and **"Update End F."** to make it easy to quickly change the start and end frames of the range to match the current frame.
- Added **"Export Current Frame"** button to export the current frame with applied crop and fixed resolution settings. Useful if you want to extract specific frames from your footage for captioning or to include it as a high res image in your dataset.
- **Video Editing Tab** — a dedicated tab for non-destructive video file operations:
  - **Trim**: remove unwanted frames from the very start or end of a video. Choose between in-place overwrite (the original file is replaced and immediately reloaded) or creating a `_trimmed` copy alongside it. Uses ffmpeg stream-copy — fast and lossless.
  - **Split Video**: divide a video into multiple parts by specifying the first frame of each part (comma or space separated). Parts are named `_part01`, `_part02`, etc. and are immediately added to the video list. Optionally moves the original to the Recycle Bin after a successful split.
- **Real-time Folder Monitoring**: the video list now updates automatically when files appear in or disappear from the currently open folder, without requiring a manual reload.

[View all changes in Changelog](changelog.md).


# Outdated Readme of the original VidTrainPrep:

**VidTrainPrep** is a Python-based tool designed for clipping and preparing video data, specifically tailored for creating datasets for training video models like **LORA, Wan, or Hunyuan**. It allows for precise range selection, cropping, FPS conversion, and optional AI-powered description generation using the Gemini API.

**Acknowledgement:** This tool is a significant refactoring and enhancement based on the original [HunyClip by Tr1dae](https://github.com/Tr1dae/HunyClip).

![VidTrainPrep Workflow](visual.gif) 
*(Note: Screenshot might be slightly outdated)*

## Key Features

*   **Range-Based Clipping:** Define multiple start/end points (ranges) within a single source video, instead of just one trim point.
*   **Interactive Range Creation:** Create new clip ranges visually by drawing a crop rectangle on the desired start frame. The duration set in the UI is used to determine the end frame.
*   **Independent Range Cropping:** Assign a unique crop region to each defined range.
*   **FPS Conversion Tool:** Pre-process videos in a selected folder by converting them to a target FPS (e.g., 30 FPS) into a new subfolder, crucial for training consistency.
*   **Gemini Integration (Optional):**
    *   Automatically generate descriptions for exported video ranges using the Gemini API (requires API key), helpful for creating captions or prompts.
    *   Optionally prepend a custom **Trigger Word** (e.g., `MyLoraTag, ...`) to generated descriptions/captions.
    *   Optionally provide a **Character Name** to be included in the prompt sent to Gemini for more personalized descriptions.
*   **Flexible Export Options:**
    *   Export cropped video clips.
    *   Export uncropped video clips (full frame, but timed to the range).
    *   Export an image frame from the start of each selected range.
*   **Modern UI:** Refreshed dark monochrome theme.
*   **Session Saving:** Remembers the selected folder, defined ranges, and export settings.
*   **Keyboard Shortcuts:** For faster navigation and editing.

## Installation (Windows Focus)

### Prerequisites

*   **Python:** 3.8 or higher recommended. Download from [python.org](https://www.python.org/). Ensure Python and Pip are added to your system's PATH during installation.
*   **FFmpeg:** Required for video processing (cropping, FPS conversion). 
    *   Download from [ffmpeg.org](https://ffmpeg.org/download.html) (e.g., the `gyan.dev` builds for Windows).
    *   Extract the downloaded archive.
    *   **Crucially, add the `bin` directory** (containing `ffmpeg.exe`, `ffprobe.exe`) **to your system's PATH environment variable.** You can find guides online on how to add directories to the PATH on Windows.
*   **Git:** Optional, but recommended for cloning. Download from [git-scm.com](https://git-scm.com/).

### Steps

1.  **Clone or Download:**
    *   **Using Git (Recommended):**
        ```bash
        git clone https://github.com/lovisdotio/VidTrainPrep.git # Replace with your repo URL if forked
        cd VidTrainPrep
        ```
    *   **Download ZIP:** Download the repository ZIP from GitHub, extract it, and open a terminal (like Command Prompt or PowerShell) in the extracted folder.

2.  **Run the Setup Script:**
    *   Double-click the `Start.bat` file.
    *   This script will automatically:
        *   Create a Python virtual environment (`venv` folder).
        *   Activate the environment.
        *   Install all required Python packages (PyQt6, ffmpeg-python, google-generativeai, Pillow, etc.) from `requirements.txt`.
        *   Launch the application (`main.py`).

## Usage Workflow

1.  **Select Folder:** Click `Select Folder` and choose the directory containing your source videos.
2.  **(Optional) Convert FPS:**
    *   Click `Convert FPS...`.
    *   Enter the desired Target FPS (e.g., 30) and a name for the output subfolder (e.g., `converted_30fps`).
    *   Click `OK`. The conversion process will run in the background (check console output).
    *   Once complete, the application will automatically reload using the new subfolder.
3.  **Load Video:** Click a video name in the "Video Files" list.
4.  **Define Clip Ranges:**
    *   **Navigate:** Use the slider to find the desired start frame for your first clip.
    *   **Set Duration:** Enter the desired clip duration (in frames) in the "Duration (f)" field.
    *   **Create Range by Cropping:** Click and drag on the video preview to define the crop region. When you release the mouse, a new range will be added to the "Clip Ranges" list, starting at the current frame, using the specified duration, and including the crop you drew.
    *   **Create Range without Cropping:** Click the `Add Range Here` button. This adds a range at the current frame with the specified duration, but *without* a crop.
    *   **Repeat:** Navigate to other start frames, adjust duration, and draw crops (or click `Add Range Here`) to define all the ranges you need from this source video.
5.  **Manage Ranges:**
    *   **Select:** Click a range in the "Clip Ranges" list to view/edit its properties.
    *   **Adjust Duration:** Select a range and modify the "Duration (f)" field. The end frame is calculated automatically.
    *   **Update Crop:** Select a range and simply draw a new crop rectangle on the video. The selected range's crop will be updated.
    *   **Clear Crop:** Select a range and click `Clear Crop for Selected Range`.
    *   **Remove:** Select a range and click `Remove Range`.
    *   **Preview:** Select a range and press `Z` to loop playback within that range.
6.  **Configure Export Options:**
    *   **Checkboxes:** Select whether to export cropped clips, uncropped clips, and/or an image from the start frame of each range.
    *   **(Optional) Output Res:** Set a maximum longest edge for exported videos (requires FFmpeg scaling).
    *   **(Optional) Filename Prefix:** Enter text to replace the original filename part.
    *   **(Optional) Trigger Word:** Enter a word/tag to prepend to Gemini descriptions (e.g., `mydata, ...`).
    *   **(Optional) Character Name:** Enter the subject's name to include in Gemini prompts.
    *   **(Optional) Gemini:** Enter your Gemini API Key and check "Generate Gemini..." to enable AI descriptions/captions.
7.  **Select Videos for Export:** In the main "Video Files" list, **check the box** next to each video source whose defined ranges you want to export.
8.  **Export:** Click `Export Selected Video(s)`. The application will process each checked video, exporting files for each of its defined ranges into the `cropped` and/or `uncropped` subfolders based on your settings.

## Keyboard Shortcuts

*   **Z**: Preview (Loop) selected range.
*   **C**: Play/Pause normal playback from current position.
*   **X**: Select Next Video in the main list.
*   **A / S**: Nudge Start Frame Left / Right (of selected range - updates duration).
*   **Q / W**: Nudge End Frame Left / Right (by changing duration).
*   **Delete / Backspace**: Remove selected range (when range list has focus).

## Contributing

Contributions or suggestions are welcome! Please fork the repository and create a pull request with your changes.

## Acknowledgments

*   Original HunyClip concept and base: [Tr1dae](https://github.com/Tr1dae)
*   PyQt6 for the GUI framework.
*   OpenCV and FFmpeg (via ffmpeg-python) for video processing.
*   Google Gemini API (via google-generativeai) for AI descriptions.
