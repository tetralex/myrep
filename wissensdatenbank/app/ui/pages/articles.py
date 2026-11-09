"""Wissensartikel: Kategorien, Liste, Ansicht, Editor, Versionen, Anhänge."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
    QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..theme import markdown_css
from ..widgets import (
    AppContext, MarkdownView, Page, confirm, hbox, info, markdown_to_pdf, muted, warn,
)

ROLE_KIND = Qt.UserRole
ROLE_ID = Qt.UserRole + 1


def category_combo(db, combo: QComboBox, selected: int | None = None) -> None:
    combo.clear()
    combo.addItem("— ohne Kategorie —", None)
    for c in db.categories():
        combo.addItem(db.category_path(c["id"]), c["id"])
    # alphabetisch nach Pfad sortieren
    items = sorted([(combo.itemText(i), combo.itemData(i)) for i in range(1, combo.count())],
                   key=lambda x: x[0].lower())
    combo.clear()
    combo.addItem("— ohne Kategorie —", None)
    for text, data in items:
        combo.addItem(text, data)
    if selected is not None:
        idx = combo.findData(selected)
        if idx >= 0:
            combo.setCurrentIndex(idx)


# ---------------------------------------------------------------- Editor
class ArticleEditor(QDialog):
    def __init__(self, ctx: AppContext, article_id: int | None = None, category_id: int | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.db = ctx.db
        self.article_id = article_id
        self.setWindowTitle("Artikel bearbeiten" if article_id else "Neuer Artikel")
        self.resize(1200, 780)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)

        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Worum geht's?")
        self.category = QComboBox()
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Tags, durch Komma getrennt – z. B. R290, Wärmepumpe, Praxis")
        form.addRow("Titel", self.title)
        form.addRow("Kategorie", self.category)
        form.addRow("Tags", self.tags)
        lay.addLayout(form)

        bar = QHBoxLayout()
        for label, tip, fn in [
            ("H", "Überschrift", lambda: self._prefix("## ")),
            ("B", "Fett", lambda: self._wrap("**")),
            ("I", "Kursiv", lambda: self._wrap("*")),
            ("•", "Aufzählung", lambda: self._prefix("- ")),
            ("1.", "Nummerierung", lambda: self._prefix("1. ")),
            ("☐", "Checkliste", lambda: self._prefix("- [ ] ")),
            ("▦", "Tabelle", self._table),
            ("🔗", "Link auf Artikel", self._article_link),
            ("🖼", "Bild einfügen", self._image),
        ]:
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.setMinimumWidth(36)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(muted("Markdown – Vorschau rechts", wrap=False))
        lay.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Schreib los … (Markdown wird unterstützt)")
        self.editor.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace;")
        self.preview = MarkdownView(ctx)
        split.addWidget(self.editor)
        split.addWidget(self.preview)
        split.setSizes([600, 600])
        lay.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_preview)
        self.editor.textChanged.connect(self._timer.start)

        buttons = QDialogButtonBox()
        save = buttons.addButton("Speichern", QDialogButtonBox.AcceptRole)
        save.setObjectName("Primary")
        buttons.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        QShortcut(QKeySequence.Save, self, activated=self._save)

        row = self.db.article(article_id) if article_id else None
        category_combo(self.db, self.category, row["category_id"] if row else category_id)
        if row:
            self.title.setText(row["title"])
            self.tags.setText(row["tags"])
            self.editor.setPlainText(row["body"])
        self._update_preview()

    def _update_preview(self) -> None:
        self.preview.set_markdown(self.editor.toPlainText())

    def _wrap(self, marker: str) -> None:
        cur = self.editor.textCursor()
        text = cur.selectedText() or "Text"
        cur.insertText(f"{marker}{text}{marker}")

    def _prefix(self, prefix: str) -> None:
        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.StartOfLine)
        cur.insertText(prefix)

    def _table(self) -> None:
        self.editor.insertPlainText("\n| Spalte 1 | Spalte 2 | Spalte 3 |\n|---|---|---|\n|  |  |  |\n")

    def _article_link(self) -> None:
        titles = [a["title"] for a in self.db.articles()]
        title, ok = QInputDialog.getItem(self, "Link auf Artikel", "Artikel:", titles, 0, False)
        if ok and title:
            self.editor.insertPlainText(f"[{title}](<artikel:{title}>)")

    def _image(self) -> None:
        if self.article_id is None:
            if not self._save(close=False):
                return
        path, _ = QFileDialog.getOpenFileName(self, "Bild einfügen", "",
                                              "Bilder (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if path:
            att = self.db.add_attachment(path, article_id=self.article_id)
            self.editor.insertPlainText(f"\n![{att['filename']}]({att['stored_name']})\n")

    def _save(self, close: bool = True) -> bool:
        title = self.title.text().strip()
        if not title:
            warn(self, "Titel fehlt", "Gib dem Artikel bitte einen Titel. 🙂")
            return False
        dup = self.db.find_article_by_title(title)
        if dup and dup["id"] != self.article_id:
            warn(self, "Titel gibt's schon", f"Es gibt bereits einen Artikel „{title}“.")
            return False
        self.article_id = self.db.save_article(title, self.editor.toPlainText(), self.category.currentData(),
                                               self.tags.text(), self.article_id)
        self.ctx.notify("article")
        if close:
            self.accept()
        return True


# ---------------------------------------------------------------- Versionen
class VersionDialog(QDialog):
    def __init__(self, ctx: AppContext, article_id: int, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.article_id = article_id
        self.setWindowTitle("Versionsverlauf")
        self.resize(1000, 640)
        lay = QHBoxLayout(self)
        self.list = QListWidget()
        self.view = MarkdownView(ctx)
        left = QVBoxLayout()
        left.addWidget(QLabel("Frühere Fassungen"))
        left.addWidget(self.list, 1)
        self.restore = QPushButton("↩️  Diese Version wiederherstellen")
        self.restore.setObjectName("Primary")
        self.restore.clicked.connect(self._restore)
        left.addWidget(self.restore)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(320)
        lay.addWidget(lw)
        lay.addWidget(self.view, 1)
        self.versions = ctx.db.versions(article_id)
        for v in self.versions:
            item = QListWidgetItem(f"{v['saved_at'].replace('T', '  ')}\n{v['title']}")
            item.setData(Qt.UserRole, v["id"])
            self.list.addItem(item)
        self.list.currentRowChanged.connect(self._show)
        if self.versions:
            self.list.setCurrentRow(0)
        else:
            self.view.set_markdown("*Noch keine früheren Versionen – die entstehen beim Bearbeiten.*")
            self.restore.setEnabled(False)

    def _show(self, row: int) -> None:
        if 0 <= row < len(self.versions):
            v = self.versions[row]
            self.view.set_markdown(f"# {v['title']}\n\n{v['body']}")

    def _restore(self) -> None:
        item = self.list.currentItem()
        if item and confirm(self, "Wiederherstellen", "Aktuelle Fassung durch diese Version ersetzen?\n"
                                                       "(Die aktuelle Fassung bleibt im Verlauf erhalten.)"):
            self.ctx.db.restore_version(item.data(Qt.UserRole))
            self.ctx.notify("article")
            self.accept()


# ---------------------------------------------------------------- Seite
class ArticlesPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, "📚 Wissensartikel", "Dein Fachwissen – sortiert, verlinkt und durchsuchbar.")
        self.current_id: int | None = None

        split = QSplitter(Qt.Horizontal)
        self.root.addWidget(split, 1)

        # links: Kategorien
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(lambda *_: self._load_list())
        ll.addWidget(self.tree, 1)
        add_cat = QPushButton("＋ Kategorie")
        add_cat.clicked.connect(lambda: self._new_category(None))
        ll.addWidget(add_cat)
        split.addWidget(left)

        # Mitte: Liste
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 Filtern …")
        self.filter.textChanged.connect(self._load_list)
        self.tag_combo = QComboBox()
        self.tag_combo.currentIndexChanged.connect(self._load_list)
        ml.addWidget(self.filter)
        ml.addWidget(self.tag_combo)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        ml.addWidget(self.list, 1)
        new_btn = QPushButton("＋ Neuer Artikel")
        new_btn.setObjectName("Primary")
        new_btn.clicked.connect(self._new_article)
        ml.addWidget(new_btn)
        split.addWidget(mid)

        # rechts: Ansicht
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.h_title = QLabel("Wähl einen Artikel aus 👈")
        self.h_title.setObjectName("SectionTitle")
        self.h_title.setWordWrap(True)
        self.h_meta = muted("")
        rl.addWidget(self.h_title)
        rl.addWidget(self.h_meta)
        self.btn_fav = QPushButton("☆ Favorit")
        self.btn_edit = QPushButton("✏️ Bearbeiten")
        self.btn_hist = QPushButton("🕑 Verlauf")
        self.btn_pdf = QPushButton("📄 PDF")
        self.btn_link = QPushButton("🔗 Verknüpfen")
        self.btn_del = QPushButton("🗑")
        self.btn_del.setObjectName("Danger")
        self.btn_del.setToolTip("Artikel löschen")
        self.btn_fav.clicked.connect(self._toggle_fav)
        self.btn_edit.clicked.connect(self._edit)
        self.btn_hist.clicked.connect(self._history)
        self.btn_pdf.clicked.connect(self._pdf)
        self.btn_link.clicked.connect(self._link)
        self.btn_del.clicked.connect(self._delete)
        self.action_buttons = [self.btn_fav, self.btn_edit, self.btn_hist, self.btn_pdf, self.btn_link, self.btn_del]
        rl.addLayout(hbox(*self.action_buttons, None))
        self.view = MarkdownView(ctx)
        self.view.article_link.connect(self._open_by_title)
        rl.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        links_box = QVBoxLayout()
        links_box.addWidget(QLabel("🔗 Verknüpfte Artikel"))
        self.links = QListWidget()
        self.links.setMaximumHeight(130)
        self.links.itemDoubleClicked.connect(lambda it: self.show_article(it.data(Qt.UserRole)))
        self.links.setContextMenuPolicy(Qt.CustomContextMenu)
        self.links.customContextMenuRequested.connect(self._links_menu)
        links_box.addWidget(self.links)
        att_box = QVBoxLayout()
        att_head = QHBoxLayout()
        att_head.addWidget(QLabel("📎 Anhänge"))
        att_head.addStretch(1)
        add_att = QToolButton()
        add_att.setText("＋")
        add_att.setToolTip("Datei anhängen")
        add_att.clicked.connect(self._add_attachment)
        att_head.addWidget(add_att)
        att_box.addLayout(att_head)
        self.atts = QListWidget()
        self.atts.setMaximumHeight(130)
        self.atts.itemDoubleClicked.connect(self._open_attachment)
        self.atts.setContextMenuPolicy(Qt.CustomContextMenu)
        self.atts.customContextMenuRequested.connect(self._att_menu)
        att_box.addWidget(self.atts)
        bottom.addLayout(links_box, 1)
        bottom.addLayout(att_box, 1)
        rl.addLayout(bottom)
        split.addWidget(right)
        split.setSizes([240, 300, 760])

        ctx.changed.connect(self._on_changed)
        self._set_enabled(False)
        self.refresh()

    # ----------------------------------------------------------- Laden
    def _on_changed(self, kind: str) -> None:
        if kind in ("article", "category", "all"):
            self.refresh()

    def refresh(self) -> None:
        current = self._current_tree_key()
        self.tree.blockSignals(True)
        self.tree.clear()
        all_item = QTreeWidgetItem(["📚 Alle Artikel"])
        all_item.setData(0, ROLE_KIND, "all")
        fav_item = QTreeWidgetItem(["⭐ Favoriten"])
        fav_item.setData(0, ROLE_KIND, "fav")
        self.tree.addTopLevelItem(all_item)
        self.tree.addTopLevelItem(fav_item)
        cats = self.db.categories()
        items: dict[int, QTreeWidgetItem] = {}
        for c in cats:
            it = QTreeWidgetItem([f"📁 {c['name']}"])
            it.setData(0, ROLE_KIND, "cat")
            it.setData(0, ROLE_ID, c["id"])
            items[c["id"]] = it
        for c in cats:
            parent = items.get(c["parent_id"]) if c["parent_id"] else None
            (parent.addChild if parent else self.tree.addTopLevelItem)(items[c["id"]])
        none_item = QTreeWidgetItem(["🗂 Ohne Kategorie"])
        none_item.setData(0, ROLE_KIND, "none")
        self.tree.addTopLevelItem(none_item)
        self.tree.expandAll()
        self._select_tree_key(current or ("all", None))
        self.tree.blockSignals(False)

        tag = self.tag_combo.currentData()
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("🏷 Alle Tags", None)
        for t in self.db.all_tags():
            self.tag_combo.addItem(f"🏷 {t}", t)
        idx = self.tag_combo.findData(tag)
        self.tag_combo.setCurrentIndex(max(idx, 0))
        self.tag_combo.blockSignals(False)
        self._load_list()
        if self.current_id and self.db.article(self.current_id):
            self._render(self.current_id)
        else:
            self._clear_view()

    def _current_tree_key(self):
        it = self.tree.currentItem()
        if not it:
            return None
        return it.data(0, ROLE_KIND), it.data(0, ROLE_ID)

    def _select_tree_key(self, key) -> None:
        def walk(item):
            if (item.data(0, ROLE_KIND), item.data(0, ROLE_ID)) == key:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None
        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found:
                self.tree.setCurrentItem(found)
                return
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _load_list(self) -> None:
        key = self._current_tree_key() or ("all", None)
        kind, cid = key
        tag = self.tag_combo.currentData()
        if kind == "fav":
            rows = self.db.articles(favorites_only=True, tag=tag)
        elif kind == "cat":
            rows = self.db.articles(category_id=cid, tag=tag)
        else:
            rows = self.db.articles(tag=tag)
            if kind == "none":
                rows = [r for r in rows if r["category_id"] is None]
        flt = self.filter.text().strip().lower()
        if flt:
            rows = [r for r in rows if flt in r["title"].lower() or flt in r["tags"].lower()]
        self.list.blockSignals(True)
        self.list.clear()
        for r in rows:
            it = QListWidgetItem(("⭐ " if r["favorite"] else "📄 ") + r["title"])
            it.setData(Qt.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == self.current_id:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if not rows:
            it = QListWidgetItem("Hier ist noch nichts – leg einen Artikel an oder importier was! 📥")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def _on_select(self, item, _prev=None) -> None:
        if item and item.data(Qt.UserRole):
            self._render(item.data(Qt.UserRole))

    def show_article(self, article_id: int) -> None:
        if not self.db.article(article_id):
            return
        self.filter.clear()
        self.tag_combo.setCurrentIndex(0)
        self._select_tree_key(("all", None))
        self._load_list()
        self._render(article_id)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == article_id:
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)
                break

    def _render(self, article_id: int) -> None:
        a = self.db.article(article_id)
        if not a:
            self._clear_view()
            return
        self.current_id = article_id
        self.db.mark_viewed(article_id)
        self.h_title.setText(a["title"])
        meta = []
        if a["category_id"]:
            meta.append("📁 " + self.db.category_path(a["category_id"]))
        if a["tags"]:
            meta.append("🏷 " + a["tags"])
        meta.append("🕑 " + a["updated"].replace("T", " ")[:16])
        if a["source"] and a["source"] != "Startinhalt":
            meta.append("📥 " + a["source"])
        self.h_meta.setText("   ·   ".join(meta))
        self.btn_fav.setText("★ Favorit" if a["favorite"] else "☆ Favorit")
        self.view.set_markdown(a["body"])
        self.links.clear()
        for l in self.db.links(article_id):
            it = QListWidgetItem("📄 " + l["title"])
            it.setData(Qt.UserRole, l["id"])
            self.links.addItem(it)
        self.atts.clear()
        for att in self.db.attachments(article_id=article_id):
            it = QListWidgetItem("📎 " + att["filename"])
            it.setData(Qt.UserRole, att["id"])
            it.setData(Qt.UserRole + 1, att["stored_name"])
            self.atts.addItem(it)
        self._set_enabled(True)

    def _clear_view(self) -> None:
        self.current_id = None
        self.h_title.setText("Wähl einen Artikel aus 👈")
        self.h_meta.setText("")
        self.view.set_markdown("")
        self.links.clear()
        self.atts.clear()
        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        for b in self.action_buttons:
            b.setEnabled(on)

    # ----------------------------------------------------------- Aktionen
    def _open_by_title(self, title: str) -> None:
        a = self.db.find_article_by_title(QUrl.fromPercentEncoding(title.encode()))
        if a:
            self.show_article(a["id"])
        else:
            info(self, "Nicht gefunden", f"Den Artikel „{title}“ gibt's (noch) nicht.")

    def _new_article(self) -> None:
        key = self._current_tree_key()
        cid = key[1] if key and key[0] == "cat" else None
        dlg = ArticleEditor(self.ctx, None, cid, self)
        if dlg.exec() and dlg.article_id:
            self.show_article(dlg.article_id)

    def _edit(self) -> None:
        if self.current_id:
            dlg = ArticleEditor(self.ctx, self.current_id, None, self)
            dlg.exec()
            self.refresh()

    def _toggle_fav(self) -> None:
        if self.current_id:
            self.db.toggle_favorite(self.current_id)
            self.ctx.notify("article")

    def _history(self) -> None:
        if self.current_id:
            VersionDialog(self.ctx, self.current_id, self).exec()

    def _pdf(self) -> None:
        a = self.db.article(self.current_id) if self.current_id else None
        if not a:
            return
        safe = "".join(ch for ch in a["title"] if ch.isalnum() or ch in " -_").strip() or "Artikel"
        path, _ = QFileDialog.getSaveFileName(self, "Als PDF exportieren", f"{safe}.pdf", "PDF (*.pdf)")
        if path:
            markdown_to_pdf(a["body"], a["title"], path, markdown_css(False))
            info(self, "Fertig", "PDF gespeichert. 📄")

    def _link(self) -> None:
        if not self.current_id:
            return
        others = [a for a in self.db.articles() if a["id"] != self.current_id]
        titles = [a["title"] for a in others]
        title, ok = QInputDialog.getItem(self, "Artikel verknüpfen", "Mit welchem Artikel?", titles, 0, False)
        if ok and title:
            target = next(a for a in others if a["title"] == title)
            self.db.link_articles(self.current_id, target["id"])
            self._render(self.current_id)

    def _links_menu(self, pos) -> None:
        it = self.links.itemAt(pos)
        if not it or not self.current_id:
            return
        menu = QMenu(self)
        menu.addAction("Öffnen", lambda: self.show_article(it.data(Qt.UserRole)))
        menu.addAction("Verknüpfung entfernen", lambda: (
            self.db.unlink_articles(self.current_id, it.data(Qt.UserRole)), self._render(self.current_id)))
        menu.exec(self.links.mapToGlobal(pos))

    def _delete(self) -> None:
        a = self.db.article(self.current_id) if self.current_id else None
        if a and confirm(self, "Löschen", f"Artikel „{a['title']}“ wirklich löschen?"):
            self.db.delete_article(a["id"])
            self.current_id = None
            self.ctx.notify("article")

    def _add_attachment(self) -> None:
        if not self.current_id:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Dateien anhängen")
        for p in paths:
            self.db.add_attachment(p, article_id=self.current_id)
        if paths:
            self._render(self.current_id)

    def _open_attachment(self, item) -> None:
        path = Path(self.db.attachments_dir) / item.data(Qt.UserRole + 1)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _att_menu(self, pos) -> None:
        it = self.atts.itemAt(pos)
        if not it:
            return
        menu = QMenu(self)
        menu.addAction("Öffnen", lambda: self._open_attachment(it))
        menu.addAction("Speichern unter …", lambda: self._save_attachment(it))
        menu.addAction("Entfernen", lambda: self._remove_attachment(it))
        menu.exec(self.atts.mapToGlobal(pos))

    def _save_attachment(self, it) -> None:
        import shutil
        src = Path(self.db.attachments_dir) / it.data(Qt.UserRole + 1)
        name = it.text().replace("📎 ", "")
        path, _ = QFileDialog.getSaveFileName(self, "Speichern unter", name)
        if path:
            shutil.copy2(src, path)

    def _remove_attachment(self, it) -> None:
        if confirm(self, "Anhang entfernen", "Anhang wirklich entfernen?"):
            self.db.delete_attachment(it.data(Qt.UserRole))
            self._render(self.current_id)

    # ----------------------------------------------------------- Kategorien
    def _tree_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        menu = QMenu(self)
        menu.addAction("＋ Neue Kategorie", lambda: self._new_category(None))
        if it and it.data(0, ROLE_KIND) == "cat":
            cid = it.data(0, ROLE_ID)
            menu.addAction("＋ Unterkategorie", lambda: self._new_category(cid))
            menu.addAction("✏️ Umbenennen", lambda: self._rename_category(cid))
            menu.addAction("🗑 Löschen", lambda: self._delete_category(cid))
        menu.exec(self.tree.mapToGlobal(pos))

    def _new_category(self, parent_id: int | None) -> None:
        name, ok = QInputDialog.getText(self, "Neue Kategorie", "Name:")
        if ok and name.strip():
            self.db.add_category(name, parent_id, sort=100)
            self.ctx.notify("category")

    def _rename_category(self, cid: int) -> None:
        row = self.db.one("SELECT name FROM categories WHERE id = ?", (cid,))
        name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name:", text=row["name"] if row else "")
        if ok and name.strip():
            self.db.rename_category(cid, name)
            self.ctx.notify("category")

    def _delete_category(self, cid: int) -> None:
        if confirm(self, "Kategorie löschen",
                   "Kategorie samt Unterkategorien löschen?\nDie Artikel bleiben erhalten (ohne Kategorie)."):
            for sub in self.db._category_descendants(cid):
                self.db.conn.execute("UPDATE articles SET category_id = NULL WHERE category_id = ?", (sub,))
            self.db.delete_category(cid)
            self.ctx.notify("category")
