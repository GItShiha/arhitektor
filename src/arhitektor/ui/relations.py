from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arhitektor.ui.field_editor import scroll_area


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


class RelatedObjects(QWidget):
    open_requested = Signal(int)
    delete_requested = Signal(int)
    create_requested = Signal()

    def __init__(self, article_id: int, catalog: dict, compact=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Связанные объекты"))
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        articles = {row["id"]: row for row in catalog["article"]}
        count = 0
        for relation in catalog.get("relation", []):
            if article_id not in (relation["source_id"], relation["target_id"]):
                continue
            forward = relation["source_id"] == article_id
            other_id = relation["target_id"] if forward else relation["source_id"]
            label = relation["label"] if forward else relation["reverse_label"]
            title = QLabel(f"{label} → {articles[other_id]['title']}")
            title.setWordWrap(True)
            rows.addWidget(title)
            button = QPushButton("Открыть статью")
            button.clicked.connect(
                lambda _=False, identifier=other_id: self.open_requested.emit(identifier)
            )
            rows.addWidget(button)
            if not compact:
                remove = QPushButton("Удалить связь")
                remove.clicked.connect(
                    lambda _=False, identifier=relation["id"]: self.delete_requested.emit(
                        identifier
                    )
                )
                rows.addWidget(remove)
            count += 1
        if count == 0:
            rows.addWidget(QLabel("Связей пока нет"))
        if compact:
            layout.addWidget(content)
        else:
            scroll = scroll_area(content)
            scroll.setMaximumHeight(190)
            layout.addWidget(scroll)
            add = QPushButton("＋ Связать со статьёй")
            add.clicked.connect(self.create_requested)
            layout.addWidget(add)
