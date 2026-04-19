# interactive_crop_region.py
from PyQt6.QtWidgets import QGraphicsRectItem, QStyleOptionGraphicsItem, QWidget, QGraphicsSceneMouseEvent, QGraphicsSceneWheelEvent, QGraphicsSceneHoverEvent
from PyQt6.QtGui import QPen, QBrush, QColor, QPainter
from PyQt6.QtCore import QRectF, Qt, QPointF

class InteractiveCropRegion(QGraphicsRectItem):
    HANDLE_SIZE = 8
    MIN_SIZE = 20

    def __init__(self, rect: QRectF, aspect_ratio: float = None, parent=None):
        """
        rect: initial rectangle in local coordinates.
        aspect_ratio: if set, enforces width/height ratio (e.g. 16/9); if None, freeform.
        """
        super().__init__(rect, parent)
        self.aspect_ratio = aspect_ratio
        
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        # Enable focus so wheel events are received.
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsFocusable, True)
        
        self.setPen(QPen(QColor("red"), 2))
        self.setBrush(QBrush(QColor(165, 0, 0, 30)))
        
        # Internal state for resizing
        self.active_handle = None  # "top_left", "top_right", "bottom_left", or "bottom_right"
        self.resizing = False
        self.start_rect_scene = QRectF()   # start rect in scene coordinates
        self.start_mouse_scene = QPointF() # start mouse position in scene coordinates
        
        self.handle_positions = {}
        
        self.setRect(rect)
            
        self.updateHandlePositions()

    def boundingRect(self) -> QRectF:
        """Return the area that needs to be repainted (including handles)."""
        rect = self.rect()
        extra = self.HANDLE_SIZE / 2
        return rect.adjusted(-extra, -extra, extra, extra)

    def shape(self):
        from PyQt6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    def updateHandlePositions(self):
        """Compute small square handles at the four corners of the crop rect."""
        r = self.rect()
        s = self.HANDLE_SIZE
        half = s / 2
        self.handle_positions = {
            "top_left": QRectF(r.left() - half, r.top() - half, s, s),
            "top_right": QRectF(r.right() - half, r.top() - half, s, s),
            "bottom_left": QRectF(r.left() - half, r.bottom() - half, s, s),
            "bottom_right": QRectF(r.right() - half, r.bottom() - half, s, s)
        }
        # Request a repaint for the whole bounding rect
        self.update()

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget = None):
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for handle_rect in self.handle_positions.values():
            painter.drawRect(handle_rect)
            painter.drawRect(handle_rect)
            painter.drawRect(handle_rect)

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        pos = event.pos()
        handle = self.getHandleAt(pos)
        if handle:
            if handle in ("top_left", "bottom_right"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif handle in ("top_right", "bottom_left"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        event.accept()

    def getHandleAt(self, pos: QPointF):
        for name, rect in self.handle_positions.items():
            if rect.contains(pos):
                return name
        return None

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        pos_local = event.pos()
        handle = self.getHandleAt(pos_local)
        if handle:
            self.active_handle = handle
            self.resizing = True
            # Capture start state in scene coordinates to avoid local-coord drift
            # when the item's origin shifts due to ItemIsMovable.
            self.start_rect_scene = self.mapRectToScene(self.rect())
            self.start_mouse_scene = event.scenePos()
        else:
            self.resizing = False
            super().mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        """
        Handle mouse drag for resizing (when a handle is active) or moving the whole rect.
        All resize arithmetic is done in scene coordinates to prevent local-coord drift
        that can occur when the item's origin shifts due to ItemIsMovable.
        """
        if self.resizing and self.active_handle:
            scene_delta = event.scenePos() - self.start_mouse_scene
            s = self.start_rect_scene          # start rect in scene space
            scene_bounds = self.scene().sceneRect()

            # Determine which edge moves (the dragged corner) and which stays fixed.
            if self.active_handle == "top_left":
                fixed_pt = s.bottomRight()
                moved_x = s.left()  + scene_delta.x()
                moved_y = s.top()   + scene_delta.y()
                if self.aspect_ratio:
                    w = fixed_pt.x() - moved_x
                    h = fixed_pt.y() - moved_y
                    if w / max(h, 1e-6) > self.aspect_ratio:
                        w = h * self.aspect_ratio
                    else:
                        h = w / self.aspect_ratio
                    moved_x = fixed_pt.x() - w
                    moved_y = fixed_pt.y() - h
                # Clamp moving edge to scene bounds
                moved_x = max(scene_bounds.left(), moved_x)
                moved_y = max(scene_bounds.top(),  moved_y)
                new_scene_rect = QRectF(QPointF(moved_x, moved_y), fixed_pt).normalized()

            elif self.active_handle == "top_right":
                fixed_pt = s.bottomLeft()
                moved_x = s.right() + scene_delta.x()
                moved_y = s.top()   + scene_delta.y()
                if self.aspect_ratio:
                    w = moved_x - fixed_pt.x()
                    h = fixed_pt.y() - moved_y
                    if w / max(h, 1e-6) > self.aspect_ratio:
                        w = h * self.aspect_ratio
                    else:
                        h = w / self.aspect_ratio
                    moved_x = fixed_pt.x() + w
                    moved_y = fixed_pt.y() - h
                moved_x = min(scene_bounds.right(), moved_x)
                moved_y = max(scene_bounds.top(),   moved_y)
                new_scene_rect = QRectF(fixed_pt, QPointF(moved_x, moved_y)).normalized()

            elif self.active_handle == "bottom_left":
                fixed_pt = s.topRight()
                moved_x = s.left()   + scene_delta.x()
                moved_y = s.bottom() + scene_delta.y()
                if self.aspect_ratio:
                    w = fixed_pt.x() - moved_x
                    h = moved_y - fixed_pt.y()
                    if w / max(h, 1e-6) > self.aspect_ratio:
                        w = h * self.aspect_ratio
                    else:
                        h = w / self.aspect_ratio
                    moved_x = fixed_pt.x() - w
                    moved_y = fixed_pt.y() + h
                moved_x = max(scene_bounds.left(),   moved_x)
                moved_y = min(scene_bounds.bottom(), moved_y)
                new_scene_rect = QRectF(QPointF(moved_x, moved_y), fixed_pt).normalized()

            else:  # bottom_right
                fixed_pt = s.topLeft()
                moved_x = s.right()  + scene_delta.x()
                moved_y = s.bottom() + scene_delta.y()
                if self.aspect_ratio:
                    w = moved_x - fixed_pt.x()
                    h = moved_y - fixed_pt.y()
                    if w / max(h, 1e-6) > self.aspect_ratio:
                        w = h * self.aspect_ratio
                    else:
                        h = w / self.aspect_ratio
                    moved_x = fixed_pt.x() + w
                    moved_y = fixed_pt.y() + h
                moved_x = min(scene_bounds.right(),  moved_x)
                moved_y = min(scene_bounds.bottom(), moved_y)
                new_scene_rect = QRectF(fixed_pt, QPointF(moved_x, moved_y)).normalized()

            # Enforce minimum size
            if new_scene_rect.width() < self.MIN_SIZE or new_scene_rect.height() < self.MIN_SIZE:
                new_scene_rect = self.start_rect_scene

            # Convert back to local item coordinates and apply
            new_local_rect = self.mapRectFromScene(new_scene_rect)
            self.prepareGeometryChange()
            self.setRect(new_local_rect)
            self.updateHandlePositions()
            event.accept()
            if self.scene() and hasattr(self.scene().parent_widget, "crop_rect_updating"):
                self.scene().parent_widget.crop_rect_updating(self.mapRectToScene(self.rect()))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        """
        Finalise a resize or move operation, clamp position to scene bounds,
        and notify the parent widget with the true drawn rect (not the inflated
        bounding rect which includes handle padding).
        """
        if not self.resizing:
            super().mouseReleaseEvent(event)
        self.resizing = False
        self.clamp_to_scene_bounds()
        event.accept()
        if self.scene() and hasattr(self.scene().parent_widget, "crop_rect_finalized"):
            # Use mapRectToScene(rect()) — the actual drawn rect — NOT sceneBoundingRect()
            # which is expanded by HANDLE_SIZE/2 + pen width on every side.
            self.scene().parent_widget.crop_rect_finalized(self.mapRectToScene(self.rect()))

    def itemChange(self, change, value):
        """
        Intercept ItemPositionChange (fires before every move, including moveBy and
        Qt's built-in drag) to clamp the item so its *actual drawn rect* never leaves
        the scene boundaries.

        Using ItemPositionChange (not ItemPositionHasChanged) lets us return an
        adjusted QPointF and avoids any risk of recursive callbacks.
        """
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value  # proposed new position (QPointF) in parent/scene coords
            r = self.rect()  # local rect (top-left may not be at 0,0)
            # Where the actual drawn rect would be in scene space at new_pos.
            # This assumes no rotation/scale on the item (which we never apply).
            proposed = QRectF(
                new_pos.x() + r.x(),
                new_pos.y() + r.y(),
                r.width(),
                r.height()
            )
            bounds = self.scene().sceneRect()
            dx, dy = 0.0, 0.0
            if proposed.left() < bounds.left():
                dx = bounds.left() - proposed.left()
            if proposed.top() < bounds.top():
                dy = bounds.top() - proposed.top()
            if proposed.right() > bounds.right():
                dx = bounds.right() - proposed.right()
            if proposed.bottom() > bounds.bottom():
                dy = bounds.bottom() - proposed.bottom()
            if dx or dy:
                return QPointF(new_pos.x() + dx, new_pos.y() + dy)
        return super().itemChange(change, value)

    def clamp_to_scene_bounds(self):
        """
        Adjusts the item's position so the actual drawn rect stays fully inside
        the scene's bounding rect.  Uses mapRectToScene(rect()) — the true drawn
        rect — NOT sceneBoundingRect() which is inflated by handle padding and
        would cause an erroneous position shift equal to HANDLE_SIZE/2.
        """
        if not self.scene():
            return
        scene_rect = self.scene().sceneRect()
        crop_rect = self.mapRectToScene(self.rect())
        dx, dy = 0.0, 0.0
        if crop_rect.left() < scene_rect.left():
            dx = scene_rect.left() - crop_rect.left()
        if crop_rect.top() < scene_rect.top():
            dy = scene_rect.top() - crop_rect.top()
        if crop_rect.right() > scene_rect.right():
            dx = scene_rect.right() - crop_rect.right()
        if crop_rect.bottom() > scene_rect.bottom():
            dy = scene_rect.bottom() - crop_rect.bottom()
        if dx or dy:
            self.moveBy(dx, dy)

    def wheelEvent(self, event: QGraphicsSceneWheelEvent):
        """
        Scale the crop rect uniformly on mouse-wheel scroll, then clamp to scene bounds.
        The scale is applied about the rect's current center in local space.
        Clamping is delegated to clamp_to_scene_bounds() which uses the actual
        drawn rect (not the handle-padded bounding rect).
        """
        delta_val = event.delta()
        scale_factor = 1.0 + (delta_val / 120) * 0.1
        current_rect = self.rect()
        center = current_rect.center()
        new_width  = current_rect.width()  * scale_factor
        new_height = current_rect.height() * scale_factor
        if new_width < self.MIN_SIZE or new_height < self.MIN_SIZE:
            event.ignore()
            return
        if self.aspect_ratio:
            new_height = new_width / self.aspect_ratio
        new_rect = QRectF(
            center.x() - new_width  / 2,
            center.y() - new_height / 2,
            new_width,
            new_height
        )
        self.prepareGeometryChange()
        self.setRect(new_rect)
        self.updateHandlePositions()
        # Clamp position via the corrected helper (uses actual rect, not bounding rect).
        self.clamp_to_scene_bounds()
        event.accept()
        if self.scene() and hasattr(self.scene().parent_widget, "crop_rect_finalized"):
            self.scene().parent_widget.crop_rect_finalized(self.mapRectToScene(self.rect()))

    def update_geometry_on_ratio_change(self):
        if self.aspect_ratio is not None and self.rect().width() > 0:
            current_rect = self.rect()
            current_center = current_rect.center()
            
            # Keep current width, adjust height based on new aspect ratio
            new_width = current_rect.width()
            new_height = new_width / self.aspect_ratio

            # Ensure minimum size, adjust both width and height if necessary to maintain ratio
            min_w_for_min_h = self.MIN_SIZE * self.aspect_ratio
            min_h_for_min_w = self.MIN_SIZE / self.aspect_ratio

            if new_height < self.MIN_SIZE:
                new_height = self.MIN_SIZE
                new_width = new_height * self.aspect_ratio 
           
            if new_width < self.MIN_SIZE: # Check width after height adjustment
                new_width = self.MIN_SIZE
                new_height = new_width / self.aspect_ratio

            # Create new rect centered
            new_top_left_x = current_center.x() - new_width / 2
            new_top_left_y = current_center.y() - new_height / 2
            
            adjusted_rect = QRectF(new_top_left_x, new_top_left_y, new_width, new_height)
            
            self.prepareGeometryChange() # Important before changing geometry that affects boundingRect
            self.setRect(adjusted_rect.normalized())
            self.updateHandlePositions()
            self.clamp_to_scene_bounds() # Ensure it stays within scene after resize
            
            if self.scene() and hasattr(self.scene().parent_widget, "crop_rect_finalized"):
                # Notify parent that the crop has changed due to aspect ratio update.
                # Use mapRectToScene(rect()) — the actual drawn rect.
                self.scene().parent_widget.crop_rect_finalized(self.mapRectToScene(self.rect()))
            self.update() # Request a repaint