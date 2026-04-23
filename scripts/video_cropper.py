import sys, os, cv2, ffmpeg, json, numpy as np, send2trash, re, subprocess
import uuid  # Import UUID for unique range IDs
from scripts.custom_graphics_view import CustomGraphicsView
from PyQt6.QtWidgets import (
    QApplication, QWidget, QFileDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QListWidget, QSlider, QGraphicsPixmapItem, QLineEdit, QSpinBox, QDoubleSpinBox,
    QSizePolicy, QCheckBox, QListWidgetItem, QComboBox, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QSpacerItem, QTabWidget, QToolButton, QTextEdit,
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QIcon, QMouseEvent, QIntValidator, QKeySequence, QShortcut
from PyQt6.QtCore import Qt, QTimer, QRectF

# Custom scene (modified to use the new crop region)
from scripts.custom_graphics_scene import CustomGraphicsScene

# Import helper modules
from scripts.video_loader import VideoLoader
from scripts.video_editor import VideoEditor
from scripts.video_exporter import VideoExporter
from scripts.video_file_operator import VideoFileOperator
from scripts.caption_manager import (
    get_caption_path, load_caption, save_caption_atomic, copy_caption, caption_exists,
)

class VideoCropper(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sana's VidTrainPrep")
        self.setGeometry(100, 100, 900, 700) # Increased size slightly
        self.setWindowIcon(QIcon("icons/favicon.ico"))
        
        # Core state
        self.folder_path = ""
        self.video_files = []  # List of video dicts (display info)
        # NEW Data structure: Key is original_path, value is dict with ranges
        self.video_data = {}
        # Structure for a range: {"start": int, "end": int, "crop": tuple | None, "id": str}
        self.current_video_original_path = None # Track the source file path
        self.current_selected_range_id = None # Track the selected range in the list

        # Crop related (mostly unchanged, but context changes)
        self.current_rect = None
        self.cap = None
        self.frame_count = 0
        self.original_width = 0
        self.original_height = 0
        self.clip_aspect_ratio = 1.0 # This might be redundant with scene.aspect_ratio

        # New attributes for fixed resolution mode
        self.fixed_export_width = None
        self.fixed_export_height = None

        # Playback state (mostly unchanged)
        self.is_playing = False
        self.loop_enabled = False  # When True, playback loops (normal: whole video; range: within range bounds)

        # Export properties (mostly unchanged for now)
        self.export_uncropped = False
        self.export_image = False

        # Session file (will need update later)
        self.folder_sessions = {}
        self.session_file = "session_data.json"
        self.longest_edge = 1024  # Default; may be overwritten by loaded session data

        # Caption properties (unchanged)
        self.simple_caption = ""
        self.last_changed_sync = 'duration'

        # UI widgets (some changes)
        self.video_list = QListWidget() # Main list of videos/duplicates

        # Aspect ratio options with added WAN format
        self.aspect_ratios = {
            "Free-form": None, "1:1 (Square)": 1.0, "4:3 (Standard)": 4/3,
            "16:9 (Widescreen)": 16/9, "9:16 (Vertical Video)": 9/16,
            "2:1 (Cinematic)": 2.0, "3:2 (Classic Photo)": 3/2,
            "21:9 (Ultrawide)": 21/9
        }

        # Create helper modules and pass self.
        self.loader = VideoLoader(self)
        self.editor = VideoEditor(self)
        self.exporter = VideoExporter(self)

        # Load previous session.
        self.loader.load_session() # Will need modification later
        
        self.initUI()
        # Initialize frame label text after UI is built
        self.update_current_frame_label(0, 0, 0) # Show initial state
        
        # Auto-load the last opened folder if it still exists
        if self.folder_path and os.path.isdir(self.folder_path):
            self.loader.load_folder(self.folder_path)
    
    def initUI(self):
        main_layout = QHBoxLayout(self)
        
        # LEFT PANEL
        left_panel = QVBoxLayout()
        icon_label = QLabel(self)
        icon_pixmap = QPixmap("icons/folder_icon.png")
        icon_label.setPixmap(icon_pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_panel.addWidget(icon_label)
        
        top_buttons_layout = QHBoxLayout()
        self.folder_button = QPushButton("📂 Select Folder")
        self.folder_button.setToolTip("Select folder containing videos.")
        self.folder_button.clicked.connect(self.loader.load_folder)
        top_buttons_layout.addWidget(self.folder_button)
        
        self.convert_fps_button = QPushButton("🗜 Convert FPS")
        self.convert_fps_button.setToolTip("Convert all videos in the current folder to a target FPS.")
        self.convert_fps_button.clicked.connect(self.open_convert_fps_dialog)
        top_buttons_layout.addWidget(self.convert_fps_button)
        left_panel.addLayout(top_buttons_layout)
        
        # Main video list
        left_panel.addWidget(QLabel("Video Files:"))
        self.video_list.currentRowChanged.connect(self._on_video_selection_changed)
        # self.video_list.itemChanged.connect(self.loader.update_list_item_color) # Keep this
        left_panel.addWidget(self.video_list, 1) # More vertical space

        # Right-click context menu on the video list
        self.video_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_list.customContextMenuRequested.connect(self._show_video_list_context_menu)

        delete_buttons_layout = QHBoxLayout()
        self.delete_video_button = QPushButton("🗑️ Delete Video")
        self.delete_video_button.setToolTip("Deletes the selected video and moves it to recycle bin.")
        self.delete_video_button.clicked.connect(self.delete_current_video)
        delete_buttons_layout.addWidget(self.delete_video_button)

        self.delete_all_selected_button = QPushButton("🗑️ Delete All Selected")
        self.delete_all_selected_button.setToolTip(
            "<b>Delete All Selected Videos</b><br>"
            "Deletes every video whose checkbox is <b>checked</b> in the list above.<br>"
            "Each file is moved to the Recycle Bin."
        )
        self.delete_all_selected_button.clicked.connect(self.delete_all_selected_videos)
        delete_buttons_layout.addWidget(self.delete_all_selected_button)
        left_panel.addLayout(delete_buttons_layout)

        # --- Clip Range Management Panel ---
        range_group_box = QWidget() # Use a QWidget for layout within the panel
        range_layout = QVBoxLayout(range_group_box)
        range_layout.setContentsMargins(0, 5, 0, 0) # Adjust margins

        range_layout.addWidget(QLabel("Clip Ranges for Selected Video:"))
        self.clip_range_list = QListWidget()
        self.clip_range_list.itemClicked.connect(self.select_range) # New method needed
        range_layout.addWidget(self.clip_range_list, 1)

        # Range Start/End/Duration Inputs
        range_input_layout = QHBoxLayout()
        range_input_layout.addWidget(QLabel("Start Frame:"))
        self.start_frame_input = QLineEdit("0")
        self.start_frame_input.setValidator(QIntValidator(0, 9999999))
        self.start_frame_input.editingFinished.connect(self.update_start_frame_input)
        self.start_frame_input.returnPressed.connect(self.start_frame_input.clearFocus)
        range_input_layout.addWidget(self.start_frame_input)

        range_input_layout.addWidget(QLabel("End Frame:"))
        self.end_frame_input = QLineEdit("60")
        self.end_frame_input.setValidator(QIntValidator(1, 9999999))
        self.end_frame_input.editingFinished.connect(self.update_end_frame_input)
        self.end_frame_input.returnPressed.connect(self.end_frame_input.clearFocus)
        range_input_layout.addWidget(self.end_frame_input)

        range_input_layout.addWidget(QLabel("Duration (f):"))
        self.duration_input = QLineEdit("60")
        self.duration_input.setValidator(QIntValidator(1, 99999))
        self.duration_input.editingFinished.connect(self.update_range_duration_from_input)
        self.duration_input.returnPressed.connect(self.duration_input.clearFocus)
        range_input_layout.addWidget(self.duration_input)
        range_layout.addLayout(range_input_layout)

        # Add/Remove Buttons
        range_button_layout = QHBoxLayout()
        self.add_range_button = QPushButton("➕ Add Range") # Renamed button
        self.add_range_button.setToolTip("Add a new range starting at the current frame, using the specified duration (no crop).")
        self.add_range_button.clicked.connect(self.add_range_at_current_frame) # Changed connection
        range_button_layout.addWidget(self.add_range_button)

        self.remove_range_button = QPushButton("🗑️ Remove")
        self.remove_range_button.clicked.connect(self.remove_selected_range) # New method needed
        range_button_layout.addWidget(self.remove_range_button)
        self.play_range_button = QPushButton("▶️ Preview Range (Z/Y)") # New Button
        self.play_range_button.clicked.connect(self.toggle_play_selected_range) # New method
        QShortcut(QKeySequence("Z"), self).activated.connect(self.toggle_play_selected_range)
        QShortcut(QKeySequence("Y"), self).activated.connect(self.toggle_play_selected_range)
        
        # Global shortcuts
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self._shortcut_frame_forward)
        QShortcut(QKeySequence(Qt.KeyboardModifier.ShiftModifier | Qt.Key.Key_Right), self).activated.connect(self._shortcut_second_forward)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self._shortcut_frame_backward)
        QShortcut(QKeySequence(Qt.KeyboardModifier.ShiftModifier | Qt.Key.Key_Left), self).activated.connect(self._shortcut_second_backward)
        QShortcut(QKeySequence("X"), self).activated.connect(self._shortcut_next_video)
        QShortcut(QKeySequence("C"), self).activated.connect(self._shortcut_play_pause)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(self._shortcut_play_pause)
        QShortcut(QKeySequence("Q"), self).activated.connect(lambda: self.nudge_start_frame(-1) if self.current_selected_range_id else None)
        QShortcut(QKeySequence("W"), self).activated.connect(lambda: self.nudge_start_frame(1) if self.current_selected_range_id else None)
        QShortcut(QKeySequence("E"), self).activated.connect(lambda: self.nudge_end_frame(-1) if self.current_selected_range_id else None)
        QShortcut(QKeySequence("R"), self).activated.connect(lambda: self.nudge_end_frame(1) if self.current_selected_range_id else None)
        QShortcut(QKeySequence("A"), self).activated.connect(self.decrease_playback_speed)
        QShortcut(QKeySequence("S"), self).activated.connect(lambda: self.playback_speed_spinner.setValue(1.0))
        QShortcut(QKeySequence("D"), self).activated.connect(self.increase_playback_speed)
        
        range_button_layout.addWidget(self.play_range_button)
        range_layout.addLayout(range_button_layout)

        left_panel.addWidget(range_group_box) # Add the range management group

        # --- Other Controls (Moved slightly) ---


        self.export_all_checkbox = QCheckBox("Export All Ranges as Defined")
        self.export_all_checkbox.setToolTip(
            "Exports all ranges exactly once.\n"
            "• Ranges WITH a crop rect → exported cropped.\n"
            "• Ranges WITHOUT a crop rect → exported uncropped."
        )
        self.export_all_checkbox.setChecked(True)
        left_panel.addWidget(self.export_all_checkbox)

        self.export_cropped_checkbox = QCheckBox("Export Cropped Ranges Only")
        self.export_cropped_checkbox.setToolTip(
            "Exports only the ranges that have a crop region defined.\n"
            "Ranges without crop data are skipped."
        )
        self.export_cropped_checkbox.setChecked(False)
        left_panel.addWidget(self.export_cropped_checkbox)

        self.export_uncropped_checkbox = QCheckBox("Export All Ranges Uncropped")
        self.export_uncropped_checkbox.setToolTip(
            "Exports all defined ranges as full-frame (uncropped) clips,\n"
            "regardless of whether a crop region is defined."
        )
        self.export_uncropped_checkbox.setChecked(False)
        left_panel.addWidget(self.export_uncropped_checkbox)

        self.export_image_checkbox = QCheckBox("Export Image at Start Frame")
        self.export_image_checkbox.setChecked(False)
        left_panel.addWidget(self.export_image_checkbox)

        # Add spacer but replace it with toggle logic and widget container
        workflow_toggle_layout = QHBoxLayout()
        self.toggle_workflow_btn = QToolButton()
        self.toggle_workflow_btn.setArrowType(Qt.ArrowType.UpArrow)
        self.toggle_workflow_btn.setCheckable(True)
        self.toggle_workflow_btn.clicked.connect(self.toggle_workflow_labels)
        workflow_toggle_layout.addWidget(QLabel("Workflow & Attribution:"))
        workflow_toggle_layout.addWidget(self.toggle_workflow_btn)
        workflow_toggle_layout.addStretch()
        left_panel.addLayout(workflow_toggle_layout)

        self.workflow_container = QWidget()
        workflow_vlayout = QVBoxLayout(self.workflow_container)
        workflow_vlayout.setContentsMargins(0,0,0,0)

        # Add Description Label
        description_label = QLabel(
            "<b>Workflow:</b><br>"
            "1. Select Folder / Convert FPS.<br>"
            "2. Select video from list.<br>"
            "3. Navigate to desired start frame using slider.<br>"
            "4. Set clip Duration.<br>"
            "5. Draw crop rectangle to define & add a new range.<br>"
            "   (Or click 'Add Range Here' for no crop).<br>"
            "6. Select ranges, adjust Duration if needed.<br>"
            "7. Configure Export/Gemini options (API Key, Trigger, Name).<br>"
            "8. Check videos in list & Export."
        )
        description_label.setWordWrap(True)
        description_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        description_label.setStyleSheet("font-size: 11px; color: #B0B0B0; background-color: transparent; padding: 5px; border-top: 1px solid #555555;") # Add style
        workflow_vlayout.addWidget(description_label)

        # Add Attribution Label
        attribution_label = QLabel(
            "Based on <a href=\"https://github.com/lovisdotio/VidTrainPrep\" style=\"color: #88C0D0;\"><span style=\"color: #88C0D0;\">VidTrainPrep by lovisdotio</span></a> and <a href=\"https://github.com/Tr1dae/HunyClip\" style=\"color: #88C0D0;\"><span style=\"color: #88C0D0;\">HunyClip by Tr1dae</span></a>"
        )
        attribution_label.setOpenExternalLinks(True)
        attribution_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        attribution_label.setStyleSheet("font-size: 11px; color: #A0A0A0; background-color: transparent; margin-top: 5px;") # Increased font size
        workflow_vlayout.addWidget(attribution_label)
        
        left_panel.addWidget(self.workflow_container)

        main_layout.addLayout(left_panel, 1) # Left panel takes less space relative to right

        self.video_list.setStyleSheet("QListWidget::item:selected { background-color: #3A4F7A; }")
        self.clip_range_list.setStyleSheet("QListWidget::item:selected { background-color: #5A6F9A; }") # Different selection color
        
        # RIGHT PANEL
        right_panel = QVBoxLayout()
        keybindings_label = QLabel("⬅️/➡️: Prev./Next Frame • <b>Shift+</b>⬅️/➡️: Prev/Next Second • <b>Z/Y</b>: Preview Range • <b>X</b>: Next Video • <b>C/Space</b>: ▶️/⏸️ • <b>A/S/D</b>: Playback Speed • <b>Q/W</b>: Nudge Start Frame • <b>E/R</b>: Nudge End Frame • Drag on Canvas: Create Crop ")
        keybindings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        keybindings_label.setStyleSheet("font-size: 11px; color: #ECEFF4;") # Smaller font
        right_panel.addWidget(keybindings_label)
        
        aspect_ratio_layout = QHBoxLayout()
        aspect_ratio_layout.addWidget(QLabel("Aspect Ratio:"))
        self.aspect_ratio_combo = QComboBox()
        for ratio_name in self.aspect_ratios.keys():
            self.aspect_ratio_combo.addItem(ratio_name)
        self.aspect_ratio_combo.currentTextChanged.connect(self.set_aspect_ratio)
        aspect_ratio_layout.addWidget(self.aspect_ratio_combo)
        
        right_panel.addLayout(aspect_ratio_layout)
        
        self.graphics_view = CustomGraphicsView()
        self.graphics_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.graphics_view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.graphics_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scene = CustomGraphicsScene(self)
        self.graphics_view.setScene(self.scene)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)
        self.graphics_view.setMouseTracking(True)
        right_panel.addWidget(self.graphics_view, 1)
        
        # --- Resolution and Aspect Ratio Controls ---
        resolution_aspect_group = QWidget()
        resolution_aspect_layout = QFormLayout(resolution_aspect_group)
        resolution_aspect_layout.setContentsMargins(0,5,0,5)

        # Connect aspect ratio combo here, as it's part of this group
        current_aspect_ratio_layout = QHBoxLayout()
        current_aspect_ratio_layout.addWidget(QLabel("Aspect Ratio:"))
        # self.aspect_ratio_combo is already initialized and items added.
        current_aspect_ratio_layout.addWidget(self.aspect_ratio_combo)
        
        
        # Fixed Resolution Mode UI Elements
        custom_ar_layout = QHBoxLayout()
        fixed_res_label = QLabel("<b>Custom Aspect Ratio:</b>")
        self.fixed_res_status_label = QLabel("Custom Aspect Ratio: Deactivated")
        custom_ar_layout.addWidget(fixed_res_label)
        custom_ar_layout.addWidget(self.fixed_res_status_label)
        resolution_aspect_layout.addRow(custom_ar_layout)

        fixed_res_inputs_layout = QHBoxLayout()
        self.fixed_width_input = QLineEdit()
        self.fixed_width_input.setPlaceholderText("Width")
        self.fixed_width_input.setValidator(QIntValidator(1, 7680, self))
        self.fixed_width_input.returnPressed.connect(self.fixed_width_input.clearFocus)
        fixed_res_inputs_layout.addWidget(self.fixed_width_input)
        fixed_res_inputs_layout.addWidget(QLabel("x"))
        self.fixed_height_input = QLineEdit()
        self.fixed_height_input.setPlaceholderText("Height")
        self.fixed_height_input.setValidator(QIntValidator(1, 7680, self))
        self.fixed_height_input.returnPressed.connect(self.fixed_height_input.clearFocus)
        fixed_res_inputs_layout.addWidget(self.fixed_height_input)

        self.apply_fixed_res_button = QPushButton("✔️ Apply")
        fixed_res_inputs_layout.addWidget(self.apply_fixed_res_button)
        self.clear_fixed_res_button = QPushButton("🗑️ Clear")
        fixed_res_inputs_layout.addWidget(self.clear_fixed_res_button)
        resolution_aspect_layout.addRow(fixed_res_inputs_layout)
        
        

        self.apply_fixed_res_button.clicked.connect(lambda: self.toggle_fixed_resolution_mode(True))
        self.clear_fixed_res_button.clicked.connect(lambda: self.toggle_fixed_resolution_mode(False))

        # --- Current Crop Details ---
        current_crop_group = QWidget()
        current_crop_layout = QFormLayout(current_crop_group)
        current_crop_layout.setContentsMargins(0, 5, 0, 0)

        crop_xy_layout = QHBoxLayout()
        self.crop_x_input = QLineEdit()
        self.crop_x_input.setPlaceholderText("0")
        self.crop_x_input.setToolTip("X coordinate of the crop (Top-Left corner of the video is 0,0)")
        self.crop_x_input.setValidator(QIntValidator(0, 7680, self))
        self.crop_y_input = QLineEdit()
        self.crop_y_input.setPlaceholderText("0")
        self.crop_y_input.setToolTip("Y coordinate of the crop (Top-Left corner of the video is 0,0)")
        self.crop_y_input.setValidator(QIntValidator(0, 7680, self))
        crop_xy_layout.addWidget(QLabel("X:"))
        crop_xy_layout.addWidget(self.crop_x_input)
        crop_xy_layout.addWidget(QLabel("Y:"))
        crop_xy_layout.addWidget(self.crop_y_input)


        self.crop_w_input = QLineEdit()
        self.crop_w_input.setPlaceholderText("Width")
        self.crop_w_input.setToolTip("Width of the crop area in original pixels")
        self.crop_w_input.setValidator(QIntValidator(2, 7680, self))
        self.crop_h_input = QLineEdit()
        self.crop_h_input.setPlaceholderText("Height")
        self.crop_h_input.setToolTip("Height of the crop area in original pixels")
        self.crop_h_input.setValidator(QIntValidator(2, 7680, self))
        crop_xy_layout.addWidget(QLabel("W:"))
        crop_xy_layout.addWidget(self.crop_w_input)
        crop_xy_layout.addWidget(QLabel("H:"))
        crop_xy_layout.addWidget(self.crop_h_input)
        current_crop_layout.addRow(crop_xy_layout)

        self.apply_manual_crop_button = QPushButton("🔄️ Update Crop")
        self.apply_manual_crop_button.setToolTip("Apply the above coordinates and size to the current crop. Pressing enter in the textboxes should also apply the crop, but this button has been added just in case things don't work out as expected.")
        self.apply_manual_crop_button.clicked.connect(self.apply_manual_crop)

        self.clear_crop_button = QPushButton("🗑️ Clear Crop")
        self.clear_crop_button.setToolTip("Clear the crop region for the currently selected range.")
        self.clear_crop_button.clicked.connect(self.clear_current_range_crop)

        crop_action_row = QHBoxLayout()
        crop_action_row.addWidget(self.apply_manual_crop_button)
        crop_action_row.addWidget(self.clear_crop_button)
        current_crop_layout.addRow(crop_action_row)
        
        # Connect enter key on inputs — apply crop then clear focus so global shortcuts work
        self.crop_x_input.returnPressed.connect(self.apply_manual_crop)
        self.crop_y_input.returnPressed.connect(self.apply_manual_crop)
        self.crop_w_input.returnPressed.connect(self.apply_manual_crop)
        self.crop_h_input.returnPressed.connect(self.apply_manual_crop)
        self.crop_x_input.returnPressed.connect(self.crop_x_input.clearFocus)
        self.crop_y_input.returnPressed.connect(self.crop_y_input.clearFocus)
        self.crop_w_input.returnPressed.connect(self.crop_w_input.clearFocus)
        self.crop_h_input.returnPressed.connect(self.crop_h_input.clearFocus)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.sliderMoved.connect(self.editor.scrub_video)
        self.slider.valueChanged.connect(self.editor.scrub_video)
        right_panel.addWidget(self.slider)

        clip_length_layout = QHBoxLayout()
        self.clip_length_label = QLabel("Clip Length: 0 frames | Video Length: 0 frames")
        clip_length_layout.addWidget(self.clip_length_label)
        
        clip_length_layout.addStretch()
        
        clip_length_layout.addWidget(QLabel("Speed:"))
        self.playback_speed_spinner = QDoubleSpinBox()
        self.playback_speed_spinner.setMinimum(0.1)
        self.playback_speed_spinner.setSingleStep(0.25)
        self.playback_speed_spinner.setValue(1.0)
        self.playback_speed_spinner.setFixedWidth(90)
        #self.playback_speed_spinner.setStyleSheet("padding-right: 20px;") # Ensure space for buttons
        self.playback_speed_spinner.valueChanged.connect(self.update_playback_speed)
        clip_length_layout.addWidget(self.playback_speed_spinner)
        
        self.reset_speed_button = QPushButton("1️⃣")
        self.reset_speed_button.setToolTip("Reset Speed to 1.0")
        self.reset_speed_button.setFixedSize(24, 24)
        self.reset_speed_button.setStyleSheet("padding: 0px;")
        self.reset_speed_button.clicked.connect(lambda: self.playback_speed_spinner.setValue(1.0))
        clip_length_layout.addWidget(self.reset_speed_button)

        self.loop_button = QPushButton("🔁")
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(True)
        self.loop_button.setFixedSize(24, 24)
        self.loop_button.clicked.connect(self.toggle_loop)
        self.toggle_loop()
        clip_length_layout.addWidget(self.loop_button)
        
        right_panel.addLayout(clip_length_layout)
        
        self.thumbnail_label = QWidget(self)
        self.thumbnail_label.setWindowFlags(Qt.WindowType.ToolTip)
        self.thumbnail_label.setStyleSheet("background-color: black; border: 1px solid white;")
        self.thumbnail_label.hide()
        right_panel.addWidget(self.thumbnail_label)
        self.thumbnail_image_label = QLabel(self.thumbnail_label)
        self.thumbnail_image_label.setGeometry(0, 0, 160, 90)
        
        self.slider.installEventFilter(self)
        
        # --- NEW: Frame Control Layout ---
        frame_control_layout = QHBoxLayout()

        self.step_backward_button = QPushButton("< Frame")
        self.step_backward_button.setToolTip("Go to Previous Frame (Shortcut: Left Arrow)")
        self.step_backward_button.clicked.connect(self._step_frame_backward)
        self.step_backward_button.setFixedWidth(80)
        frame_control_layout.addWidget(self.step_backward_button)

        self.jump_start_frame_button = QPushButton("⏮️")
        self.jump_start_frame_button.setToolTip("Navigate frame slider to the current range's start frame")
        self.jump_start_frame_button.clicked.connect(self.jump_to_range_start)
        frame_control_layout.addWidget(self.jump_start_frame_button)

        self.update_start_f_button = QPushButton("📝 Start F.")
        self.update_start_f_button.setToolTip("Changes Start Frame of currently selected Range to current frame")
        self.update_start_f_button.clicked.connect(self.set_range_start_to_current)
        frame_control_layout.addWidget(self.update_start_f_button)

        self.current_frame_label = QLabel("Frame: - / -")
        self.current_frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current_frame_label.setStyleSheet("font-size: 12px; color: #C0C0C0;")
        frame_control_layout.addWidget(self.current_frame_label, 1)

        self.update_end_f_button = QPushButton("📝 End F.")
        self.update_end_f_button.setToolTip("Changes the End Frame of currently selected Range to current frame")
        self.update_end_f_button.clicked.connect(self.set_range_end_to_current)
        frame_control_layout.addWidget(self.update_end_f_button)

        self.jump_end_frame_button = QPushButton("⏭️")
        self.jump_end_frame_button.setToolTip("Navigate frame slider to the current range's end frame")
        self.jump_end_frame_button.clicked.connect(self.jump_to_range_end)
        frame_control_layout.addWidget(self.jump_end_frame_button)

        self.step_forward_button = QPushButton("Frame >")
        self.step_forward_button.setToolTip("Go to Next Frame (Shortcut: Right Arrow)")
        self.step_forward_button.clicked.connect(self._step_frame_forward)
        self.step_forward_button.setFixedWidth(80)
        frame_control_layout.addWidget(self.step_forward_button)

        frame_control_layout.addWidget(QLabel(" Go to: "))
        self.goto_frame_input = QLineEdit()
        self.goto_frame_input.setFixedWidth(50)
        self.goto_frame_input.setValidator(QIntValidator(0, 9999999))
        self.goto_frame_input.setToolTip("Enter frame number and press Enter")
        self.goto_frame_input.returnPressed.connect(self._goto_frame)
        self.goto_frame_input.returnPressed.connect(self.goto_frame_input.clearFocus)
        frame_control_layout.addWidget(self.goto_frame_input)

        right_panel.addLayout(frame_control_layout)

        # --- Reorganized Export Settings & Gemini Inputs (Vertical) into a Widget ---
        gemini_options_group = QWidget()
        gemini_options_layout = QFormLayout(gemini_options_group)
        gemini_options_layout.setContentsMargins(0, 10, 0, 5)

        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("Replace original name (Optional)")
        self.prefix_input.textChanged.connect(lambda text: setattr(self, "export_prefix", text))
        self.prefix_input.returnPressed.connect(self.prefix_input.clearFocus)
        gemini_options_layout.addRow("Filename Prefix:", self.prefix_input)

        self.trigger_word_input = QLineEdit()
        self.trigger_word_input.setPlaceholderText("Prepend to captions (Optional)")
        self.trigger_word_input.returnPressed.connect(self.trigger_word_input.clearFocus)
        gemini_options_layout.addRow("Trigger Word:", self.trigger_word_input)

        self.character_name_input = QLineEdit()
        self.character_name_input.setPlaceholderText("Subject name for Gemini (Optional)")
        self.character_name_input.returnPressed.connect(self.character_name_input.clearFocus)
        gemini_options_layout.addRow("Character Name:", self.character_name_input)
        
        self.gemini_api_key_input = QLineEdit()
        self.gemini_api_key_input.setPlaceholderText("Enter Gemini API Key Here")
        self.gemini_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key_input.returnPressed.connect(self.gemini_api_key_input.clearFocus)
        gemini_options_layout.addRow("Gemini API Key:", self.gemini_api_key_input)
        
        self.gemini_caption_checkbox = QCheckBox("Generate Gemini Caption/Description")
        self.gemini_caption_checkbox.setChecked(False)
        gemini_options_layout.addRow("", self.gemini_caption_checkbox)

        # Tabs Layout
        self.tabs = QTabWidget()
        
        self.minimize_tabs_btn = QToolButton()
        self.minimize_tabs_btn.setArrowType(Qt.ArrowType.UpArrow)
        self.minimize_tabs_btn.setCheckable(True)
        self.minimize_tabs_btn.setToolTip("Toggle Tabs Visibility")
        self.minimize_tabs_btn.clicked.connect(self.toggle_tabs_visibility)
        self.tabs.setCornerWidget(self.minimize_tabs_btn)
        
        # Tab 1: Crop
        crop_tab = QWidget()
        crop_layout = QVBoxLayout(crop_tab)
        
        # Add Current Crop Details (New layout container)
        crop_details_box = QWidget()
        crop_details_box_layout = QVBoxLayout(crop_details_box)
        crop_details_box_layout.addWidget(QLabel("<b>Current Crop</b>"))
        crop_details_box_layout.addWidget(current_crop_group)
        crop_details_box_layout.setContentsMargins(0,0,0,0)

        crop_layout.addWidget(resolution_aspect_group)
        crop_layout.addWidget(crop_details_box)
        crop_layout.addStretch(1)
        self.tabs.addTab(crop_tab, "Crop")
        
        # ── Tab 2: Video Editing ─────────────────────────────────────────────
        video_editing_tab = QWidget()
        video_editing_layout = QVBoxLayout(video_editing_tab)
        video_editing_layout.setContentsMargins(8, 8, 8, 8)
        video_editing_layout.setSpacing(6)

        # ── TRIM SECTION ──────────────────────────────────────────────────
        trim_header_layout = QHBoxLayout()
        trim_section_label = QLabel("<b>── Trim ──</b>")
        trim_section_label.setToolTip(
            "<b>Trim Section</b><br>"
            "Remove frames from the very beginning or the very end of the "
            "currently selected video.<br><br>"
            "<i>Trim Start</i>: discards everything <b>before</b> the chosen frame.<br>"
            "<i>Trim End</i>: discards everything <b>after</b> the chosen frame."
        )
        trim_header_layout.addWidget(trim_section_label)
        trim_header_layout.addStretch()

        self.trim_overwrite_checkbox = QCheckBox("Overwrite current video")
        self.trim_overwrite_checkbox.setChecked(True)
        self.trim_overwrite_checkbox.setToolTip(
            "<b>Overwrite current video</b><br>"
            "When <b>checked</b>: the original file is replaced with the trimmed "
            "version. The video is reloaded automatically afterwards.<br>"
            "When <b>unchecked</b>: a new file is created next to the original with "
            "a <i>_trimmed</i> suffix and added to the video list."
        )
        trim_header_layout.addWidget(self.trim_overwrite_checkbox)
        video_editing_layout.addLayout(trim_header_layout)

        trim_controls_layout = QHBoxLayout()
        self.trim_mode_combo = QComboBox()
        self.trim_mode_combo.addItems(["Trim Start", "Trim End"])
        self.trim_mode_combo.setToolTip(
            "<b>Trim Mode</b><br>"
            "<b>Trim Start</b>: removes all frames <b>before</b> the frame entered "
            "in the spinner. The chosen frame becomes the new first frame.<br>"
            "<b>Trim End</b>: removes all frames <b>after</b> the frame entered in "
            "the spinner. The chosen frame becomes the new last frame."
        )
        trim_controls_layout.addWidget(self.trim_mode_combo)

        trim_frame_label = QLabel("First/Last Good Frame:")
        trim_frame_label.setToolTip(
            "<b>Boundary Frame</b><br>"
            "For <i>Trim Start</i>: the <b>first good frame</b> \u2014 all frames "
            "<b>before</b> this number are removed.<br>"
            "For <i>Trim End</i>: the <b>last good frame</b> \u2014 all frames "
            "<b>after</b> this number are removed.<br><br>"
            "Range: 0 \u2013 (total frames \u2212 1)."
        )
        trim_frame_label.setFixedWidth(150)
        trim_frame_label.setStyleSheet("padding-left: 10px;")
        trim_controls_layout.addWidget(trim_frame_label)
        
        self.trim_frame_spinner = QSpinBox()
        self.trim_frame_spinner.setMinimum(0)
        self.trim_frame_spinner.setMaximum(0)   # Updated when a video is loaded
        self.trim_frame_spinner.setSingleStep(1)
        self.trim_frame_spinner.setToolTip(
            "<b>Boundary Frame</b><br>"
            "For <i>Trim Start</i>: the <b>first good frame</b> \u2014 all frames "
            "<b>before</b> this number are removed.<br>"
            "For <i>Trim End</i>: the <b>last good frame</b> \u2014 all frames "
            "<b>after</b> this number are removed.<br><br>"
            "Range: 0 \u2013 (total frames \u2212 1)."
        )
        trim_controls_layout.addWidget(self.trim_frame_spinner)

        self.trim_button = QPushButton("\u2702\ufe0f Trim")
        self.trim_button.setToolTip(
            "<b>Trim</b><br>"
            "Executes the trim operation using ffmpeg (stream-copy \u2014 no re-encode).<br>"
            "Result depends on the <i>Overwrite current video</i> checkbox above."
        )
        self.trim_button.clicked.connect(self._on_trim_clicked)
        trim_controls_layout.addWidget(self.trim_button)
        video_editing_layout.addLayout(trim_controls_layout)

        # ── SPLIT SECTION ─────────────────────────────────────────────────
        split_header_layout = QHBoxLayout()
        split_section_label = QLabel("<b>── Split Video ──</b>")
        split_section_label.setToolTip(
            "<b>Split Video Section</b><br>"
            "Divides the current video into multiple consecutive parts at the "
            "frame numbers you specify. Each part is saved as a separate file "
            "(e.g. <i>_part01</i>, <i>_part02</i>, \u2026)."
        )
        split_header_layout.addWidget(split_section_label)
        split_header_layout.addStretch()

        self.split_delete_original_checkbox = QCheckBox("Delete original video")
        self.split_delete_original_checkbox.setChecked(True)
        self.split_delete_original_checkbox.setToolTip(
            "<b>Delete original video</b><br>"
            "When <b>checked</b>: the original file is moved to the Recycle Bin "
            "after all parts are successfully exported.<br>"
            "When <b>unchecked</b>: the original file is kept alongside the parts."
        )
        split_header_layout.addWidget(self.split_delete_original_checkbox)
        video_editing_layout.addLayout(split_header_layout)

        split_controls_layout = QHBoxLayout()
        self.split_frames_input = QLineEdit()
        self.split_frames_input.setPlaceholderText(
            "First frames of each part, e.g.: 0, 150, 400  or  0 150 400"
        )
        self.split_frames_input.setToolTip(
            "<b>Split Frame Numbers</b><br>"
            "Enter the <b>first frame</b> of each output part, separated by "
            "commas or spaces.<br>"
            "Frame 0 is always the start of the first part (added automatically "
            "if omitted).<br><br>"
            "<b>Example:</b> entering <code>150 400</code> produces three parts:<br>"
            "&nbsp;&nbsp;\u2022 <i>_part01</i> \u2014 frames 0 \u2013 149<br>"
            "&nbsp;&nbsp;\u2022 <i>_part02</i> \u2014 frames 150 \u2013 399<br>"
            "&nbsp;&nbsp;\u2022 <i>_part03</i> \u2014 frames 400 \u2013 end"
        )
        self.split_frames_input.returnPressed.connect(self.split_frames_input.clearFocus)
        split_controls_layout.addWidget(self.split_frames_input, 1)

        self.split_button = QPushButton("\u2702\ufe0f Split")
        self.split_button.setToolTip(
            "<b>Split</b><br>"
            "Parses the frame numbers above and writes each part using ffmpeg "
            "(stream-copy \u2014 no re-encode).<br>"
            "Parts are added to the video list automatically."
        )
        self.split_button.clicked.connect(self._on_split_clicked)
        split_controls_layout.addWidget(self.split_button)
        video_editing_layout.addLayout(split_controls_layout)

        video_editing_layout.addStretch(1)
        self.tabs.addTab(video_editing_tab, "Video Editing")

        # Tab 3: Captioning
        caption_tab = QWidget()
        caption_layout = QVBoxLayout(caption_tab)
        caption_layout.setContentsMargins(8, 8, 8, 8)
        caption_layout.setSpacing(6)

        caption_label = QLabel("<b>Caption Text</b>")
        caption_label.setToolTip(
            "<b>Caption Editor</b><br>"
            "Displays and edits the <code>.txt</code> file that shares the same name "
            "as the selected video.<br>"
            "Changes are saved automatically ~0.8 s after you stop typing.<br>"
            "The file is created automatically if it does not exist yet.<br><br>"
            "Spellchecking is active (English&nbsp;US) — misspelled words are "
            "underlined in red."
        )
        caption_layout.addWidget(caption_label)

        self.caption_edit = SpellingTextEdit()
        self.caption_edit.setAcceptRichText(False)   # Plain text only
        self.caption_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.caption_edit.setPlaceholderText(
            "No caption file found for this video. Start typing to create one\u2026"
        )
        self.caption_edit.setToolTip(
            "<b>Caption Text</b><br>"
            "Edits the <code>.txt</code> caption file co-located with the current video.<br>"
            "Misspelled words are underlined in red (English&nbsp;US dictionary).<br>"
            "Right-click on a red-underlined word for corrections."
        )

        # Attach the English-US spell-check highlighter
        from scripts.spellcheck_highlighter import SpellCheckHighlighter
        self._spellcheck_highlighter = SpellCheckHighlighter(self.caption_edit.document())
        self.caption_edit.set_highlighter(self._spellcheck_highlighter)

        # Debounce timer — fires 800 ms after the last keystroke
        self._caption_save_timer = QTimer(self)
        self._caption_save_timer.setSingleShot(True)
        self._caption_save_timer.setInterval(800)
        self._caption_save_timer.timeout.connect(self._save_caption_now)
        self.caption_edit.textChanged.connect(self._on_caption_text_changed)

        caption_layout.addWidget(self.caption_edit, 1)

        # Bottom action buttons
        caption_btn_layout = QHBoxLayout()

        self.create_caption_copy_button = QPushButton("\U0001f4c4 Create Copy of the Caption File")
        self.create_caption_copy_button.setToolTip(
            "<b>Create Copy of the Caption File</b><br>"
            "Saves a duplicate of the current <code>.txt</code> caption file "
            "with a numbered suffix:<br>"
            "<code>&lt;name&gt;_01.txt</code>, <code>&lt;name&gt;_02.txt</code>, \u2026 "
            "(first free number)."
        )
        self.create_caption_copy_button.clicked.connect(self._create_caption_copy)
        caption_btn_layout.addWidget(self.create_caption_copy_button)

        self.open_caption_explorer_button = QPushButton("\U0001f4c2 Open Caption File in Windows Explorer")
        self.open_caption_explorer_button.setToolTip(
            "<b>Open Caption File in Windows Explorer</b><br>"
            "Opens the video\u2019s folder in Windows Explorer with the caption "
            "<code>.txt</code> file pre-selected."
        )
        self.open_caption_explorer_button.clicked.connect(self._open_caption_in_explorer)
        caption_btn_layout.addWidget(self.open_caption_explorer_button)

        caption_layout.addLayout(caption_btn_layout)
        self.tabs.addTab(caption_tab, "Captioning")

        # Tab 4: Gemini Captioning
        gemini_caption_tab = QWidget()
        gemini_caption_layout = QVBoxLayout(gemini_caption_tab)
        gemini_caption_layout.addWidget(gemini_options_group)
        gemini_caption_layout.addStretch(1)
        self.tabs.addTab(gemini_caption_tab, "Gemini Captioning")
        
        right_panel.addWidget(self.tabs)

        export_buttons_layout = QHBoxLayout()
        self.submit_button = QPushButton("🎞️ Export Selected Video(s)")
        self.submit_button.clicked.connect(self.exporter.export_videos)
        export_buttons_layout.addWidget(self.submit_button)
        
        self.export_range_start_frames_button = QPushButton("📚 Export 1st Frame of Ranges")
        self.export_range_start_frames_button.clicked.connect(self.trigger_export_range_start_frames)
        export_buttons_layout.addWidget(self.export_range_start_frames_button)

        self.export_current_frame_button = QPushButton("🖼️ Export Current Frame")
        self.export_current_frame_button.clicked.connect(self.exporter.export_current_frame_as_image)
        export_buttons_layout.addWidget(self.export_current_frame_button)
        
        right_panel.addLayout(export_buttons_layout)
        
        main_layout.addLayout(right_panel, 3)
    
    def set_aspect_ratio(self, ratio_name):
        ratio_value = self.aspect_ratios.get(ratio_name)
        # This is the primary way aspect ratio is set on the scene from UI (combobox)
        # If fixed mode is active, this combobox should be disabled.
        if self.fixed_export_width is None: # Only apply if not in fixed mode
            if ratio_name == "Original": # Special handling for "Original"
                if self.original_width > 0 and self.original_height > 0:
                    original_ratio = self.original_width / self.original_height
                    self.scene.set_aspect_ratio(original_ratio)
                else:
                    self.scene.set_aspect_ratio(None) # No video, no original ratio yet
            else:
                self.scene.set_aspect_ratio(ratio_value) # This can be float or None for Free-form
        # If fixed mode IS active, and this is somehow called, the scene's aspect ratio
        # should already be correctly set by toggle_fixed_resolution_mode.
        # No need for an else block to re-assert, as the combobox is disabled.

    def clear_crop_region_controller(self):
        """
        Remove all interactive crop region items from the scene.
        This ensures that when loading a new clip or creating a new crop region,
        only one crop region is visible.
        """
        from scripts.interactive_crop_region import InteractiveCropRegion
        # Collect all items that are instances of InteractiveCropRegion.
        items_to_remove = [item for item in self.scene.items() if isinstance(item, InteractiveCropRegion)]
        for item in items_to_remove:
            self.scene.removeItem(item)
        self.current_rect = None
        # Keep the scene's crop_item reference in sync so mouse events
        # are not routed to an item that no longer exists.
        self.scene.crop_item = None

    def crop_rect_updating(self, rect):
        """
        Callback invoked during crop region adjustment.
        You can use this to update a preview or status label.
        """
        print(f"Crop region updating: {rect}")

    def crop_rect_finalized(self, rect):
        """Callback invoked when the crop region is finalized.
           If a range is selected, updates its crop.
           If no range is selected, creates a new range at the current frame.
        """
        if not self.current_video_original_path:
            print("⚠️ Cannot process crop: No video loaded.")
            return

        pixmap = self.pixmap_item.pixmap()
        if pixmap is None or pixmap.width() == 0:
            print("⚠️ Cannot process crop: No pixmap.")
            return

        # --- Calculate Crop Data (relative to original video) ---
        print(f"[DEBUG crop_rect_finalized] Received rect from scene: x={rect.x():.2f}, y={rect.y():.2f}, w={rect.width():.2f}, h={rect.height():.2f}")
        print(f"[DEBUG crop_rect_finalized] VideoCropper original_width: {self.original_width}, original_height: {self.original_height}")
        print(f"[DEBUG crop_rect_finalized] Current pixmap_item.pixmap() dimensions: {pixmap.width()}x{pixmap.height()}")

        scale_w = self.original_width / pixmap.width() if pixmap.width() > 0 else 1.0
        scale_h = self.original_height / pixmap.height() if pixmap.height() > 0 else 1.0
        print(f"[DEBUG crop_rect_finalized] Calculated scale_w: {scale_w:.4f}, scale_h: {scale_h:.4f}")

        x = int(rect.x() * scale_w)
        y = int(rect.y() * scale_h)
        w = int(rect.width() * scale_w)
        h = int(rect.height() * scale_h)
        
        # Validate coordinates
        crop_tuple_before_validation = (x, y, w, h)
        print(f"[DEBUG crop_rect_finalized] Crop tuple before validation: {crop_tuple_before_validation}")

        if x<0 or y<0 or w<=0 or h<=0 or x+w > self.original_width or y+h > self.original_height:
             print(f"⚠️ Invalid crop coordinates calculated: ({x},{y},{w},{h}). Clamping/adjusting might be needed.")
             x = max(0, x)
             y = max(0, y)
             h = min(h, self.original_height - y)
             if w <= 0 or h <= 0:
                 print("   Crop invalid even after clamping. Discarding crop action.")
                 self.clear_crop_region_controller() # Clear invalid visual crop
                 return
                 
        # Snap dimensions to be divisible by 2.
        # If rounding w/h down would push the crop outside the video, adjust x/y
        # by +1 instead so the crop stays fully within bounds.
        if w % 2 != 0:
            if x + (w - 1) <= self.original_width:
                w -= 1  # round down
            else:
                x += 1  # shift origin instead
        if h % 2 != 0:
            if y + (h - 1) <= self.original_height:
                h -= 1  # round down
            else:
                y += 1  # shift origin instead
        if w < 2: w = 2
        if h < 2: h = 2

        crop_tuple = (x, y, w, h)
        print(f"[DEBUG crop_rect_finalized] Final crop_tuple for storage: {crop_tuple}")
        
        # Update Current Crop UI
        self.crop_x_input.setText(str(x))
        self.crop_y_input.setText(str(y))
        self.crop_w_input.setText(str(w))
        self.crop_h_input.setText(str(h))
        
        # --- Apply Crop to Selected Range OR Create New Range ---
        if self.current_selected_range_id:
            # --- Update Existing Selected Range --- 
            range_data = self.find_range_by_id(self.current_selected_range_id)
            if range_data:
                 range_data["crop"] = crop_tuple
                 print(f"Updated crop for range {self.current_selected_range_id}: {crop_tuple}")
                 # Reload visual crop to ensure consistency (handles aspect ratio enforcement)
                 self._load_range_crop(range_data)
            else:
                 print(f"⚠️ Could not find selected range {self.current_selected_range_id} to update crop.")
                 # Clear visual crop if data is inconsistent
                 self.clear_crop_region_controller()
        else:
            # --- Create New Range --- 
            print("No range selected. Creating new range from crop...")
            start_frame = self.slider.value() # Use the current slider position as start
            try:
                duration = int(self.duration_input.text())
                if duration <= 0:
                    print("⚠️ Duration must be positive. Using default of 60.")
                    duration = 60
                    self.duration_input.setText("60")
            except ValueError:
                print("⚠️ Invalid duration input. Using default of 60.")
                duration = 60
                self.duration_input.setText("60")
                
            end_frame = min(start_frame + duration, self.frame_count) # Calculate end, clamp to video length
            if end_frame <= start_frame: # Ensure duration is at least 1 frame after clamping
                print("⚠️ Calculated end frame is <= start frame. Adjusting end frame.")
                end_frame = start_frame + 1
                if end_frame > self.frame_count:
                    print("   Cannot add range starting at the very last frame.")
                    self.clear_crop_region_controller()
                    return

            print(f"Adding new range from crop: Start={start_frame}, End={end_frame}, Crop={crop_tuple}")
            self.add_new_range(start=start_frame, end=end_frame, crop=crop_tuple)
            # The visual crop rectangle is handled by the selection of the new range in add_new_range

    def check_current_video_item(self):
        # Might need rework depending on how "checked" state is used with ranges
        pass
        # for i in range(self.video_list.count()):
        #     item = self.video_list.item(i)
        #     # How to map item back to original_path consistently? Store path in item data?
        #     # item_path = item.data(Qt.ItemDataRole.UserRole) # Assuming we store path here
        #     # if item_path == self.current_video_original_path:
        #     #      if item.checkState() != Qt.CheckState.Checked:
        #     #         item.setCheckState(Qt.CheckState.Checked)
        #     #      break

    def toggle_tabs_visibility(self, checked):
        if checked:
            self.minimize_tabs_btn.setArrowType(Qt.ArrowType.DownArrow)
            for i in range(self.tabs.count()):
                self.tabs.widget(i).setVisible(False)
            self.tabs.setMaximumHeight(self.tabs.tabBar().height())
        else:
            self.minimize_tabs_btn.setArrowType(Qt.ArrowType.UpArrow)
            for i in range(self.tabs.count()):
                self.tabs.widget(i).setVisible(True)
            self.tabs.setMaximumHeight(16777215)
        # Re-layout and trigger frame redraw to fit available window space 
        if self.tabs.parentWidget() and self.tabs.parentWidget().layout():
            self.tabs.parentWidget().layout().invalidate()
        QTimer.singleShot(25, lambda: self.editor.update_frame_display(self.slider.value()) if getattr(self, 'frame_count', 0) > 0 else None)

    def toggle_workflow_labels(self, checked):
        if checked:
            self.toggle_workflow_btn.setArrowType(Qt.ArrowType.DownArrow)
            self.workflow_container.setVisible(False)
        else:
            self.toggle_workflow_btn.setArrowType(Qt.ArrowType.UpArrow)
            self.workflow_container.setVisible(True)

    def _on_video_selection_changed(self, row):
        """
        Slot connected to currentRowChanged on the video list.
        Triggers the full activation sequence for the selected video.
        """
        if row < 0:
            return
            
        item = self.video_list.item(row)
        if item:
            self._activate_video_item(item)

    def _on_video_item_clicked(self, item):
        """
        DEPRECATED: Use _on_video_selection_changed.
        Kept briefly for compatibility if needed, but redirects to activation logic.
        """
        self._activate_video_item(item)

    def _activate_video_item(self, item):
        """
        Core logic to load a video, start autoplay, and load its caption.
        """
        self.loader.load_video(item)
        # Autoplay after the video has loaded (frame count will be > 0 if load succeeded)
        if self.frame_count > 0 and self.slider.isEnabled():
            self.editor.toggle_play_forward()
        # Populate the Captioning tab with any existing .txt file for this video
        if self.current_video_original_path:
            self._load_caption_for_video(self.current_video_original_path)

    def _show_video_list_context_menu(self, pos):
        """
        Shows a right-click context menu for the video list with:
        - <b>Copy Path</b>: copies the absolute file path to the clipboard.
        - <b>Open in Windows Explorer</b>: opens the video's folder and selects the file.

        Args:
            pos (QPoint): The cursor position within the video list widget (local coords).
        """
        from PyQt6.QtWidgets import QMenu
        item = self.video_list.itemAt(pos)
        if not item:
            return  # No item under cursor — nothing to show

        idx = self.video_list.row(item)
        if idx < 0 or idx >= len(self.video_files):
            return

        video_path = self.video_files[idx].get("original_path", "")
        if not video_path:
            return

        menu = QMenu(self)
        menu.setMinimumWidth(250)

        copy_action = menu.addAction("📋 Copy Path")
        copy_action.setToolTip("Copy the absolute file path to the clipboard")

        explorer_action = menu.addAction("📂 Open in Windows Explorer")
        explorer_action.setToolTip("Open the containing folder and select this file")

        # Only show the caption action when the .txt file actually exists
        caption_ctx_action = None
        if caption_exists(video_path):
            caption_ctx_action = menu.addAction("\U0001f4dd Open Caption File in Windows Explorer")
            caption_ctx_action.setToolTip(
                "Open the video\u2019s folder in Windows Explorer with the caption "
                "<code>.txt</code> file pre-selected."
            )

        action = menu.exec(self.video_list.mapToGlobal(pos))

        if action == copy_action:
            QApplication.clipboard().setText(video_path)
            print(f"Copied to clipboard: {video_path}")
        elif action == explorer_action:
            # /select, highlights the specific file inside Explorer
            subprocess.Popen(['explorer', '/select,', os.path.normpath(video_path)])
        elif caption_ctx_action and action == caption_ctx_action:
            caption_path = get_caption_path(video_path)
            subprocess.Popen(['explorer', '/select,', os.path.normpath(caption_path)])

    def delete_all_selected_videos(self):
        """
        Deletes every video in the list whose checkbox is checked (Export Selected).
        Each file is moved to the Recycle Bin.  After deletion the selection moves
        to the item just before the first deleted item, mirroring the behaviour of
        the single-video delete.
        """
        # Collect (row, path) pairs for checked items, sorted descending by row
        # so we can remove from the list widget bottom-up without index drift.
        targets = []
        for i in range(self.video_list.count()):
            item = self.video_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                if i < len(self.video_files):
                    targets.append((i, self.video_files[i]["original_path"]))

        if not targets:
            QMessageBox.information(self, "Nothing to Delete",
                                    "No videos are checked. Tick the checkboxes next to the "
                                    "videos you want to delete first.")
            return

        # Remember the lowest row so we can land just above it afterwards
        first_deleted_row = targets[0][0]

        # Stop playback / release cap if the current video is among those being deleted
        current_paths = {os.path.normpath(p) for _, p in targets}
        if self.current_video_original_path and \
                os.path.normpath(self.current_video_original_path) in current_paths:
            self.editor.stop_playback()
            if self.cap:
                self.cap.release()
                self.cap = None
            self.current_video_original_path = None

        errors = []
        deleted_paths = set()

        # Delete bottom-up to keep row indices valid
        for row, path in sorted(targets, key=lambda t: t[0], reverse=True):
            try:
                send2trash.send2trash(path)
                deleted_paths.add(os.path.normpath(path))
                self.video_list.takeItem(row)
            except Exception as exc:
                errors.append(f"{os.path.basename(path)}: {exc}")

        # Clean up in-memory state
        self.video_files = [
            v for v in self.video_files
            if os.path.normpath(v["original_path"]) not in deleted_paths
        ]
        for p in list(self.video_data.keys()):
            if os.path.normpath(p) in deleted_paths:
                del self.video_data[p]

        if errors:
            QMessageBox.warning(self, "Partial Deletion",
                                "Some files could not be deleted:\n" + "\n".join(errors))

        # Select a neighbour and load it, or clear the viewer if the list is now empty
        if self.video_list.count() > 0:
            new_row = max(0, first_deleted_row - 1)
            self.video_list.setCurrentRow(new_row)
            self.loader.load_video(self.video_list.item(new_row))
        else:
            self.pixmap_item.setPixmap(QPixmap())
            self.clear_crop_region_controller()
            self.graphics_view.update()
            self.slider.setEnabled(False)
            self.slider.setValue(0)
            self.start_frame_input.setText("0")
            self.end_frame_input.setText("0")
            self.duration_input.setText("0")

        self.loader.save_session()

    def delete_current_video(self):
        if not self.current_video_original_path: return

        try:
            # Stop active playback and release the video handle to prevent
            # WinError 32 (file in use by another process) on deletion.
            self.editor.stop_playback()
            if self.cap:
                self.cap.release()
                self.cap = None

            send2trash.send2trash(self.current_video_original_path)

            for i in range(self.video_list.count()):
                item = self.video_list.item(i)
                if getattr(item, 'original_path', None) == self.current_video_original_path or item.text().startswith(os.path.basename(self.current_video_original_path)): 
                    row = self.video_list.row(item)
                    self.video_list.takeItem(row) # Automatically removes from UI
                    break
                    
            self.video_files = [v for v in self.video_files if v["original_path"] != self.current_video_original_path]
            if self.current_video_original_path in self.video_data:
                del self.video_data[self.current_video_original_path]

            self.current_video_original_path = None
            
            # Select the item just before the deleted one (index - 1), not always 0
            if self.video_list.count() > 0:
                new_row = max(0, row - 1)
                self.video_list.setCurrentRow(new_row)
                self.loader.load_video(self.video_list.item(new_row))
            else:
                self.pixmap_item.setPixmap(QPixmap())
                self.clear_crop_region_controller()
                self.graphics_view.update()
                self.slider.setEnabled(False)
                self.slider.setValue(0)
                self.start_frame_input.setText("0")
                self.end_frame_input.setText("0")
                self.duration_input.setText("0")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete video: {e}")

    def update_playback_speed(self):
        if self.editor.playback_timer.isActive():
            speed = self.playback_speed_spinner.value()
            interval = int((1000 / self.editor.current_fps) / speed) if self.editor.current_fps > 0 else int(33 / speed)
            self.editor.playback_timer.setInterval(interval)

    def decrease_playback_speed(self):
        current = self.playback_speed_spinner.value()
        step = self.playback_speed_spinner.singleStep()
        self.playback_speed_spinner.setValue(max(self.playback_speed_spinner.minimum(), current - step))

    def increase_playback_speed(self):
        current = self.playback_speed_spinner.value()
        step = self.playback_speed_spinner.singleStep()
        self.playback_speed_spinner.setValue(min(self.playback_speed_spinner.maximum(), current + step))

    def toggle_loop(self):
        """
        Toggles playback looping on or off.

        When looping is enabled:
        - Normal playback (C / Space) will loop from the last video frame back to frame 0.
        - Range preview (Z / Y) will loop from the range's end frame back to its start frame.

        The loop button appearance and tooltip are updated to reflect the current state.
        """
        self.loop_enabled = self.loop_button.isChecked()
        self._update_loop_button_style()

    def _update_loop_button_style(self):
        """
        Applies a visual style to the loop button that reflects whether looping is
        currently enabled (highlighted / accent colour) or disabled (plain / muted).
        Also updates the tooltip to clearly communicate the current state.
        """
        if self.loop_enabled:
            self.loop_button.setToolTip(
                "<b>Loop: ON</b><br>"
                "Playback will restart automatically when it reaches the end.<br>"
                "<i>Normal playback</i> loops the whole video.<br>"
                "<i>Range preview</i> loops within the selected range.<br>"
                "Click to turn looping <b>off</b>."
            )
            self.loop_button.setStyleSheet(
                "QPushButton {"
                "  padding: 0px;"
                "  background-color: #3A6EA5;"   # accent blue when ON
                "  border: 1px solid #5A9ED6;"
                "  border-radius: 3px;"
                "}"
                "QPushButton:hover {"
                "  background-color: #4A7EB5;"
                "}"
            )
        else:
            self.loop_button.setToolTip(
                "<b>Loop: OFF</b><br>"
                "Playback stops at the end of the video / range.<br>"
                "Click to turn looping <b>on</b>."
            )
            self.loop_button.setStyleSheet(
                "QPushButton {"
                "  padding: 0px;"
                "  background-color: transparent;"
                "  border: 1px solid #555555;"
                "  border-radius: 3px;"
                "}"
                "QPushButton:hover {"
                "  background-color: #3A3A3A;"
                "}"
            )

    def jump_to_range_start(self):
        if not self.current_selected_range_id: return
        try:
            start_frame = int(self.start_frame_input.text())
            if self.frame_count > 0:
                self.editor.update_frame_display(start_frame)
                self.slider.setValue(start_frame)
        except ValueError: pass

    def jump_to_range_end(self):
        if not self.current_selected_range_id: return
        try:
            end_frame = int(self.end_frame_input.text())
            if self.frame_count > 0:
                self.editor.update_frame_display(end_frame)
                self.slider.setValue(end_frame)
        except ValueError: pass

    def set_range_start_to_current(self):
        if not self.current_selected_range_id: return
        current_frame = self.slider.value()
        self.start_frame_input.setText(str(current_frame))
        self.update_start_frame_input()

    def set_range_end_to_current(self):
        if not self.current_selected_range_id: return
        current_frame = self.slider.value()
        self.end_frame_input.setText(str(current_frame))
        self.update_end_frame_input()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            # Delete selected range if range list has focus
            if self.clip_range_list.hasFocus() and self.current_selected_range_id:
                self.remove_selected_range()
                event.accept()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def _shortcut_frame_forward(self):
        if self.slider.isEnabled(): self.editor.step_frame(1)
        
    def _shortcut_second_forward(self):
        if self.slider.isEnabled(): self.editor.jump_frames(1.0)
        
    def _shortcut_frame_backward(self):
        if self.slider.isEnabled(): self.editor.step_frame(-1)
        
    def _shortcut_second_backward(self):
        if self.slider.isEnabled(): self.editor.jump_frames(-1.0)
        
    def _shortcut_next_video(self):
        self.editor.next_clip()
        
    def _shortcut_play_pause(self):
        if self.slider.isEnabled(): self.editor.toggle_play_forward()

    def nudge_start_frame(self, delta):
        if not self.current_selected_range_id: return
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if not range_data: return

        try:
            current_start = range_data.get("start", 0)
            current_end = range_data.get("end", 0)
            current_duration = current_end - current_start

            new_start = max(0, current_start + delta)

            # Calculate new end based on original duration, then clamp
            new_end = new_start + current_duration
            new_end = min(new_end, self.frame_count) # Clamp end to video length

            # Ensure start is still less than (clamped) end
            if new_start >= new_end:
                 print("Nudge start failed: Start frame reached or exceeded end frame.")
                 # Optionally revert or just do nothing
                 return

            # Update data structure
            range_data["start"] = new_start
            range_data["end"] = new_end # End also changes to maintain duration

            # Update UI Input Fields
            self.start_frame_input.setText(str(new_start))
            new_duration = new_end - new_start
            self.duration_input.setText(str(new_duration)) # Update duration display

            # Update list item text
            current_item = self.clip_range_list.currentItem()
            if current_item:
                self._update_list_item_text(current_item, range_data)

            # Update frame display and slider to the new start
            self.editor.update_frame_display(new_start)

            print(f"Nudged start for {self.current_selected_range_id}: New Range [{new_start}-{new_end}]")

        except ValueError: pass # Ignore if inputs are somehow invalid

    def nudge_end_frame(self, delta):
        # This function is simpler as it just changes duration
        if not self.current_selected_range_id: return
        try:
            # Get current duration from input
            current_duration = int(self.duration_input.text())
            new_duration = max(1, current_duration + delta) # Ensure duration is at least 1

            # Update the duration input
            self.duration_input.setText(str(new_duration))

            # Trigger the update logic (which clamps end frame etc.)
            self.update_range_duration_from_input()
            print(f"Nudged end for {self.current_selected_range_id}: New Duration {new_duration}")

        except ValueError: pass

    def eventFilter(self, source, event):
        if source is self.slider:
            if event.type() == QMouseEvent.Type.MouseButtonPress:
                pass
            elif event.type() == QMouseEvent.Type.HoverMove:
                self.editor.show_thumbnail(event) # show_thumbnail might need update?
            elif event.type() == QMouseEvent.Type.Leave:
                self.thumbnail_label.hide()
        return False

    # ── Caption file management ───────────────────────────────────────────────

    def _load_caption_for_video(self, video_path: str) -> None:
        """
        Populate the Captioning tab text editor with the content of the
        caption file co-located with ``video_path``.

        Signals are blocked while loading so that reading existing text from
        disk does not arm the auto-save debounce timer.

        Args:
            video_path (str): Absolute path to the currently selected video.
        """
        text = load_caption(video_path)
        # Block signals so the load does not trigger _on_caption_text_changed
        self.caption_edit.blockSignals(True)
        self.caption_edit.setPlainText(text)
        self.caption_edit.blockSignals(False)

    def _on_caption_text_changed(self) -> None:
        """
        Slot connected to ``QTextEdit.textChanged``.

        Restarts the single-shot debounce timer every time the user edits the
        caption.  The actual disk write happens in ``_save_caption_now`` once
        800 ms of inactivity have elapsed.
        """
        if self.current_video_original_path:
            self._caption_save_timer.start()  # (Re)start the single-shot timer

    def _save_caption_now(self) -> None:
        """
        Immediately write the current caption text to disk.

        Uses an atomic write strategy (temp file + os.replace + os.fsync)
        via ``CaptionManager.save_caption_atomic`` so the file is never left
        corrupt or truncated, even after a hard power cut.
        """
        if not self.current_video_original_path:
            return
        text = self.caption_edit.toPlainText()
        save_caption_atomic(self.current_video_original_path, text)

    def _create_caption_copy(self) -> None:
        """
        Create a numbered copy of the current video's caption file.

        The copy is named ``<stem>_01.txt``, ``<stem>_02.txt``, etc., using
        the first suffix that is not already taken.  Any unsaved edits are
        flushed to disk before the copy is made.
        """
        if not self.current_video_original_path:
            QMessageBox.warning(self, "No Video Selected",
                                "Please select a video first.")
            return

        # Flush unsaved edits before copying
        if self._caption_save_timer.isActive():
            self._caption_save_timer.stop()
            self._save_caption_now()

        new_path = copy_caption(self.current_video_original_path)
        if new_path:
            print(f"\u2705 Caption copy created: {new_path}")
            QMessageBox.information(
                self, "Copy Created",
                f"Caption copy saved as:\n{os.path.basename(new_path)}"
            )
        else:
            QMessageBox.warning(
                self, "Copy Failed",
                "Could not create a caption copy.\n"
                "Make sure a caption file exists for the selected video."
            )

    def _open_caption_in_explorer(self) -> None:
        """
        Open the video\u2019s folder in Windows Explorer with the caption
        ``.txt`` file pre-selected.

        If no caption file exists yet the folder is opened without a
        selection (Explorer\u2019s default behaviour for a missing file path).
        """
        if not self.current_video_original_path:
            QMessageBox.warning(self, "No Video Selected",
                                "Please select a video first.")
            return
        caption_path = get_caption_path(self.current_video_original_path)
        subprocess.Popen(['explorer', '/select,', os.path.normpath(caption_path)])

    def closeEvent(self, event):
        # Flush any pending caption auto-save so no text is lost on exit
        if hasattr(self, '_caption_save_timer') and self._caption_save_timer.isActive():
            self._caption_save_timer.stop()
            self._save_caption_now()
        self.loader.save_session()
        event.accept()

    def select_range(self, item):
        if not item: # Can happen if list is cleared
            self.current_selected_range_id = None
            self.start_frame_input.setText("-")
            self.duration_input.setText("-")
            self.end_frame_input.setText("-")
            self.clear_crop_region_controller()
            if hasattr(self, 'goto_frame_input'): self.goto_frame_input.clear() # Clear goto input
            return
            
        range_id = item.data(Qt.ItemDataRole.UserRole)
        if not range_id:
             print("⚠️ Selected item has no range ID.")
             return
             
        self.current_selected_range_id = range_id
        range_data = self.find_range_by_id(range_id)

        if range_data:
            print(f"Range selected: {range_id} -> {range_data}")
            start_frame = range_data.get("start", 0)
            end_frame = range_data.get("end", 0)
            self.start_frame_input.setText(str(start_frame))
            duration = end_frame - start_frame
            self.duration_input.setText(str(duration))
            self.end_frame_input.setText(str(end_frame))
            self._load_range_crop(range_data) # Load visual crop
            if self.frame_count > 0:
                 # Update frame display first
                 self.editor.update_frame_display(start_frame)
                 # Update slider value (may trigger scrub_video again, but should be ok)
                 self.slider.setValue(start_frame)
            # Update label (using the new method directly)
            fps = self.cap.get(cv2.CAP_PROP_FPS) if self.cap else 0
            # self.update_current_frame_label(start_frame, self.frame_count, fps) # update_frame_display handles this

            # Clear goto input when selecting a range
            if hasattr(self, 'goto_frame_input'): self.goto_frame_input.clear()

        else:
            print(f"⚠️ Could not find data for range ID: {range_id}")
            self.current_selected_range_id = None
            # Reset UI elements if data not found
            self.start_frame_input.setText("0")
            self.duration_input.setText("60")
            self.end_frame_input.setText("60")
            self.clear_crop_region_controller()
            if hasattr(self, 'goto_frame_input'): self.goto_frame_input.clear() # Clear goto input

    def update_start_frame_input(self):
        if not self.current_selected_range_id: return
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if not range_data: return
        try:
            new_start = int(self.start_frame_input.text())
            if new_start < 0:
                new_start = 0
            
            if self.last_changed_sync == 'duration':
                current_duration = int(self.duration_input.text())
                new_end = min(new_start + current_duration, self.frame_count)
                if new_end <= new_start:
                    new_end = min(new_start + 1, self.frame_count)
            else:
                new_end = int(self.end_frame_input.text())
                if new_end <= new_start:
                    new_end = min(new_start + 1, self.frame_count)
            
            range_data["start"] = new_start
            range_data["end"] = new_end
            
            self.start_frame_input.setText(str(new_start))
            self.end_frame_input.setText(str(new_end))
            self.duration_input.setText(str(new_end - new_start))
            
            current_item = self.clip_range_list.currentItem()
            if current_item:
                self._update_list_item_text(current_item, range_data)
            
            self.clip_length_label.setText(f"Clip Length: {new_end - new_start} frames | Video Length: {self.frame_count} frames")
            if self.frame_count > 0:
                 self.editor.update_frame_display(new_start)
                 self.slider.setValue(new_start)
        except ValueError:
            self.start_frame_input.setText(str(range_data.get("start", 0)))

    def update_end_frame_input(self):
        self.last_changed_sync = 'end'
        if not self.current_selected_range_id: return
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if not range_data: return
        try:
            start_frame = int(self.start_frame_input.text())
            new_end = int(self.end_frame_input.text())
            if new_end > self.frame_count:
                new_end = self.frame_count
            if new_end <= start_frame:
                new_end = start_frame + 1
            
            range_data["end"] = new_end
            self.end_frame_input.setText(str(new_end))
            self.duration_input.setText(str(new_end - start_frame))
            
            current_item = self.clip_range_list.currentItem()
            if current_item:
                self._update_list_item_text(current_item, range_data)
            
            self.clip_length_label.setText(f"Clip Length: {new_end - start_frame} frames | Video Length: {self.frame_count} frames")
        except ValueError:
            self.end_frame_input.setText(str(range_data.get("end", 60)))

    def update_range_duration_from_input(self):
        self.last_changed_sync = 'duration'
        if not self.current_selected_range_id: return
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if not range_data: return
        try:
            start_frame = int(self.start_frame_input.text())
            new_duration = int(self.duration_input.text())
            if new_duration <= 0:
                 new_duration = range_data.get("end", start_frame) - range_data.get("start", start_frame)
            
            new_end = min(start_frame + new_duration, self.frame_count)
            if new_end <= start_frame:
                 new_duration = range_data.get("end", start_frame) - range_data.get("start", start_frame)
                 new_end = min(start_frame + new_duration, self.frame_count)
            
            self.duration_input.setText(str(new_end - start_frame))
            self.end_frame_input.setText(str(new_end))
            range_data["end"] = new_end
            
            current_item = self.clip_range_list.currentItem()
            if current_item:
                self._update_list_item_text(current_item, range_data)
            
            self.clip_length_label.setText(f"Clip Length: {new_end - start_frame} frames | Video Length: {self.frame_count} frames")
        except ValueError:
            old_duration = range_data.get("end", start_frame) - range_data.get("start", start_frame)
            self.duration_input.setText(str(old_duration))

    def add_new_range(self, start=None, end=None, crop=None):
        """Adds a new range, potentially with pre-defined start, end, crop."""
        if not self.current_video_original_path:
            QMessageBox.warning(self, "No Video", "Please select a video first.")
            return
            
        if self.current_video_original_path not in self.video_data:
             # Initialize if this is the first range for this video
             self.video_data[self.current_video_original_path] = {"ranges": []}

        video_ranges = self.video_data[self.current_video_original_path]["ranges"]
        
        # Determine default start/end/crop if not provided
        if start is None:
             # Default: use current slider position
             start_frame = self.slider.value()
             try:
                 duration = int(self.duration_input.text())
                 if duration <= 0: duration = 60
             except ValueError: duration = 60
             end_frame = min(start_frame + duration, self.frame_count)
             if end_frame <= start_frame:
                  end_frame = min(start_frame + 1, self.frame_count)
                  if start_frame >= end_frame:
                      start_frame = max(0, end_frame - 1)
             # Copy crop rect from the previously selected range if it has one
             prev_range = self.find_range_by_id(self.current_selected_range_id)
             crop_tuple = prev_range.get("crop") if prev_range else None
        else:
             # Use provided values (from crop_rect_finalized)
             start_frame = start
             end_frame = end
             crop_tuple = crop

        # Create new range data
        new_range_id = str(uuid.uuid4())
        new_range_data = {
            "id": new_range_id,
            "start": start_frame,
            "end": end_frame,
            "crop": crop_tuple, # Use calculated/provided crop
            "index": len(video_ranges) + 1 # Simple 1-based index for display
        }
        video_ranges.append(new_range_data)
        print(f"Added new range: {new_range_data}")

        # Add item to the list widget
        item = QListWidgetItem()
        self._update_list_item_text(item, new_range_data) 
        self.clip_range_list.addItem(item)
        
        # Select the newly added item
        self.clip_range_list.setCurrentItem(item)
        self.select_range(item) # Trigger selection logic to load data into UI
        
    def add_range_at_current_frame(self):
         """Called by the 'Add Range Here' button."""
         self.add_new_range() # Call add_new_range without specific args
         
    def remove_selected_range(self):
        selected_items = self.clip_range_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a range to remove.")
            return
            
        current_item = selected_items[0]
        range_id_to_remove = current_item.data(Qt.ItemDataRole.UserRole)
        
        if not range_id_to_remove or not self.current_video_original_path:
            print("⚠️ Cannot remove range: Invalid state.")
            return

        # Remove from data structure
        if self.current_video_original_path in self.video_data:
            ranges = self.video_data[self.current_video_original_path].get("ranges", [])
            original_length = len(ranges)
            self.video_data[self.current_video_original_path]["ranges"] = [
                r for r in ranges if r["id"] != range_id_to_remove
            ]
            # Re-index remaining ranges for display consistency
            for i, r in enumerate(self.video_data[self.current_video_original_path]["ranges"]):
                 r["index"] = i + 1
                 
            if len(self.video_data[self.current_video_original_path]["ranges"]) < original_length:
                 print(f"Removed range {range_id_to_remove}")
            else:
                 print(f"⚠️ Range {range_id_to_remove} not found in data.")
                 # Don't remove from list if not found in data
                 return

        # Remove from list widget
        row = self.clip_range_list.row(current_item)
        self.clip_range_list.takeItem(row)
        
        # Update list item text for remaining items (due to re-indexing)
        for i in range(self.clip_range_list.count()):
            item = self.clip_range_list.item(i)
            item_range_id = item.data(Qt.ItemDataRole.UserRole)
            item_range_data = self.find_range_by_id(item_range_id)
            if item_range_data:
                self._update_list_item_text(item, item_range_data)

        # Clear selection or select next/previous
        if self.clip_range_list.count() > 0:
            next_row = min(row, self.clip_range_list.count() - 1)
            self.clip_range_list.setCurrentRow(next_row)
            self.select_range(self.clip_range_list.item(next_row)) # Explicitly call select
        else:
            self.current_selected_range_id = None
            self.start_frame_input.setText("-")
            self.duration_input.setText("-")
            self.clear_crop_region_controller()
            self.clip_length_label.setText("Clip Length: 0 frames | Video Length: ...")

    def clear_current_range_crop(self):
        if not self.current_selected_range_id:
             QMessageBox.warning(self, "No Selection", "Please select a range first.")
             return
             
        # Visually clear the rectangle
        self.clear_crop_region_controller() 
        
        # Update data
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if range_data:
           if range_data.get("crop") is not None:
               range_data["crop"] = None
               print(f"Cleared crop data for range {self.current_selected_range_id}")
           else:
                print(f"No crop data to clear for range {self.current_selected_range_id}")
        else:
            print(f"⚠️ Could not find range {self.current_selected_range_id} to clear crop data.")

    def toggle_play_selected_range(self):
        """Starts or stops playback of the currently selected range."""
        if not self.current_selected_range_id:
            QMessageBox.warning(self, "No Range Selected", "Please select a range to play.")
            return
            
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if not range_data:
            print("⚠️ Cannot play range: Data not found.")
            return
            
        print(f"Toggling playback for range: {range_data['start']} - {range_data['end']}")
        self.editor.toggle_range_playback(range_data['start'], range_data['end'])

    # --- Range Data Helper --- 
    def find_range_by_id(self, range_id):
        if self.current_video_original_path in self.video_data:
            for r in self.video_data[self.current_video_original_path].get("ranges", []):
                if r["id"] == range_id:
                    return r
        return None

    def _update_list_item_text(self, item, range_data):
        """Helper to format the text of a range list item."""
        item.setText(f"Range {range_data.get('index', '?')} [{range_data['start']}-{range_data['end']}]")
        # Store the range ID in the item's data
        item.setData(Qt.ItemDataRole.UserRole, range_data["id"])
        
    def _load_range_crop(self, range_data):
        """ Clears existing crop and loads the one for the given range."""
        self.clear_crop_region_controller()
        crop_tuple = range_data.get("crop")
        if crop_tuple:
            from scripts.interactive_crop_region import InteractiveCropRegion
            x, y, w, h = crop_tuple
            
            # Convert original coordinates back to scene coordinates
            pixmap = self.pixmap_item.pixmap()
            if pixmap and pixmap.width() > 0 and pixmap.height() > 0:
                scale_w = pixmap.width() / self.original_width
                scale_h = pixmap.height() / self.original_height
                scene_x = x * scale_w
                scene_y = y * scale_h
                scene_w = w * scale_w
                scene_h = h * scale_h
                
                # Create a QRectF object first
                scene_rect = QRectF(scene_x, scene_y, scene_w, scene_h)

                # Create and add the visual crop rectangle.
                crop_item = InteractiveCropRegion(scene_rect, aspect_ratio=self.scene.aspect_ratio)
                self.scene.addItem(crop_item)
                self.current_rect = crop_item  # Keep track of the visual item
                # IMPORTANT: register with the scene so that mouse presses are routed
                # to the existing item rather than starting a new draw.
                self.scene.crop_item = crop_item
                
                # Update UI elements
                self.crop_x_input.setText(str(x))
                self.crop_y_input.setText(str(y))
                self.crop_w_input.setText(str(w))
                self.crop_h_input.setText(str(h))
            else:
                print("⚠️ Cannot display crop: pixmap invalid.")

    def apply_manual_crop(self):
        """Applies crop typed manually in the Current Crop input fields."""
        if not self.current_selected_range_id:
            QMessageBox.warning(self, "No Selection", "Please select a range first to modify its crop.")
            return
            
        try:
            x = int(self.crop_x_input.text())
            y = int(self.crop_y_input.text())
            w = int(self.crop_w_input.text())
            h = int(self.crop_h_input.text())
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Crop values must be integers.")
            return

        if self.original_width <= 0 or self.original_height <= 0:
            return

        x = max(0, min(x, self.original_width - 1))
        y = max(0, min(y, self.original_height - 1))
        
        w = max(2, min(w, self.original_width - x))
        h = max(2, min(h, self.original_height - y))
        w = w - (w % 2)
        h = h - (h % 2)
        
        # update inputs back to corrected values
        self.crop_x_input.setText(str(x))
        self.crop_y_input.setText(str(y))
        self.crop_w_input.setText(str(w))
        self.crop_h_input.setText(str(h))

        crop_tuple = (x, y, w, h)
        range_data = self.find_range_by_id(self.current_selected_range_id)
        if range_data:
            range_data["crop"] = crop_tuple
            print(f"Manually updated crop for range {self.current_selected_range_id}: {crop_tuple}")
            self._load_range_crop(range_data)

    def open_convert_fps_dialog(self):
        """Opens the dialog to configure and start FPS conversion."""
        if not self.folder_path or not os.path.isdir(self.folder_path):
            QMessageBox.warning(self, "No Folder", "Please select a folder first.")
            return

        # We'll create the dialog class separately
        dialog = ConvertFpsDialog(self)
        if dialog.exec(): # exec() shows the dialog modally
            target_fps, output_subdir = dialog.get_values()
            if target_fps and output_subdir:
                print(f"Starting FPS conversion: Target FPS={target_fps}, Subdir={output_subdir}")
                # Call the conversion function (likely in VideoLoader)
                # This should ideally run in a thread later, but start simple
                success = self.loader.convert_folder_fps(target_fps, output_subdir)
                if success:
                    QMessageBox.information(self, "Conversion Complete", f"Videos converted to {target_fps} FPS in subfolder '{output_subdir}'. Reloading folder.")
                    # Automatically load the new folder
                    new_folder_path = os.path.normpath(os.path.join(self.folder_path, output_subdir))
                    self.folder_path = new_folder_path # Update main path
                    self.loader.load_folder_contents() # Reload contents
                else:
                    QMessageBox.critical(self, "Conversion Failed", "FPS conversion failed. Check console for details.")
            else:
                 print("Conversion cancelled or invalid values.")

    # --- Helper to format timecodes ---
    def _format_timecode(self, frame_number, fps):
        if fps <= 0:
            return "--:--:--.---"
        total_seconds = frame_number / fps
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        milliseconds = int((total_seconds - int(total_seconds)) * 1000)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
        else:
            return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    # --- Method to update the current frame label ---
    def update_current_frame_label(self, current_frame, total_frames, fps):
        if not hasattr(self, 'current_frame_label'): # Check if UI is initialized
             return
        current_tc = self._format_timecode(current_frame, fps)
        total_tc = self._format_timecode(total_frames, fps)
        if total_frames > 0:
            self.current_frame_label.setText(f"Frame: {current_frame} / {total_frames - 1}   ({current_tc} / {total_tc})")
        else:
            self.current_frame_label.setText("Frame: - / -   (--:--:--.-- / --:--:--.--)")

    # --- Slot Methods for New Frame Controls ---
    def _step_frame_backward(self):
        self.editor.step_frame(-1)

    def _step_frame_forward(self):
        self.editor.step_frame(1)

    def _goto_frame(self):
        try:
            target_frame = int(self.goto_frame_input.text())
            self.editor.goto_frame(target_frame)
        except ValueError:
            print("Invalid frame number entered.")
            # Optionally clear the input or show a brief message
            self.goto_frame_input.clear()

    def toggle_fixed_resolution_mode(self, enable):
        if enable:
            try:
                width_str = self.fixed_width_input.text()
                height_str = self.fixed_height_input.text()
                if not width_str or not height_str:
                    QMessageBox.warning(self, "Input Error", "Please enter both width and height for fixed resolution/custom AR.")
                    self.fixed_res_status_label.setText("Custom AR: Invalid input")
                    return

                width = int(width_str)
                height = int(height_str)

                if width <= 0 or height <= 0:
                    QMessageBox.warning(self, "Input Error", "Width and Height must be positive values.")
                    self.fixed_res_status_label.setText("Custom AR: Invalid W/H")
                    return
                
                self.fixed_export_width = width
                self.fixed_export_height = height
                
                self.aspect_ratio_combo.setEnabled(False)
                # self.longest_edge_input_field.setEnabled(False) # REMOVED
                
                fixed_ratio = width / height
                self.scene.set_aspect_ratio(fixed_ratio)

                # Visually update the aspect ratio combo to something that reflects the mode if possible
                # This is tricky because the ratio might be custom. "Free-form" is a safe bet.
                # Or find a matching one. For now, let's leave it or set to Free-form.
                free_form_text = "Free-form"
                if free_form_text in self.aspect_ratios:
                     # Temporarily block signals to prevent on_aspect_ratio_changed from firing
                    self.aspect_ratio_combo.blockSignals(True)
                    self.aspect_ratio_combo.setCurrentText(free_form_text)
                    self.aspect_ratio_combo.blockSignals(False)
                
                self.fixed_res_status_label.setText(f"Custom AR:{width}x{height} (Active)")
                print(f"Custom AR mode enabled: {width}x{height}")

            except ValueError:
                QMessageBox.warning(self, "Input Error", "Invalid number format for width or height.")
                self.fixed_res_status_label.setText("Custom AR: Format Error")
                # Don't automatically call toggle_fixed_resolution_mode(False) here to avoid recursion on bad input
                # User needs to correct or clear.
        else: # Disable fixed resolution mode
            self.fixed_export_width = None
            self.fixed_export_height = None
            
            self.aspect_ratio_combo.setEnabled(True)
            # self.longest_edge_input_field.setEnabled(True) # REMOVED
            
            # Optionally clear the fixed width/height input fields
            # self.fixed_width_input.clear()
            # self.fixed_height_input.clear()

            # Restore aspect ratio from the (now enabled) combobox
            current_combo_selection = self.aspect_ratio_combo.currentText()
            self.set_aspect_ratio(current_combo_selection)
            
            self.fixed_res_status_label.setText("Custom AR: Deactivated")
            print("Custom AR mode disabled.")

    # ------------------------------------------------------------------
    # Video Editing tab — Trim & Split slots
    # ------------------------------------------------------------------

    def _on_trim_clicked(self):
        """
        Handles the Trim button press in the Video Editing tab.

        Reads the trim mode and boundary frame from the UI, delegates the
        actual ffmpeg work to ``VideoFileOperator.trim_video``, then either
        reloads the overwritten video in-place or adds the new ``_trimmed``
        file to the video list, depending on the checkbox state.
        """
        if not self.current_video_original_path:
            QMessageBox.warning(self, "No Video", "Please select a video first.")
            return

        mode_text = self.trim_mode_combo.currentText()
        mode = "start" if mode_text == "Trim Start" else "end"
        frame = self.trim_frame_spinner.value()
        fps = self.editor.current_fps
        overwrite = self.trim_overwrite_checkbox.isChecked()

        if fps <= 0:
            QMessageBox.warning(self, "No FPS Data",
                                "Could not determine video FPS. Reload the video and try again.")
            return

        # Guard against trivial / no-op trims
        if mode == "start" and frame == 0:
            QMessageBox.information(self, "Nothing to Trim",
                                    "Frame 0 is already the first frame — nothing to remove.")
            return
        if mode == "end" and frame >= self.frame_count - 1:
            QMessageBox.information(self, "Nothing to Trim",
                                    "The chosen frame is already the last frame — nothing to remove.")
            return

        input_path = self.current_video_original_path

        # Release the file handle before overwriting so ffmpeg can write to the
        # same path (mirrors the pattern used in delete_current_video).
        if overwrite:
            self.editor.stop_playback()
            if self.cap:
                self.cap.release()
                self.cap = None

        print(f"Trimming '{os.path.basename(input_path)}' — mode={mode}, "
              f"frame={frame}, overwrite={overwrite}")

        success, output_paths, error = VideoFileOperator.trim_video(
            input_path, mode, frame, fps, overwrite
        )

        if not success:
            QMessageBox.critical(self, "Trim Failed",
                                 f"Could not trim video:\n\n{error}")
            if overwrite:
                # Attempt to restore the video capture so the app stays usable
                self.editor.load_video_properties(input_path)
            return

        if overwrite:
            # Reload the now-trimmed video, resetting ranges (they are stale)
            self._reload_video(input_path)
            QMessageBox.information(self, "Trim Complete",
                                    "Video trimmed and saved successfully.")
        else:
            for out_path in output_paths:
                self._add_video_to_list(out_path)
            names = "\n".join(os.path.basename(p) for p in output_paths)
            QMessageBox.information(self, "Trim Complete",
                                    f"Trimmed video saved as:\n{names}")

    def _on_split_clicked(self):
        """
        Handles the Split button press in the Video Editing tab.

        Parses the comma/space-separated frame numbers from the input field,
        delegates splitting to ``VideoFileOperator.split_video``, and adds
        each resulting part to the video list.  If "Delete original video" is
        checked and the split succeeds, the original is moved to the Recycle Bin
        and removed from the list.
        """
        if not self.current_video_original_path:
            QMessageBox.warning(self, "No Video", "Please select a video first.")
            return

        raw_text = self.split_frames_input.text().strip()
        if not raw_text:
            QMessageBox.warning(self, "No Frames",
                                "Please enter at least one split frame number.")
            return

        # Parse: split on any combination of commas and whitespace
        tokens = re.split(r'[\s,]+', raw_text)
        try:
            split_frames = [int(t) for t in tokens if t]
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "All split frame numbers must be integers.")
            return

        if not split_frames:
            QMessageBox.warning(self, "No Valid Frames",
                                "No valid frame numbers were found in the input.")
            return

        fps = self.editor.current_fps
        if fps <= 0:
            QMessageBox.warning(self, "No FPS Data",
                                "Could not determine video FPS. Reload the video and try again.")
            return

        delete_original = self.split_delete_original_checkbox.isChecked()
        input_path = self.current_video_original_path

        # Release the file handle so ffmpeg can read the file freely and,
        # if delete_original is set, send2trash can remove it afterwards.
        self.editor.stop_playback()
        if self.cap:
            self.cap.release()
            self.cap = None

        print(f"Splitting '{os.path.basename(input_path)}' at frames {split_frames}, "
              f"delete_original={delete_original}")

        success, output_paths, error = VideoFileOperator.split_video(
            input_path, split_frames, fps, delete_original
        )

        # Add successfully written parts to the video list regardless of errors
        for out_path in output_paths:
            self._add_video_to_list(out_path)

        if not success:
            QMessageBox.critical(self, "Split Failed",
                                 f"Split encountered errors:\n\n{error}")
            # Restore video capture so the app stays usable
            if os.path.isfile(input_path):
                self.editor.load_video_properties(input_path)
            return

        # Remove the original from the app state if it was deleted
        if delete_original and not os.path.isfile(input_path):
            # Remove from video_files list
            self.video_files = [
                v for v in self.video_files
                if os.path.normpath(v["original_path"]) != os.path.normpath(input_path)
            ]
            # Remove from UI list
            for i in range(self.video_list.count()):
                item = self.video_list.item(i)
                if item and item.text() == os.path.basename(input_path):
                    self.video_list.takeItem(i)
                    break
            # Remove stale video_data entry
            if input_path in self.video_data:
                del self.video_data[input_path]
            self.current_video_original_path = None

        if error:
            # Partial success — some parts wrote but delete failed (non-fatal)
            QMessageBox.warning(self, "Split Warning", error)
        else:
            names = "\n".join(os.path.basename(p) for p in output_paths)
            QMessageBox.information(self, "Split Complete",
                                    f"Video split into {len(output_paths)} parts:\n{names}")

        self.loader.save_session()

    def _reload_video(self, path: str) -> None:
        """
        Reloads a video file into the player after an in-place edit (e.g. trim
        overwrite).  Resets the slider, frame label, and clip range list because
        the original ranges are no longer valid for the modified file.

        Args:
            path (str): Absolute path of the video to reload (same as before edit).
        """
        success = self.editor.load_video_properties(path)
        if not success:
            print(f"⚠️ Could not reload video after edit: {path}")
            return

        # Update trim spinner max for the newly trimmed file
        self.trim_frame_spinner.setMaximum(max(0, self.frame_count - 1))
        self.trim_frame_spinner.setValue(0)

        # Reset ranges — existing range boundaries are invalid after trimming
        if path in self.video_data:
            self.video_data[path] = {"ranges": []}
        self.clip_range_list.clear()
        self.current_selected_range_id = None
        self.add_new_range()

        self.loader.save_session()

    def _add_video_to_list(self, video_path: str) -> None:
        """
        Adds a newly created video file to ``video_files`` and the UI list widget
        if it is not already present.  Called after trim (no overwrite) and split
        operations to make the new files immediately accessible.

        Args:
            video_path (str): Absolute path to the video file to add.
        """
        norm_path = os.path.normpath(video_path)
        # Idempotent: skip if already tracked
        if any(os.path.normpath(v["original_path"]) == norm_path
               for v in self.video_files):
            return

        filename = os.path.basename(norm_path)
        new_entry = {
            "original_path": norm_path,
            "display_name": filename,
            "copy_number": 0,
            "export_enabled": False,
        }
        self.video_files.append(new_entry)
        self.loader.add_video_item(filename)
        print(f"✅ Added to video list: {filename}")

    def trigger_export_range_start_frames(self):

        """
        Triggers the export of the first frame of each range for the selected videos.
        """
        # print(f"[DEBUG VideoCropper] Current frame number from attribute: {getattr(self, 'current_frame_number', 'N/A')}")
        # frame_to_export = 0 # Default
        # if hasattr(self, 'slider'):
        #     frame_to_export = self.slider.value()
        #     print(f"[DEBUG VideoCropper] Current frame from slider: {frame_to_export}")
        # else:
        #     print("[DEBUG VideoCropper] Slider not found.")
            
        # is_mode_image_active = getattr(self, 'is_image_mode', False) # This flag is no longer relevant here

        if hasattr(self, 'exporter'):
            # Tell the exporter to process the ranges of the selected videos
            # The exporter method will find start_frames, etc.
            self.exporter.export_first_frames_of_ranges_as_images()
        else:
            QMessageBox.warning(self, "Error", "Exporter component not initialized.")

