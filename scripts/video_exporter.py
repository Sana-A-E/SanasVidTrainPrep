import os, ffmpeg, cv2
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import Qt
import google.generativeai as genai
from google.api_core import exceptions # For specific error handling
from PIL import Image
import time # for potential retries
import numpy as np

class VideoExporter:
    def __init__(self, main_app):
        self.main_app = main_app
        self.file_counter = 0  # Counter for incremental padding suffix
        self.gemini_model = None # Initialize Gemini model placeholder

    def _configure_gemini(self):
        """Configures the Gemini API client if not already configured."""
        if self.gemini_model:
            return True # Already configured

        api_key = self.main_app.gemini_api_key_input.text()
        if not api_key:
            print("❌ Gemini API Key is missing. Cannot generate captions.")
            # Optionally show a message box to the user
            # msg = QMessageBox()
            # msg.setIcon(QMessageBox.Icon.Warning)
            # msg.setText("Gemini API Key Missing")
            # msg.setInformativeText("Please enter your Gemini API key in the input field to generate captions.")
            # msg.setWindowTitle("API Key Error")
            # msg.exec()
            return False

        try:
            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            print("✅ Gemini API configured successfully using gemini-1.5-flash-latest.")
            return True
        except Exception as e:
            print(f"❌ Failed to configure Gemini API: {e}")
            self.gemini_model = None # Ensure model is None if config fails
            # Optionally show a more detailed error to the user
            # msg = QMessageBox()
            # msg.setIcon(QMessageBox.Icon.Critical)
            # msg.setText("Gemini API Configuration Error")
            # msg.setInformativeText(f"Failed to configure Gemini API: {e}")
            # msg.setWindowTitle("API Error")
            # msg.exec()
            return False

    def generate_gemini_caption(self, image_path, max_retries=3):
        """Generates a caption for the given image using the Gemini API."""
        if not self.gemini_model and not self._configure_gemini():
             # Attempt to configure if not already done, return if fails
            return None # Configuration failed or API key missing

        try:
            print(f"⏳ Generating Gemini caption for {os.path.basename(image_path)}...")
            img = Image.open(image_path)
            
            # Simple retry mechanism
            for attempt in range(max_retries):
                try:
                    # Use generate_content with stream=False for simpler handling
                    # Updated prompt for more detailed image captions
                    # Check for character name
                    char_name_widget = getattr(self.main_app, 'character_name_input', None)
                    char_name = char_name_widget.text().strip() if char_name_widget else ""
                    
                    name_clause = f" The main subject is named {char_name}. Describe {char_name}, including their" if char_name else " Describe the main subject(s), including"
                    
                    prompt = (
                        f"Analyze this image and provide a detailed description suitable for a video caption, "
                        f"covering the following aspects in approximately 80-100 words:\n"
                        f"1.  **Subject:**{name_clause} appearance, expression, clothing, and posture.\n"
                        f"2.  **Scene:** Describe the environment, background, and setting.\n"
                        f"3.  **Visual Style:** Describe the overall visual style (e.g., realistic, illustration, photographic style, specific art style if applicable).\n"
                        f"4.  **Atmosphere:** Describe the mood or feeling conveyed (e.g., mysterious, joyful, tense, solemn, vibrant).\n"
                        f"Output only the description."
                    )
                    response = self.gemini_model.generate_content(
                        [prompt, img], # Pass the updated prompt and the image
                        generation_config=genai.types.GenerationConfig(
                            # Optional: Add safety settings or other parameters if needed
                            # candidate_count=1,
                            # max_output_tokens=100, # Limit caption length
                            # temperature=0.4 
                        ),
                        stream=False # Get the full response at once
                    )
                    # Resolve the response to get the text part
                    response.resolve() 
                    
                    if response.parts:
                         # Remove potential markdown and leading/trailing whitespace
                        caption = response.text.strip().replace('*', '') 
                        print(f"✅ Generated caption: '{caption}'")
                        return caption
                    else:
                        print(f"❓ Gemini response did not contain text for {os.path.basename(image_path)}.")
                        return None # No text part in response
                        
                except Exception as e:
                    print(f"⚠️ Attempt {attempt + 1} failed: {e}")
                    if attempt + 1 == max_retries:
                        print(f"❌ Max retries reached for {os.path.basename(image_path)}. Giving up.")
                        return None
                    time.sleep(2 ** attempt) # Exponential backoff

            return None # Should not be reached if loop logic is correct

        except FileNotFoundError:
            print(f"❌ Image file not found: {image_path}")
            return None
        except Exception as e:
            # Catch other potential errors during image loading or API call
            print(f"❌ Error generating Gemini caption for {image_path}: {e}")
            # Consider more specific error handling based on potential Gemini API errors
            # if "API key not valid" in str(e): # Example specific error check
            #     self._show_api_key_error_message() # A helper to show QMessageBox
            #     self.gemini_model = None # Reset model state if key is invalid
            return None

    def generate_gemini_video_description(self, video_path, max_retries=3):
        """Generates a description for the given video file using the Gemini API."""
        if not self.gemini_model and not self._configure_gemini():
            return None # Configuration failed or API key missing

        print(f"⏳ Uploading video {os.path.basename(video_path)} for Gemini analysis...")
        video_file = None
        try:
            # Upload the video file
            video_file = genai.upload_file(path=video_path)
            print(f"   File uploaded: {video_file.name}, URI: {video_file.uri}")

            # Wait for the file to be processed and active
            while video_file.state.name == "PROCESSING":
                print("   Waiting for video processing...")
                time.sleep(5) # Check every 5 seconds
                video_file = genai.get_file(video_file.name)

            if video_file.state.name == "FAILED":
                print(f"❌ Video processing failed for {video_path}: {video_file.state}")
                return None
            elif video_file.state.name != "ACTIVE":
                print(f"❌ Video is not active after processing: {video_file.state.name}")
                return None
                
            print(f"✅ Video processed. Generating description for {os.path.basename(video_path)}...")
                
            # --- Generate Content using the uploaded video --- 
            # Updated prompt for more detailed video descriptions
            # Check for character name
            char_name_widget = getattr(self.main_app, 'character_name_input', None)
            char_name = char_name_widget.text().strip() if char_name_widget else ""
            
            name_clause = f" The main subject is named {char_name}. Describe {char_name}, including their" if char_name else " Describe the main subject(s), including"
            action_subject = char_name if char_name else "the subject(s)"
            
            prompt = (
                f"Analyze this video clip and provide a detailed description covering the following aspects "
                f"in approximately 80-100 words:\n"
                f"1.  **Subject:**{name_clause} appearance, expression, clothing, and posture.\n"
                f"2.  **Scene:** Describe the environment, background, and setting.\n"
                f"3.  **Action/Motion:** Describe the key actions or movements performed by {action_subject} and any significant camera movement (e.g., push in, pull out, pan, follow, orbit). Use simple, direct verbs.\n"
                f"4.  **Visual Style:** Describe the overall visual style (e.g., realistic, animated, cinematic, film grain, specific art style if applicable).\n"
                f"5.  **Atmosphere:** Describe the mood or feeling conveyed (e.g., mysterious, joyful, tense, solemn, vibrant).\n"
                f"Output only the description."
            )
            
            # Simple retry mechanism for generation
            for attempt in range(max_retries):
                try:
                    response = self.gemini_model.generate_content(
                        [prompt, video_file], # Pass the prompt and the file object
                        generation_config=genai.types.GenerationConfig(
                            # temperature=0.4 
                        ),
                        request_options={'timeout': 600} # Increased timeout for video
                    )
                    response.resolve()
                    
                    if response.parts:
                        description = response.text.strip().replace('*', '')
                        print(f"✅ Generated video description: '{description}'")
                        return description
                    else:
                        print(f"❓ Gemini response did not contain text for video {os.path.basename(video_path)}.")
                        return None # No text part
                        
                except exceptions.DeadlineExceeded:
                     print(f"⚠️ Attempt {attempt + 1} failed: Timeout during generation.")
                     if attempt + 1 == max_retries: return None
                     time.sleep(5)
                except Exception as e:
                    print(f"⚠️ Attempt {attempt + 1} failed during generation: {e}")
                    if attempt + 1 == max_retries: return None
                    time.sleep(2 ** attempt) # Exponential backoff
            
            return None # Should not be reached

        except Exception as e:
            print(f"❌ Error during video upload or description generation for {video_path}: {e}")
            return None
        finally:
            # --- IMPORTANT: Clean up the uploaded file --- 
            if video_file:
                try:
                    print(f"   Deleting uploaded file {video_file.name}...")
                    genai.delete_file(video_file.name)
                    print(f"   File {video_file.name} deleted.")
                except Exception as e:
                    print(f"⚠️ Failed to delete uploaded file {video_file.name}: {e}")

    @staticmethod
    def get_frame_count(video_path):
        try:
            probe = ffmpeg.probe(video_path)
            video_stream = next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
            return int(video_stream['nb_frames'])
        except Exception as e:
            print(f"❌ Error reading frame count from {video_path}: {e}")
            return -1

    def write_caption(self, output_file, caption_content=None):
        """
        Writes the provided caption_content into a .txt file 
        with the same base name as output_file.
        If caption_content is None, it uses the simple caption from the UI.
        Prepends the trigger word if provided.
        """
        caption = caption_content if caption_content is not None else getattr(self.main_app, 'simple_caption', '').strip()
        
        # Prepend trigger word if provided
        trigger_widget = getattr(self.main_app, 'trigger_word_input', None)
        if trigger_widget:
            trigger_word = trigger_widget.text().strip()
            if trigger_word and caption: # Only prepend if both trigger and caption exist
                caption = f"{trigger_word}, {caption}"

        if caption: # Only write if there's actually content
            base, _ = os.path.splitext(output_file)
            txt_file = base + ".txt"
            try:
                with open(txt_file, "w", encoding='utf-8') as f: # Specify encoding
                    f.write(caption)
                print(f"      ✅ Exported caption/description to {os.path.basename(txt_file)}")
            except Exception as e:
                print(f"      ❌ Error writing caption file {txt_file}: {e}")
        # else: # Optional: print if no caption was provided or generated
            # print(f"    ℹ️ No caption provided or generated for {output_file}.")

    def export_videos(self):
        """
        Exports selected (checked) videos based on their defined ranges and UI settings.

        Supported export modes (mutually exclusive checkboxes):
        - **Export All Ranges as Defined** – each range exported cropped if a crop
          rect is stored, otherwise exported uncropped.
        - **Export Cropped Ranges Only** – only ranges with a crop rect are exported.
        - **Export All Ranges Uncropped** – all ranges exported as full-frame clips.

        Additionally, "Export Image at Start Frame" and "Generate Gemini Caption" can
        be combined with any of the above modes.
        """
        # --- Read export-mode flags ---
        export_all_flag      = self.main_app.export_all_checkbox.isChecked()
        export_cropped_flag  = self.main_app.export_cropped_checkbox.isChecked()
        export_uncropped_flag = self.main_app.export_uncropped_checkbox.isChecked()
        export_image_flag    = self.main_app.export_image_checkbox.isChecked()
        generate_gemini_flag = self.main_app.gemini_caption_checkbox.isChecked()

        # At least one video-export mode or image export must be active.
        if not export_all_flag and not export_cropped_flag and not export_uncropped_flag and not export_image_flag:
            QMessageBox.warning(
                self.main_app, "Nothing to Export",
                "Please check at least one export option (Export All, Cropped, Uncropped, or Image)."
            )
            return

        # Validate Gemini API key upfront when captioning is requested.
        if generate_gemini_flag:
            if not self.main_app.gemini_api_key_input.text():
                QMessageBox.warning(
                    self.main_app, "API Key Missing",
                    "Please enter your Gemini API key to generate descriptions/captions."
                )
            elif not self.gemini_model:
                self._configure_gemini()

        # --- Define and create output folders ---
        base_folder = self.main_app.folder_path
        if not base_folder or not os.path.isdir(base_folder):
            QMessageBox.critical(self.main_app, "Error", "Invalid base folder path selected.")
            return

        output_folder_cropped  = os.path.normpath(os.path.join(base_folder, "cropped"))
        output_folder_uncropped = os.path.normpath(os.path.join(base_folder, "uncropped"))

        # "Export All" may write to both folders depending on each range's crop status.
        need_cropped_folder  = export_all_flag or export_cropped_flag
        need_uncropped_folder = export_all_flag or export_uncropped_flag
        if need_cropped_folder:
            os.makedirs(output_folder_cropped, exist_ok=True)
        if need_uncropped_folder:
            os.makedirs(output_folder_uncropped, exist_ok=True)

        # --- Collect checked videos and their ranges ---
        self.file_counter = 0
        items_to_export = []

        for i in range(self.main_app.video_list.count()):
            item = self.main_app.video_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            if i >= len(self.main_app.video_files):
                print(f"⚠️ Skipping checked item at index {i}: Mismatch with video_files data.")
                continue
            video_entry  = self.main_app.video_files[i]
            original_path = video_entry.get("original_path")
            display_name  = video_entry.get("display_name")
            if not original_path or not os.path.exists(original_path):
                print(f"⚠️ Skipping invalid video entry: {display_name} (Path: {original_path})")
                continue
            video_ranges = self.main_app.video_data.get(original_path, {}).get("ranges", [])
            if not video_ranges:
                print(f"ℹ️ No ranges defined for selected video: {display_name}. Skipping.")
                continue
            items_to_export.append({
                "original_path": original_path,
                "display_name":  display_name,
                "ranges":        video_ranges,
            })

        if not items_to_export:
            QMessageBox.information(
                self.main_app, "Nothing Selected",
                "Please select (check) at least one video file with defined ranges to export."
            )
            return

        print(f"--- Starting Export Process for {len(items_to_export)} video source(s) ---")

        # ------------------------------------------------------------------ #
        # Helper: build the FFmpeg scale filter params for the current UI     #
        # state (fixed-res mode takes precedence over aspect-ratio dropdown). #
        # ------------------------------------------------------------------ #
        def _resolve_scale_params(segment_w, segment_h):
            """
            Returns (scale_params, apply_scaling) based on Fixed Resolution mode
            or the aspect-ratio combo selection.

            :param segment_w: Width of the segment (original or cropped).
            :param segment_h: Height of the segment (original or cropped).
            :returns: Tuple of (list[str], bool).
            """
            fixed_w = getattr(self.main_app, 'fixed_export_width', None)
            fixed_h = getattr(self.main_app, 'fixed_export_height', None)
            if fixed_w is not None and fixed_h is not None:
                tw = max(2, (fixed_w // 2) * 2)
                th = max(2, (fixed_h // 2) * 2)
                print(f"      Scaling (Fixed Res): {tw}x{th}")
                return [str(tw), str(th)], True

            ratio_text  = self.main_app.aspect_ratio_combo.currentText()
            ratio_value = self.main_app.aspect_ratios.get(ratio_text)
            if isinstance(ratio_value, (float, int)):
                if ratio_value >= 1.0:
                    tw = segment_w
                    th = round(segment_w / ratio_value)
                else:
                    th = segment_h
                    tw = round(segment_h * ratio_value)
                tw = max(2, (tw // 2) * 2)
                th = max(2, (th // 2) * 2)
                if tw > 0 and th > 0:
                    print(f"      Scaling (Aspect Ratio {ratio_text}): {tw}x{th} "
                          f"based on segment {segment_w}x{segment_h}")
                    return [str(tw), str(th)], True
            return [], False

        # ------------------------------------------------------------------ #
        # Helper: run FFmpeg to export a video segment (cropped or full).     #
        # ------------------------------------------------------------------ #
        def _ffmpeg_export(src_path, out_path, ss, t, out_fps, crop=None, seg_w=0, seg_h=0):
            """
            Exports a video segment using FFmpeg.

            :param src_path: Absolute path to the source video file.
            :param out_path: Absolute path for the output file.
            :param ss: Start time in seconds.
            :param t: Duration in seconds.
            :param out_fps: Target frame-rate.
            :param crop: Optional (x, y, w, h) tuple; when provided the crop
                         filter is applied before scaling.
            :param seg_w: Width of the segment (post-crop if crop is given, else original).
            :param seg_h: Height of the segment (post-crop if crop is given, else original).
            :returns: True on success, False on failure.
            """
            try:
                stream = ffmpeg.input(src_path, ss=ss, t=t)
                stream = stream.filter('fps', fps=out_fps, round='up')
                if crop is not None:
                    x_c, y_c, w_c, h_c = crop
                    stream = stream.filter('crop', w_c, h_c, x_c, y_c)
                scale_params, apply_scaling = _resolve_scale_params(seg_w, seg_h)
                if apply_scaling and scale_params:
                    stream = stream.filter('scale', *scale_params)
                    stream = stream.filter('setsar', '1')
                stream = stream.output(
                    out_path, r=out_fps, vsync='cfr', map_metadata='-1',
                    **{'c:v': 'libx264', 'preset': 'medium', 'crf': 23}
                )
                stream.run(overwrite_output=True, quiet=True)
                return True
            except ffmpeg.Error as e:
                print(f"    ❌ FFmpeg error: {e.stderr.decode('utf8', errors='ignore')}")
                return False
            except Exception as e:
                print(f"    ❌ Unexpected error: {e}")
                return False

        # ------------------------------------------------------------------ #
        # Process each selected video source                                   #
        # ------------------------------------------------------------------ #
        for video_info in items_to_export:
            original_path    = video_info["original_path"]
            base_display_name = video_info["display_name"]
            ranges           = video_info["ranges"]
            print(f"Processing Source: {base_display_name} ({len(ranges)} ranges)")

            cap = None
            try:
                cap = cv2.VideoCapture(original_path)
                if not cap.isOpened():
                    print(f"❌ ERROR: Could not open video source {original_path}. Skipping.")
                    continue

                fps = cap.get(cv2.CAP_PROP_FPS)
                orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                total_source_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                output_fps = max(1, round(fps)) if fps > 0 else 30
                print(f"   Source FPS: {fps:.2f}, Output FPS: {output_fps}, "
                      f"Total Frames: {total_source_frames}")

                for range_data in ranges:
                    start_frame = range_data.get("start", 0)
                    end_frame   = range_data.get("end", 0)
                    crop_tuple  = range_data.get("crop")        # May be None
                    range_index = range_data.get("index", "X")  # For filename
                    print(f"  Processing Range {range_index} [{start_frame}-{end_frame}], "
                          f"Crop defined: {crop_tuple is not None}")

                    # --- Validate range ---
                    if start_frame < 0 or start_frame >= total_source_frames:
                        print(f"    ⚠️ Skipping range: start ({start_frame}) out of bounds.")
                        continue
                    if end_frame <= start_frame:
                        print(f"    ⚠️ Skipping range: end ({end_frame}) ≤ start ({start_frame}).")
                        continue
                    end_frame = min(end_frame, total_source_frames)
                    if end_frame <= start_frame:
                        print(f"    ⚠️ Skipping range: end ({end_frame}) ≤ start after clamping.")
                        continue

                    duration_frames = end_frame - start_frame
                    ss = start_frame / fps if fps > 0 else 0
                    t  = duration_frames / fps if fps > 0 else 0

                    # --- Build base output filename ---
                    prefix = getattr(self.main_app, 'export_prefix', '').strip()
                    if prefix:
                        self.file_counter += 1
                        base_output_name = f"{prefix}_{self.file_counter:05d}_range{range_index}"
                    else:
                        base_name_no_ext, _ = os.path.splitext(base_display_name)
                        base_output_name = f"{base_name_no_ext}_range{range_index}"

                    _, ext = os.path.splitext(original_path)
                    image_paths_for_gemini = []
                    video_path_for_gemini  = None

                    # -------------------------------------------------------- #
                    # 1. IMAGE EXPORT (start frame)                             #
                    # -------------------------------------------------------- #
                    if export_image_flag:
                        print(f"    Attempting image export for frame {start_frame}...")
                        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                        ret_img, frame = cap.read()
                        if ret_img and frame is not None:

                            # Determine whether to apply crop for the image in "Export All" mode.
                            do_crop_image = (
                                (export_all_flag and crop_tuple is not None) or
                                (export_cropped_flag and crop_tuple is not None)
                            )
                            do_uncrop_image = (
                                (export_all_flag and crop_tuple is None) or
                                export_uncropped_flag
                            )

                            if do_crop_image:
                                x, y, w, h = crop_tuple
                                if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > orig_w or y+h > orig_h:
                                    print(f"      ⚠️ Invalid crop for image export in range {range_index}")
                                else:
                                    cropped_frame = frame[y:y+h, x:x+w]
                                    if cropped_frame.size > 0:
                                        img_name = f"{base_output_name}_cropped.png"
                                        img_path = os.path.normpath(
                                            os.path.join(output_folder_cropped, img_name))
                                        try:
                                            cv2.imwrite(img_path, cropped_frame)
                                            print(f"      🖼️ Exported Cropped Image: {os.path.basename(img_path)}")
                                            if generate_gemini_flag:
                                                image_paths_for_gemini.append(img_path)
                                            else:
                                                self.write_caption(img_path)
                                        except Exception as e:
                                            print(f"      ❌ Error writing cropped image: {e}")
                                    else:
                                        print(f"      ⚠️ Empty crop frame for image in range {range_index}")

                            if do_uncrop_image:
                                img_name = f"{base_output_name}.png"
                                img_path = os.path.normpath(
                                    os.path.join(output_folder_uncropped, img_name))
                                try:
                                    cv2.imwrite(img_path, frame)
                                    print(f"      🖼️ Exported Uncropped Image: {os.path.basename(img_path)}")
                                    if generate_gemini_flag and img_path not in image_paths_for_gemini:
                                        image_paths_for_gemini.append(img_path)
                                    elif not generate_gemini_flag:
                                        self.write_caption(img_path)
                                except Exception as e:
                                    print(f"      ❌ Error writing uncropped image: {e}")
                        else:
                            print(f"    ⚠️ Could not read frame {start_frame} for image export.")

                    # -------------------------------------------------------- #
                    # 2. VIDEO EXPORT — "Export All" mode                       #
                    # -------------------------------------------------------- #
                    if export_all_flag:
                        if crop_tuple is not None:
                            # Range has a crop rect → export as cropped clip.
                            x_c, y_c, w_c, h_c = crop_tuple
                            if x_c < 0 or y_c < 0 or w_c <= 0 or h_c <= 0 \
                                    or x_c + w_c > orig_w or y_c + h_c > orig_h:
                                print(f"    ⚠️ Invalid crop dimensions {crop_tuple} for range "
                                      f"{range_index}. Skipping cropped export.")
                            else:
                                out_name = f"{base_output_name}_cropped{ext}"
                                out_path = os.path.normpath(
                                    os.path.join(output_folder_cropped, out_name))
                                print(f"    🎬 [Export All] Exporting Cropped Video: {out_name}...")
                                if _ffmpeg_export(
                                    original_path, out_path, ss, t, output_fps,
                                    crop=crop_tuple, seg_w=w_c, seg_h=h_c
                                ):
                                    print(f"      ✅ Exported Cropped Video: {os.path.basename(out_path)}")
                                    video_path_for_gemini = out_path
                                    if not generate_gemini_flag:
                                        self.write_caption(out_path)
                        else:
                            # Range has no crop rect → export as full-frame clip.
                            out_name = f"{base_output_name}{ext}"
                            out_path = os.path.normpath(
                                os.path.join(output_folder_uncropped, out_name))
                            print(f"    🎬 [Export All] Exporting Uncropped Video: {out_name}...")
                            if _ffmpeg_export(
                                original_path, out_path, ss, t, output_fps,
                                crop=None, seg_w=orig_w, seg_h=orig_h
                            ):
                                print(f"      ✅ Exported Uncropped Video: {os.path.basename(out_path)}")
                                video_path_for_gemini = out_path
                                if not generate_gemini_flag:
                                    self.write_caption(out_path)

                    # -------------------------------------------------------- #
                    # 3. VIDEO EXPORT — "Export Cropped Only" mode              #
                    # -------------------------------------------------------- #
                    if export_cropped_flag and crop_tuple is not None:
                        x_c, y_c, w_c, h_c = crop_tuple
                        if x_c < 0 or y_c < 0 or w_c <= 0 or h_c <= 0 \
                                or x_c + w_c > orig_w or y_c + h_c > orig_h:
                            print(f"    ⚠️ Invalid crop dimensions {crop_tuple} for range "
                                  f"{range_index}. Skipping cropped video export.")
                        else:
                            out_name = f"{base_output_name}_cropped{ext}"
                            out_path = os.path.normpath(
                                os.path.join(output_folder_cropped, out_name))
                            print(f"    🎬 Exporting Cropped Video: {out_name}...")
                            if _ffmpeg_export(
                                original_path, out_path, ss, t, output_fps,
                                crop=crop_tuple, seg_w=w_c, seg_h=h_c
                            ):
                                print(f"      ✅ Exported Cropped Video: {os.path.basename(out_path)}")
                                video_path_for_gemini = out_path
                                if not generate_gemini_flag:
                                    self.write_caption(out_path)

                    # -------------------------------------------------------- #
                    # 4. VIDEO EXPORT — "Export All Uncropped" mode             #
                    # -------------------------------------------------------- #
                    if export_uncropped_flag:
                        out_name = f"{base_output_name}{ext}"
                        out_path = os.path.normpath(
                            os.path.join(output_folder_uncropped, out_name))
                        print(f"    🎬 Exporting Uncropped Video: {out_name}...")
                        if _ffmpeg_export(
                            original_path, out_path, ss, t, output_fps,
                            crop=None, seg_w=orig_w, seg_h=orig_h
                        ):
                            print(f"      ✅ Exported Uncropped Video: {os.path.basename(out_path)}")
                            if video_path_for_gemini is None:
                                video_path_for_gemini = out_path
                            if not generate_gemini_flag:
                                self.write_caption(out_path)

                    # -------------------------------------------------------- #
                    # 5. Gemini captioning / description                        #
                    # -------------------------------------------------------- #
                    if generate_gemini_flag:
                        if video_path_for_gemini:
                            print(f"    🤖 Generating Gemini description for video: "
                                  f"{os.path.basename(video_path_for_gemini)}...")
                            description = self.generate_gemini_video_description(video_path_for_gemini)
                            if description:
                                self.write_caption(video_path_for_gemini, caption_content=description)
                            else:
                                print(f"      ⚠️ Gemini description failed. Writing simple caption.")
                                self.write_caption(video_path_for_gemini)
                        elif image_paths_for_gemini:
                            print(f"    🤖 Generating Gemini caption(s) for "
                                  f"{len(image_paths_for_gemini)} image(s)...")
                            for img_path in image_paths_for_gemini:
                                caption = self.generate_gemini_caption(img_path)
                                if caption:
                                    self.write_caption(img_path, caption_content=caption)
                                else:
                                    print(f"      ⚠️ Gemini caption failed for "
                                          f"{os.path.basename(img_path)}. Writing simple caption.")
                                    self.write_caption(img_path)

                    print(f"  Finished Range {range_index}.")

            except Exception as e:
                print(f"❌ UNEXPECTED ERROR processing source {base_display_name}: {e}")
                import traceback
                traceback.print_exc()
            finally:
                if cap and cap.isOpened():
                    cap.release()
                    print(f"   Released video source: {base_display_name}")

        print("--- Export Process Finished ---")
        QMessageBox.information(
            self.main_app, "Export Complete",
            "Finished exporting selected video ranges."
        )

    def export_first_frames_of_ranges_as_images(self):

        """
        Exports the first frame of each range for the selected (checked) videos.
        Applies range crop and fixed resolution if active.
        Generates a Gemini description for each image.
        """
        main_app = self.main_app
        output_folder_images = os.path.normpath(os.path.join(main_app.folder_path, "exported_images"))
        os.makedirs(output_folder_images, exist_ok=True)
        print(f"--- Starting export of first frames for ranges (images) to {output_folder_images} ---")

        # 1. Collect items to export (logic similar to export_videos)
        items_to_export = []
        for i in range(main_app.video_list.count()):
            item = main_app.video_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                if i >= len(main_app.video_files):
                    print(f"⚠️ Skipping checked item at index {i}: Mismatch with video_files data.")
                    continue
                video_entry = main_app.video_files[i]
                original_path = video_entry.get("original_path")
                display_name = video_entry.get("display_name") # Used for filename
                if not original_path or not os.path.exists(original_path):
                    print(f"⚠️ Skipping invalid video entry: {display_name} (Path: {original_path})")
                    continue
                video_ranges = main_app.video_data.get(original_path, {}).get("ranges", [])
                if not video_ranges:
                    print(f"ℹ️ No ranges defined for selected video: {display_name}. Skipping.")
                    continue
                items_to_export.append({
                    "original_path": original_path,
                    "display_name": display_name,
                    "ranges": video_ranges
                })

        if not items_to_export:
            QMessageBox.information(main_app, "Nothing to Export", "Please check at least one video with defined ranges.")
            return

        # 2. Process each video and its ranges
        total_images_exported = 0
        for video_info in items_to_export:
            original_path = video_info["original_path"]
            base_video_name, _ = os.path.splitext(video_info["display_name"])
            ranges = video_info["ranges"]
            print(f"Processing Source: {video_info['display_name']} ({len(ranges)} ranges)")

            cap = None
            try:
                cap = cv2.VideoCapture(original_path)
                if not cap.isOpened():
                    print(f"❌ ERROR: Could not open video source {original_path}. Skipping.")
                    continue

                for range_data in ranges:
                    start_frame = range_data.get("start", 0)
                    crop_tuple = range_data.get("crop") # Peut être None
                    range_idx_display = range_data.get("index", "X")
                    print(f"  Processing Range {range_idx_display}, Start Frame: {start_frame}, Crop: {crop_tuple is not None}")

                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                    ret, frame = cap.read()

                    if not ret or frame is None:
                        print(f"    ⚠️ Could not read frame {start_frame} for range {range_idx_display}. Skipping.")
                        continue
                    
                    img_to_process = frame.copy() # Work on a copy

                    # Apply range crop if it exists
                    if crop_tuple:
                        x, y, w, h = crop_tuple
                        current_h_img, current_w_img = img_to_process.shape[:2]
                        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > current_w_img or y + h > current_h_img:
                            print(f"    [DEBUG Exporter] Invalid crop {crop_tuple} for image of {current_w_img}x{current_h_img}. Crop ignored.")
                        else:
                            img_to_process = img_to_process[y:y+h, x:x+w]
                            print(f"    [DEBUG Exporter] Image cropped to {w}x{h} from ({x},{y}) for range {range_idx_display}")
                    
                    # Apply fixed resolution if active globally
                    fixed_w = getattr(main_app, 'fixed_export_width', None)
                    fixed_h = getattr(main_app, 'fixed_export_height', None)
                    if fixed_w and fixed_h:
                        img_to_process = cv2.resize(img_to_process, (fixed_w, fixed_h), interpolation=cv2.INTER_AREA)
                        print(f"    [DEBUG Exporter] Image resized to {fixed_w}x{fixed_h} for range {range_idx_display}")

                    # Build output filename
                    image_base_name = f"{base_video_name}_range{range_idx_display}_frame{start_frame}"
                    count = 0
                    temp_out_path = os.path.normpath(os.path.join(output_folder_images, f"{image_base_name}.png"))
                    while os.path.exists(temp_out_path):
                        count += 1
                        temp_out_path = os.path.normpath(os.path.join(output_folder_images, f"{image_base_name}_{count}.png"))
                    out_path_image = temp_out_path

                    try:
                        cv2.imwrite(out_path_image, img_to_process)
                        print(f"    ✅ Image exported: {os.path.basename(out_path_image)}")
                        total_images_exported += 1

                        # Generate Gemini description
                        if getattr(main_app, 'gemini_caption_checkbox', None) and main_app.gemini_caption_checkbox.isChecked():
                            if not self.gemini_model and not self._configure_gemini():
                                print("    ⚠️ Gemini not configured, cannot generate description.")
                                self.write_caption(out_path_image) # Write simple caption if Gemini config fails
                            else:
                                caption = self.generate_gemini_caption(out_path_image)
                                if caption:
                                    self.write_caption(out_path_image, caption_content=caption)
                                else:
                                    print(f"    ⚠️ Gemini description generation failed for {os.path.basename(out_path_image)}.")
                                    self.write_caption(out_path_image) # Fallback
                        else:
                            self.write_caption(out_path_image) # Write simple caption
                    except Exception as e_write:
                        print(f"    ❌ ERROR during image write {os.path.basename(out_path_image)}: {e_write}")

            except Exception as e_video_proc:
                print(f"❌ ERROR while processing video {video_info['display_name']}: {e_video_proc}")
            finally:
                if cap and cap.isOpened():
                    cap.release()
                    print(f"   Released video source: {video_info['display_name']}")
        
        print(f"--- Export of first frames complete. {total_images_exported} images exported. ---")
        QMessageBox.information(main_app, "Export Complete", f"{total_images_exported} images (first frames of ranges) have been exported.")

    def export_current_frame_as_image(self):
        main_app = self.main_app
        if not main_app.current_video_original_path:
            QMessageBox.warning(main_app, "No Video", "Please load a video first.")
            return

        current_frame_num = main_app.slider.value()
        original_path = main_app.current_video_original_path
        
        # Get base name for output
        video_entry = next((v for v in main_app.video_files if v["original_path"] == original_path), None)
        base_video_name = "image"
        if video_entry:
            base_video_name, _ = os.path.splitext(video_entry.get("display_name", "image"))

        output_folder_images = os.path.normpath(os.path.join(main_app.folder_path, "exported_images"))
        os.makedirs(output_folder_images, exist_ok=True)
        
        cap = None
        try:
            cap = cv2.VideoCapture(original_path)
            if not cap.isOpened():
                QMessageBox.critical(main_app, "Error", f"Could not open video source {original_path}.")
                return
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_num)
            ret, frame = cap.read()
            if not ret or frame is None:
                QMessageBox.critical(main_app, "Error", f"Could not read frame {current_frame_num}.")
                return
                
            img_to_process = frame.copy()
            
            range_idx_display = ""
            if main_app.current_selected_range_id:
                range_data = main_app.find_range_by_id(main_app.current_selected_range_id)
                if range_data and range_data.get("crop"):
                    x, y, w, h = range_data.get("crop")
                    current_h_img, current_w_img = img_to_process.shape[:2]
                    if not (x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > current_w_img or y + h > current_h_img):
                        img_to_process = img_to_process[y:y+h, x:x+w]
                if range_data:
                    range_idx_display = f"_range{range_data.get('index', 'X')}"
            
            # Apply fixed resolution globally
            fixed_w = getattr(main_app, 'fixed_export_width', None)
            fixed_h = getattr(main_app, 'fixed_export_height', None)
            if fixed_w and fixed_h:
                img_to_process = cv2.resize(img_to_process, (fixed_w, fixed_h), interpolation=cv2.INTER_AREA)
                
            # Build output filename
            image_base_name = f"{base_video_name}{range_idx_display}_frame{current_frame_num}"
            count = 0
            temp_out_path = os.path.normpath(os.path.join(output_folder_images, f"{image_base_name}.png"))
            while os.path.exists(temp_out_path):
                count += 1
                temp_out_path = os.path.normpath(os.path.join(output_folder_images, f"{image_base_name}_{count}.png"))
            out_path_image = temp_out_path
            
            cv2.imwrite(out_path_image, img_to_process)
            
            if getattr(main_app, 'gemini_caption_checkbox', None) and main_app.gemini_caption_checkbox.isChecked():
                if not self.gemini_model and not self._configure_gemini():
                    self.write_caption(out_path_image)
                else:
                    caption = self.generate_gemini_caption(out_path_image)
                    if caption:
                        self.write_caption(out_path_image, caption_content=caption)
                    else:
                        self.write_caption(out_path_image)
            else:
                self.write_caption(out_path_image)
                
            QMessageBox.information(main_app, "Export Complete", f"Current frame exported to {os.path.basename(out_path_image)}.")
            
        except Exception as e:
            QMessageBox.critical(main_app, "Error", f"Error exporting frame: {e}")
        finally:
            if cap and cap.isOpened(): cap.release()

    @staticmethod
    def qimage_to_cv(qimg):
        """Converts a QImage to an OpenCV image (numpy array)"""
        qimg = qimg.convertToFormat(4) # QImage.Format.Format_RGB32
        width = qimg.width()
        height = qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.array(ptr).reshape(height, width, 4)
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
