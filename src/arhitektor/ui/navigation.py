"""Section navigation; it never owns or changes database records."""

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

SECTIONS = ("Обзор", "Произведения", "Энциклопедия")


class NavigationPanel(QWidget):
    target_requested = Signal(object)
    section_requested = Signal(str)
    universe_requested = Signal(object)
    create_requested = Signal()
    settings_requested = Signal()
    back_requested = Signal()
    templates_requested = Signal()

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
        self.sections.setFixedHeight(112)
        self.sections.currentTextChanged.connect(self.section_requested)
        layout.addWidget(self.sections)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск в разделе…")
        self.search.textChanged.connect(self.filter_tree)
        layout.addWidget(self.search)
        self.templates_button = QPushButton("Типы и шаблоны")
        self.templates_button.clicked.connect(self.templates_requested)
        layout.addWidget(self.templates_button)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.expanded = set()
        self.expansion_contexts = {}
        self.tree_context = None
        self.search_expanded = None
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
        self.templates_button.setVisible(self.section not in ("Обзор", "Произведения"))
        self.universe_names = {u["id"]: u["title"] for u in catalog["universe"]}
        if self.tree_context is not None:
            self.expansion_contexts[self.tree_context] = (
                self.search_expanded if self.search_expanded is not None else self.expansion_state()
            )
        self.tree_context = (self.section, self.universe_id)
        self.expanded = self.expansion_contexts.get(self.tree_context, set())
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
            self.categories = {}
            templates = sorted(catalog.get("template", []), key=lambda t: (t["position"], t["id"]))
            for universe in catalog["universe"]:
                uid = universe["id"]
                if universe_id is not None and uid != universe_id:
                    continue
                parent = self.tree
                if universe_id is None:
                    parent = QTreeWidgetItem(self.tree, [universe["title"]])
                    parent.setData(0, Qt.ItemDataRole.UserRole + 2, ("world", uid))
                    parent.setToolTip(0, universe["title"])
                by_id = {}
                for template in templates:
                    if template["universe_id"] != uid:
                        continue
                    key = ("category", uid, template["id"], "")
                    self.categories[key] = {"title": template["title"], "rows": []}
                    by_id[template["id"]] = key
                for row in catalog["article"]:
                    if row["universe_id"] != uid:
                        continue
                    key = by_id.get(row.get("template_id"), ("category", uid, None, row["kind"]))
                    self.categories.setdefault(key, {"title": row["kind"], "rows": []})[
                        "rows"
                    ].append(row)
                for key, group in self.categories.items():
                    if key[1] != uid:
                        continue
                    node = QTreeWidgetItem(parent, [f"{group['title']} ({len(group['rows'])})"])
                    node.setToolTip(0, group["title"])
                    node.setData(0, Qt.ItemDataRole.UserRole, key)
                    node.setData(0, Qt.ItemDataRole.UserRole + 2, key)
                    for row in group["rows"]:
                        self._item(node, row, "article")
        self.restore_expansion(self.expanded)
        self.select_target(selected)
        self.tree.blockSignals(False)
        self.filter_tree(self.search.text())

    def _item(self, parent, row, kind, nodes=None):
        title = row["title"]
        if kind == "article" and self.universe_id is None:
            title += " · " + self.universe_names.get(row["universe_id"], "")
        item = QTreeWidgetItem(parent, [title])
        item.setToolTip(0, title)
        item.setData(0, Qt.ItemDataRole.UserRole, (kind, row["id"]))
        item.setData(
            0,
            Qt.ItemDataRole.UserRole + 1,
            " ".join([row["title"], row.get("content", ""), *row.get("tags", [])]).casefold(),
        )
        if nodes is not None:
            nodes[row["id"]] = item
        return item

    def expansion_state(self):
        return {
            item.data(0, Qt.ItemDataRole.UserRole + 2)
            for item in self.items()
            if item.isExpanded() and item.data(0, Qt.ItemDataRole.UserRole + 2)
        }

    def items(self):
        def walk(parent):
            for i in range(parent.childCount()):
                child = parent.child(i)
                yield child
                yield from walk(child)

        return walk(self.tree.invisibleRootItem())

    def restore_expansion(self, state):
        for item in self.items():
            item.setExpanded(item.data(0, Qt.ItemDataRole.UserRole + 2) in state)

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
        item = find(self.tree.invisibleRootItem()) if target else None
        self.tree.setCurrentItem(item)
        if item:
            parent = item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()
        self.tree.blockSignals(False)

    def filter_tree(self, query: str):
        needle = query.casefold().strip()
        if needle and self.search_expanded is None:
            self.search_expanded = self.expansion_state()
        elif not needle and self.search_expanded is not None:
            self.restore_expansion(self.search_expanded)
            self.search_expanded = None

        def visit(item):
            child_matches = False
            for index in range(item.childCount()):
                child_matches = visit(item.child(index)) or child_matches
            target = item.data(0, Qt.ItemDataRole.UserRole)
            own_match = needle in (
                item.data(0, Qt.ItemDataRole.UserRole + 1) or item.text(0).casefold()
            )
            matches = (
                not needle or child_matches or (target and target[0] != "category" and own_match)
            )
            if needle and child_matches:
                item.setExpanded(True)
            item.setHidden(not matches)
            return matches

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
