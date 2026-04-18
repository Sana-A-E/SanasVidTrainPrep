from PyQt6.QtWidgets import QGraphicsView
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import Qt

class CustomGraphicsView(QGraphicsView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)


    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene() and hasattr(self.scene(), 'parent_widget'):
            app = self.scene().parent_widget
            if hasattr(app, 'editor') and hasattr(app, 'slider'):
                # Redraw frame which rescales the pixmap based on new view size
                app.editor.update_frame_display(app.slider.value())
                # Reload crop region to match the newly scaled scene coordinates
                if app.current_selected_range_id:
                    range_data = app.find_range_by_id(app.current_selected_range_id)
                    if range_data and range_data.get("crop"):
                        app._load_range_crop(range_data)

