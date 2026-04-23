"""
caption_manager.py
==================
Stateless helper module that encapsulates all caption-file I/O for the
Captioning tab.  Keeping this logic separate from the main UI class makes
it independently testable and avoids cluttering video_cropper.py.

All writes use an atomic temp-file + os.replace() pattern combined with
os.fsync() so that even a hard power cut will leave the file in a valid
(previous or new) state — never corrupt or truncated.
"""

import os


def get_caption_path(video_path: str) -> str:
    """
    Derive the expected caption file path from a video path.

    The caption file lives in the same directory as the video and shares
    its stem (basename without extension), with a `.txt` extension.

    Args:
        video_path (str): Absolute path to the video file.

    Returns:
        str: Absolute path to the corresponding caption .txt file.
    """
    stem = os.path.splitext(video_path)[0]
    return stem + ".txt"


def load_caption(video_path: str) -> str:
    """
    Load the caption text for the given video.

    Args:
        video_path (str): Absolute path to the video file.

    Returns:
        str: Caption text, or an empty string if no caption file exists.
    """
    caption_path = get_caption_path(video_path)
    if os.path.isfile(caption_path):
        try:
            with open(caption_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            print(f"⚠️ Could not read caption file '{caption_path}': {exc}")
    return ""


def save_caption_atomic(video_path: str, text: str) -> bool:
    """
    Atomically save caption text to the caption file co-located with the video.

    Strategy (safe against crashes and power outages):
    1. Write to a sibling temp file (<stem>.tmp) with flush + fsync.
    2. Atomically replace the real file with os.replace() — NTFS guarantees
       this swap is atomic, so the file is never left in a partial state.

    Args:
        video_path (str): Absolute path to the video file.
        text (str): Caption text to save.

    Returns:
        bool: True on success, False on failure.
    """
    caption_path = get_caption_path(video_path)
    tmp_path = caption_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())  # Force OS write cache to physical disk
        os.replace(tmp_path, caption_path)  # Atomic rename on NTFS
        return True
    except OSError as exc:
        print(f"⚠️ Could not save caption file '{caption_path}': {exc}")
        # Clean up leftover temp file on failure
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


def copy_caption(video_path: str) -> str | None:
    """
    Create a numbered copy of the caption file.

    The copy is named ``<stem>_01.txt``, ``<stem>_02.txt``, etc., using the
    first number suffix that is not already taken.

    Args:
        video_path (str): Absolute path to the video file whose caption
            should be copied.

    Returns:
        str | None: Absolute path to the newly created copy, or ``None``
            if the source caption file does not exist or the copy failed.
    """
    source_path = get_caption_path(video_path)
    if not os.path.isfile(source_path):
        return None

    stem = os.path.splitext(source_path)[0]

    # Find the first unused suffix _01, _02, …
    suffix_n = 1
    while True:
        candidate = f"{stem}_{suffix_n:02d}.txt"
        if not os.path.exists(candidate):
            break
        suffix_n += 1
        if suffix_n > 999:  # Safety upper bound
            print("⚠️ Could not find a free suffix for caption copy (>999 copies).")
            return None

    try:
        with open(source_path, "r", encoding="utf-8") as src:
            content = src.read()

        # Use atomic write for the copy as well
        tmp_path = candidate + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as dst:
            dst.write(content)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp_path, candidate)
        return candidate
    except OSError as exc:
        print(f"⚠️ Could not create caption copy '{candidate}': {exc}")
        return None


def caption_exists(video_path: str) -> bool:
    """
    Check whether a caption file already exists for the given video.

    Args:
        video_path (str): Absolute path to the video file.

    Returns:
        bool: True if the caption .txt file exists on disk.
    """
    return os.path.isfile(get_caption_path(video_path))