# --- FPS Conversion Dialog --- 
class ConvertFpsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Convert Video FPS")
        
        self.layout = QFormLayout(self)
        
        # Target FPS Input
        self.fps_input = QSpinBox()
        self.fps_input.setRange(1, 120) # Reasonable range
        self.fps_input.setValue(30) # Default to 30 FPS
        self.layout.addRow("Target FPS:", self.fps_input)
        
        # Output Subfolder Input
        self.subdir_input = QLineEdit()
        self.subdir_input.setPlaceholderText("e.g., converted_30fps")
        self.layout.addRow("Output Subfolder Name:", self.subdir_input)
        
        # Update default subdir name when FPS changes
        self.fps_input.valueChanged.connect(self._update_default_subdir)
        self._update_default_subdir() # Set initial value
        
        # OK and Cancel Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept) # accept() closes with QDialog.Accepted
        self.button_box.rejected.connect(self.reject) # reject() closes with QDialog.Rejected
        self.layout.addWidget(self.button_box)
        
    def _update_default_subdir(self):
        fps = self.fps_input.value()
        self.subdir_input.setText(f"converted_{fps}fps")
        
    def get_values(self):
        """Returns the selected FPS and subfolder name if accepted."""
        # Basic validation could be added here before returning
        fps = self.fps_input.value()
        subdir = self.subdir_input.text().strip()
        if not subdir: # Ensure subdir name is not empty
             # Optionally show a warning
             return None, None
        # Add more validation for subdir name (e.g., no invalid characters)?
        return fps, subdir

