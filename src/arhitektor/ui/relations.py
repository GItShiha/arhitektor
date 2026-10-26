from PySide6.QtCore import QAbstractListModel, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)


class RelationDialog(QDialog):
    def __init__(self, articles: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Связать статьи")
        self.resize(600, 520)
        self.articles = articles
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Прямое отношение"))
        self.label = QComboBox()
        self.label.setEditable(True)
        self.label.addItems(["связан с", "работает в", "состоит в", "родился в", "контролирует"])
        layout.addWidget(self.label)
        layout.addWidget(QLabel("Обратное отношение"))
        self.reverse = QLineEdit("связан с")
        layout.addWidget(self.reverse)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти статью по названию…")
        layout.addWidget(self.search)
        self.kind = QComboBox()
        self.kind.addItem("Все типы", None)
        for kind in sorted({row["kind"] for row in articles}):
            self.kind.addItem(kind, kind)
        layout.addWidget(self.kind)
        self.results = QListWidget()
        layout.addWidget(self.results, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm.setText("Создать связь")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter)
        self.kind.currentIndexChanged.connect(self.filter)
        self.results.currentItemChanged.connect(self.validate)
        self.label.currentTextChanged.connect(self.validate)
        self.reverse.textChanged.connect(self.validate)
        self.filter()

    def filter(self, *_args):
        self.results.clear()
        for row in self.articles:
            if self.kind.currentData() not in (None, row["kind"]):
                continue
            if self.search.text().casefold() not in row["title"].casefold():
                continue
            item = QListWidgetItem(f"{row['title']} · {row['kind']}")
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setToolTip(item.text())
            self.results.addItem(item)
        self.validate()

    def validate(self, *_args):
        self.confirm.setEnabled(
            bool(
                self.results.currentItem()
                and self.label.currentText().strip()
                and self.reverse.text().strip()
            )
        )

    def values(self):
        return (
            self.results.currentItem().data(Qt.ItemDataRole.UserRole),
            self.label.currentText(),
            self.reverse.text(),
        )


def related_rows(article_id: int, catalog: dict) -> list[dict]:
    articles = {row["id"]: row for row in catalog["article"]}
    result = []
    for relation in catalog.get("relation", []):
        if article_id not in (relation["source_id"], relation["target_id"]):
            continue
        forward = relation["source_id"] == article_id
        other_id = relation["target_id"] if forward else relation["source_id"]
        other = articles[other_id]
        result.append(
            {
                "id": relation["id"],
                "article_id": other_id,
                "title": other["title"],
                "kind": other["kind"],
                "label": relation["label"] if forward else relation["reverse_label"],
            }
        )
    return result


class RelationsModel(QAbstractListModel):
    """Lightweight rows; no per-relation widgets or persistent editors."""

    def __init__(self, rows, checkable=False, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.checkable = checkable
        self.checked = set()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        text = f"{row['title']} · {row['kind']} · {row['label']}"
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return text
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(0, 32)
        if role == Qt.ItemDataRole.CheckStateRole and self.checkable:
            return Qt.CheckState.Checked if row["id"] in self.checked else Qt.CheckState.Unchecked
        return None

    def flags(self, index):
        flags = super().flags(index)
        if self.checkable:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or not self.checkable:
            return False
        identifier = self.rows[index.row()]["id"]
        if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
            self.checked.add(identifier)
        else:
            self.checked.discard(identifier)
        self.dataChanged.emit(index, index, [role])
        return True

    def clear_checked(self):
        self.checked.clear()
        if self.rows:
            self.dataChanged.emit(
                self.index(0), self.index(len(self.rows) - 1), [Qt.ItemDataRole.CheckStateRole]
            )


class RelationSearch(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)


class RelationRowDelegate(QStyledItemDelegate):
    def __init__(self, parent):
        super().__init__(parent)
        self.arrow = parent.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Reserve space so the navigation indicator survives text elision.
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
        option.icon = self.arrow
        option.decorationSize = QSize(12, 12)
        option.decorationPosition = QStyleOptionViewItem.Position.Right


class RelatedObjects(QWidget):
    open_requested = Signal(int)
    remove_requested = Signal()
    create_requested = Signal()

    def __init__(self, article_id: int, catalog: dict):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        title = QLabel("Связанные объекты")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        self.add = QPushButton("Добавить связь")
        self.add.clicked.connect(self.create_requested)
        header.addWidget(self.add)
        self.remove = QPushButton("Убрать связь")
        self.remove.clicked.connect(self.remove_requested)
        header.addWidget(self.remove)
        layout.addLayout(header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию, типу или отношению…")
        layout.addWidget(self.search)
        self.model = RelationsModel(related_rows(article_id, catalog), parent=self)
        self.proxy = RelationSearch(self)
        self.proxy.setSourceModel(self.model)
        self.results = QListView()
        self.results.setModel(self.proxy)
        self.results.setUniformItemSizes(True)
        self.results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.results.setItemDelegate(RelationRowDelegate(self.results))
        self.results.setCursor(Qt.CursorShape.PointingHandCursor)
        self.results.clicked.connect(self.open_row)
        keyboard_open = QShortcut(self.results)
        keyboard_open.setKeys([QKeySequence(Qt.Key.Key_Return), QKeySequence(Qt.Key.Key_Enter)])
        keyboard_open.setContext(Qt.ShortcutContext.WidgetShortcut)
        keyboard_open.activated.connect(lambda: self.open_row(self.results.currentIndex()))
        layout.addWidget(self.results)
        self.empty = QLabel()
        layout.addWidget(self.empty)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.proxy.modelReset.connect(self.resize_list)
        self.proxy.rowsInserted.connect(self.resize_list)
        self.proxy.rowsRemoved.connect(self.resize_list)
        self.remove.setEnabled(bool(self.model.rows))
        self.resize_list()

    def open_row(self, index):
        if index.isValid():
            self.open_requested.emit(index.data(Qt.ItemDataRole.UserRole)["article_id"])

    def resize_list(self, *_args):
        count = self.proxy.rowCount()
        # The card's outer scroll area owns scrolling, even for long lists.
        self.results.setFixedHeight(count * 32 + 2 * self.results.frameWidth())
        self.results.setVisible(bool(count))
        self.empty.setText("Ничего не найдено" if self.model.rows else "Связей пока нет")
        self.empty.setVisible(not count)


class DeleteRelationsDialog(QDialog):
    delete_requested = Signal(object)

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Удаление связей")
        self.resize(680, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Выберите связи. Статьи сохранятся."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию, типу или отношению…")
        layout.addWidget(self.search)
        self.model = RelationsModel(rows, checkable=True, parent=self)
        self.proxy = RelationSearch(self)
        self.proxy.setSourceModel(self.model)
        self.results = QListView()
        self.results.setModel(self.proxy)
        self.results.setUniformItemSizes(True)
        layout.addWidget(self.results, 1)
        self.count = QLabel()
        layout.addWidget(self.count)
        self.clear = QPushButton("Снять выделение")
        self.clear.clicked.connect(self.model.clear_checked)
        layout.addWidget(self.clear)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.confirm = buttons.addButton(
            "Удалить выбранные", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.confirm.clicked.connect(lambda: self.delete_requested.emit(sorted(self.model.checked)))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.model.dataChanged.connect(self.update_count)
        self.update_count()
        self.busy = False

    def update_count(self, *_args):
        self.count.setText(f"Выбрано связей: {len(self.model.checked)}")
        self.confirm.setEnabled(bool(self.model.checked))
        self.clear.setEnabled(bool(self.model.checked))

    def set_busy(self, busy):
        self.busy = busy
        self.setEnabled(not busy)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def show_error(self, message):
        self.set_busy(False)
        detail = (
            message
            if message.startswith("Список связей изменился")
            else "Попробуйте ещё раз или откройте диалог заново."
        )
        self.error.setText(f"Не удалось удалить связи. Ни одна связь не удалена. {detail}")
        self.error.show()
