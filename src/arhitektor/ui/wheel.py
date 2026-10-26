"""Route wheel gestures over closed property controls to their owning scroll area."""

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QScrollArea, QWidget


class PropertyWheelRouter(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        # Also cover the line edit child of spinboxes. Stop at text editors and
        # other controls: this policy must not change their scroll behavior.
        control = watched
        while control is not None and not (
            isinstance(control, (QAbstractSpinBox, QComboBox))
            or control.property("propertyWheelControl")
        ):
            if control is self.parent().widget():
                return False
            control = control.parentWidget()
        if control is None:
            return False
        if isinstance(control, QComboBox) and control.view().isVisible():
            return False
        area = control.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            if area.isWindow():
                return False
            area = area.parentWidget()
        if area is not self.parent():
            return False
        viewport = area.viewport()
        forwarded = QWheelEvent(
            viewport.mapFromGlobal(event.globalPosition().toPoint()),
            event.globalPosition(),
            event.pixelDelta(),
            event.angleDelta(),
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
            event.pointingDevice(),
        )
        from PySide6.QtWidgets import QApplication

        scrollbar = area.verticalScrollBar()
        before = scrollbar.value()
        QApplication.sendEvent(viewport, forwarded)
        if event.pixelDelta().y() and scrollbar.value() == before:
            # Some Qt platform plugins ignore pixel-only wheel gestures on a
            # scroll-area viewport. Respect their signed pixel delta directly;
            # do not reinterpret natural-scrolling direction a second time.
            scrollbar.setValue(before - event.pixelDelta().y())
        event.accept()
        return True


def route_property_wheels(area):
    # An application event filter covers dynamically added cards and descendants.
    # Its scope is restricted to this scroll area, including its nested controls.
    from PySide6.QtWidgets import QApplication

    router = PropertyWheelRouter(area)
    QApplication.instance().installEventFilter(router)
    area._wheel_router = router