# ── Custom Widgets ────────────────────────────────────────────────────────────

class SpellingTextEdit(QTextEdit):
    """
    A QTextEdit subclass that provides spelling suggestions via a right-click
    context menu. It works in tandem with SpellCheckHighlighter.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighter = None

    def set_highlighter(self, highlighter):
        """Sets the highlighter instance used for spellchecking."""
        self.highlighter = highlighter

    def contextMenuEvent(self, event):
        """Overrides contextMenuEvent to add spelling suggestions."""
        menu = self.createStandardContextMenu()
        
        if not self.highlighter:
            menu.exec(event.globalPos())
            return

        # Find the word at the clicked position
        cursor = self.cursorForPosition(event.pos())
        cursor.select(cursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()

        if word and self.highlighter.is_misspelled(word):
            suggestions = self.highlighter.get_suggestions(word)
            
            if suggestions:
                menu.addSeparator()
                suggestion_menu = menu.addMenu("\U0001f52e Suggestions")
                for s in suggestions:
                    action = suggestion_menu.addAction(s)
                    # Use a lambda with captured values to replace the word
                    action.triggered.connect(lambda checked, replacement=s, c=cursor: self._replace_word(c, replacement))
            
            # Option to add to dictionary
            add_action = menu.addAction("\u2795 Add to Dictionary")
            add_action.triggered.connect(lambda: self._add_to_dictionary(word))
            menu.addSeparator()

        menu.exec(event.globalPos())

    def _replace_word(self, cursor, replacement):
        """Replaces the word at the cursor with the selected suggestion."""
        cursor.insertText(replacement)

    def _add_to_dictionary(self, word):
        """Adds a word to the spellchecker's session dictionary."""
        if self.highlighter:
            self.highlighter.add_word(word)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Use explicit path check
    css_path = os.path.normpath(os.path.join("styles", "dark_mode.css"))
    if os.path.exists(css_path):
        try:
            with open(css_path, "r") as file:
                app.setStyleSheet(file.read())
        except Exception as e:
            print(f"Error loading stylesheet: {e}")
    else:
        print(f"Stylesheet not found at {css_path}")

    try:
        window = VideoCropper()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        print(f"An error occurred: {e}")
        traceback.print_exc() # Print full traceback
        input("Press Enter to exit...")
        sys.exit(1)
