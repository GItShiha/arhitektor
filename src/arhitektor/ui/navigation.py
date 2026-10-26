"""Section navigation; it never owns or changes database records."""

from collections import defaultdict
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

SECTIONS = ("Обзор", "Произведения", "Энциклопедия", "Персонажи", "Организации", "Локации")
ARTICLE_KINDS = {"Персонажи": "персонаж", "Организации": "организация", "Локации": "локация"}


class NavigationPanel(QWidget):
    target_requested = Signal(object)
    section_requested = Signal(str)
    universe_requested = Signal(object)
    create_requested = Signal()
    settings_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 12, 16)
        brand = QLabel("АРХИТЕКТОР")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addWidget(QLabel("Текущая вселенная"))
        self.universe = QComboBox()
        self.universe.currentIndexChanged.connect(
            lambda _: self.universe_requested.emit(self.universe.currentData())
        )
        layout.addWidget(self.universe)
        row = QHBoxLayout()
        back = QPushButton("← Назад")
        back.clicked.connect(self.back_requested)
        row.addWidget(back)
        add = QPushButton("＋ Создать")
        add.clicked.connect(self.create_requested)
        row.addWidget(add)
        layout.addLayout(row)
        self.sections = QListWidget()
        self.sections.setObjectName("sections")
        self.sections.addItems(SECTIONS)
        self.sections.setFixedHeight(221)
        self.sections.currentTextChanged.connect(self.section_requested)
        layout.addWidget(self.sections)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск в разделе…")
        self.search.textChanged.connect(self.filter_tree)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self.choose)
        layout.addWidget(self.tree, 1)
        settings = QPushButton("⚙  Настройки и данные")
        settings.clicked.connect(self.settings_requested)
        layout.addWidget(settings)
        self.sections.setCurrentRow(0)

    @property
    def section(self) -> str:
        return self.sections.currentItem().text() if self.sections.currentItem() else "Обзор"

    @property
    def universe_id(self) -> int | None:
        return self.universe.currentData()

    def choose(self, item, _previous):
        if item is not None:
            target = item.data(0, Qt.ItemDataRole.UserRole)
            if target:
                self.target_requested.emit(target)

    def select_section(self, name: str):
        self.sections.blockSignals(True)
        matches = self.sections.findItems(name, Qt.MatchFlag.MatchExactly)
        if matches:
            self.sections.setCurrentItem(matches[0])
        self.sections.blockSignals(False)

    def update_universes(self, rows: list[dict[str, Any]]):
        old = self.universe_id
        self.universe.blockSignals(True)
        self.universe.clear()
        self.universe.addItem("Все вселенные", None)
        for row in rows:
            self.universe.addItem(row["title"], row["id"])
        self.universe.setCurrentIndex(max(0, self.universe.findData(old)))
        self.universe.blockSignals(False)

    def section_for(self, kind: str) -> str:
        return {
            "universe": "Обзор",
            "work": "Произведения",
            "scene": "Произведения",
            "article": "Энциклопедия",
        }[kind]

    def populate(self, catalog: dict[str, list[dict]], selected=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        section, universe_id = self.section, self.universe_id
        nodes = {}
        if section == "Обзор":
            for row in catalog["universe"]:
                self._item(self.tree, row, "universe", nodes)
        elif section == "Произведения":
            for row in catalog["work"]:
                if universe_id is None or row["universe_id"] == universe_id:
                    self._item(self.tree, row, "work", nodes)
            for row in catalog["scene"]:
                if row["work_id"] in nodes:
                    self._item(nodes[row["work_id"]], row, "scene")
        else:
            groups = defaultdict(list)
            for row in catalog["article"]:
                if universe_id is not None and row["universe_id"] != universe_id:
                    continue
                if section in ARTICLE_KINDS and row["kind"].casefold() != ARTICLE_KINDS[section]:
                    continue
                groups[row["kind"]].append(row)
            for category, rows in sorted(groups.items()):
                parent = QTreeWidgetItem(self.tree, [category])
                for row in rows:
                    self._item(parent, row, "article")
        self.tree.expandAll()
        self.select_target(selected)
        self.tree.blockSignals(False)
        self.filter_tree(self.search.text())

    def _item(self, parent, row, kind, nodes=None):
        item = QTreeWidgetItem(parent, [row["title"]])
        item.setData(0, Qt.ItemDataRole.UserRole, (kind, row["id"]))
        item.setData(
            0,
            Qt.ItemDataRole.UserRole + 1,
            " ".join([row["title"], row.get("content", ""), *row.get("tags", [])]).casefold(),
        )
        if nodes is not None:
            nodes[row["id"]] = item
        return item

    def select_target(self, target):
        def find(parent):
            for index in range(parent.childCount()):
                item = parent.child(index)
                if item.data(0, Qt.ItemDataRole.UserRole) == target:
                    return item
                child = find(item)
                if child:
                    return child
            return None

        self.tree.blockSignals(True)
        self.tree.setCurrentItem(find(self.tree.invisibleRootItem()))
        self.tree.blockSignals(False)

    def filter_tree(self, query: str):
        needle = query.casefold().strip()

        def visit(item):
            child_matches = False
            for index in range(item.childCount()):
                child_matches = visit(item.child(index)) or child_matches
            matches = (
                needle in (item.data(0, Qt.ItemDataRole.UserRole + 1) or item.text(0).casefold())
                or child_matches
            )
            item.setHidden(not matches)
            return matches

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
