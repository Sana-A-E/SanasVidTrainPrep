"""
video_file_operator.py

Provides VideoFileOperator — a stateless helper that handles all destructive
video file operations (trim and split) using the ffmpeg-python library.

Assumes that ffmpeg is installed and available on the system PATH.

NOTE ON APPROACH: Stream-copy (``-c copy``) cannot perform frame-accurate cuts
because it can only cut at keyframe boundaries.  Forcing non-keyframe cuts with
stream-copy produces corrupted output files.  Therefore trim and split always
re-encode the video using libx264 (fast preset, CRF 18 — visually lossless).
Audio is copied where possible, with an AAC fallback on failure.
"""

import os
import tempfile
import ffmpeg
import send2trash


class VideoFileOperator:
    """
    Encapsulates trim and split operations for video files.

    All public methods are static.  Each returns:
        (success: bool, output_paths: list[str], error_message: str)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def trim_video(
        input_path: str,
        mode: str,
        frame: int,
        fps: float,
        overwrite: bool,
    ) -> tuple[bool, list[str], str]:
        """
        Trims a video from its start or end with frame-accurate re-encoding.

        Re-encoding with libx264 (fast preset, CRF 18) is used instead of
        stream-copy because stream-copy cannot cut at arbitrary frame boundaries
        and produces corrupted output when forced to do so.

        The ``frame`` argument identifies the boundary frame:
        - **"start"** mode: ``frame`` is the *first good frame*; everything
          before it is removed.  ``-ss`` is applied as an output-side option so
          ffmpeg decodes precisely to that frame before encoding.
        - **"end"** mode: ``frame`` is the *last good frame*; everything after
          it is removed via ``-to``.

        When ``overwrite=True`` the result is written to a temp file in the
        same directory first, then atomically replaces the original with
        ``os.replace`` to prevent data loss on partial failure.

        Args:
            input_path (str): Absolute path to the source video.
            mode (str): ``"start"`` or ``"end"``.
            frame (int): Boundary frame number (0-based).
            fps (float): Frame rate of the source video.
            overwrite (bool): Replace original when ``True``; create a
                ``_trimmed`` copy when ``False``.

        Returns:
            tuple[bool, list[str], str]: (success, output_paths, error_message)
            *output_paths* is empty when overwriting.
        """
        if not os.path.isfile(input_path):
            return False, [], f"Input file not found: {input_path}"
        if fps <= 0:
            return False, [], "Invalid FPS — cannot compute timestamps."

        base, ext = os.path.splitext(input_path)
        dir_name = os.path.dirname(input_path)

        # Compute output-side timestamps from frame numbers.
        ss_time = (frame / fps) if mode == "start" else None
        to_time = None if mode == "start" else ((frame + 1) / fps)

        output_path: str
        if overwrite:
            fd, output_path = tempfile.mkstemp(suffix=ext, dir=dir_name)
            os.close(fd)
        else:
            output_path = f"{base}_trimmed{ext}"

        try:
            VideoFileOperator._run_segment(
                input_path, output_path, ss_time=ss_time, to_time=to_time
            )
            if overwrite:
                os.replace(output_path, input_path)
                return True, [], ""
            return True, [output_path], ""
        except ffmpeg.Error as exc:
            err = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
            print(f"❌ ffmpeg trim error:\n{err}")
            VideoFileOperator._safe_remove(output_path)
            return False, [], f"ffmpeg error during trim:\n{err}"
        except Exception as exc:
            VideoFileOperator._safe_remove(output_path)
            return False, [], f"Unexpected error during trim: {exc}"

    @staticmethod
    def split_video(
        input_path: str,
        split_frames: list[int],
        fps: float,
        delete_original: bool,
    ) -> tuple[bool, list[str], str]:
        """
        Splits a video into multiple parts at the specified frame boundaries.

        Each value in ``split_frames`` is the *first frame* of a new segment.
        Frame 0 is implicitly the start of the first segment.  The last segment
        runs to the end of the file.  Output files are named
        ``{base}_part01{ext}``, ``_part02``, etc.

        Re-encoding is used for the same accuracy/validity reasons as trim.
        If ``delete_original`` is ``True`` and all segments succeed, the
        original is moved to the Recycle Bin via ``send2trash``.

        Args:
            input_path (str): Absolute path to the source video.
            split_frames (list[int]): Frame numbers beginning each segment.
            fps (float): Frame rate of the source video.
            delete_original (bool): Recycle original on full success.

        Returns:
            tuple[bool, list[str], str]: (success, output_paths, error_message)
        """
        if not os.path.isfile(input_path):
            return False, [], f"Input file not found: {input_path}"
        if fps <= 0:
            return False, [], "Invalid FPS — cannot compute timestamps."
        if not split_frames:
            return False, [], "No split frames provided."

        base, ext = os.path.splitext(input_path)

        frames = sorted(set(split_frames))
        if frames[0] != 0:
            frames.insert(0, 0)

        segments: list[tuple[int, int | None]] = [
            (frames[i], frames[i + 1] if i + 1 < len(frames) else None)
            for i in range(len(frames))
        ]

        output_paths: list[str] = []
        errors: list[str] = []

        for idx, (start_f, end_f) in enumerate(segments):
            part_label = f"{idx + 1:02d}"
            out_path = f"{base}_part{part_label}{ext}"
            ss = start_f / fps if start_f > 0 else None
            to = end_f / fps if end_f is not None else None
            try:
                VideoFileOperator._run_segment(input_path, out_path, ss_time=ss, to_time=to)
                output_paths.append(out_path)
                print(f"  ✅ Part {part_label}: {os.path.basename(out_path)}")
            except ffmpeg.Error as exc:
                err = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else str(exc)
                errors.append(f"Part {part_label}: {err}")
                print(f"  ❌ Error writing part {part_label}: {err}")
            except Exception as exc:
                errors.append(f"Part {part_label}: {exc}")
                print(f"  ❌ Unexpected error for part {part_label}: {exc}")

        if errors:
            return False, output_paths, "Errors during split:\n" + "\n".join(errors)

        if delete_original:
            try:
                send2trash.send2trash(input_path)
                print(f"  🗑️ Moved to Recycle Bin: {os.path.basename(input_path)}")
            except Exception as exc:
                return True, output_paths, f"Split succeeded but could not delete original: {exc}"

        return True, output_paths, ""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _run_segment(
        input_path: str,
        output_path: str,
        ss_time: float | None,
        to_time: float | None,
    ) -> None:
        """
        Encodes one video segment (trim or split part) using libx264.

        ``-ss`` and ``-to`` are output-side options so that seeking is
        frame-accurate (decode-and-skip rather than keyframe snap).
        Audio is stream-copied first; if that fails, re-encoded as AAC.

        Args:
            input_path (str): Source video path.
            output_path (str): Destination file path.
            ss_time (float | None): Start time in seconds, or ``None`` for 0.
            to_time (float | None): End time in seconds, or ``None`` for EOF.

        Raises:
            ffmpeg.Error: If both audio-copy and AAC fallback attempts fail.
        """
        base_kwargs: dict = {"vcodec": "libx264", "preset": "fast", "crf": "18"}
        if ss_time is not None:
            base_kwargs["ss"] = ss_time
        if to_time is not None:
            base_kwargs["to"] = to_time

        # Attempt 1: copy audio (fast, lossless audio path)
        try:
            stream = ffmpeg.input(input_path)
            stream = ffmpeg.output(stream, output_path, **{**base_kwargs, "acodec": "copy"})
            ffmpeg.run(stream, cmd=["ffmpeg", "-nostdin"], quiet=True, overwrite_output=True)
            return
        except ffmpeg.Error:
            VideoFileOperator._safe_remove(output_path)

        # Attempt 2: re-encode audio as AAC (handles incompatible audio codecs)
        stream = ffmpeg.input(input_path)
        stream = ffmpeg.output(stream, output_path, **{**base_kwargs, "acodec": "aac"})
        ffmpeg.run(stream, cmd=["ffmpeg", "-nostdin"], quiet=True, overwrite_output=True)

    @staticmethod
    def _safe_remove(path: str | None) -> None:
        """Silently removes a file if it exists; used for cleanup on failure."""
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
