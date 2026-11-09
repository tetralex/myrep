"""Startpunkt der App."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtCore import QLocale
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from PySide6.QtWidgets import QMessageBox

    from app.config import APP_NAME, ORGANIZATION, data_dir, resource_path, user_data_dir
    from app.core import local_config, package
    from app.core.db import Database
    from app.data.seed import seed
    from app.ui import theme
    from app.ui.main_window import MainWindow
    from app.ui.widgets import AppContext

    if sys.platform == "win32":  # eigenes Taskleisten-Icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORGANIZATION}.{APP_NAME}")
        except Exception:
            pass

    QLocale.setDefault(QLocale(QLocale.German, QLocale.Austria))
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    icon = resource_path("assets/icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    folder = data_dir()
    while local_config.get("data_dir") and not folder.is_dir():
        box = QMessageBox(QMessageBox.Warning, APP_NAME,
                          f"Der zentrale Speicherort ist nicht erreichbar:\n{folder}\n\n"
                          "Netzlaufwerk verbunden? VPN aktiv?")
        retry = box.addButton("Erneut versuchen", QMessageBox.AcceptRole)
        local = box.addButton("Diesmal lokal starten", QMessageBox.ActionRole)
        box.addButton("Beenden", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is retry:
            continue
        if box.clickedButton() is local:
            folder = user_data_dir()
            break
        return 0
    try:
        db = Database(folder / "wissen.db", folder / "anhaenge")
    except Exception as exc:
        QMessageBox.critical(None, APP_NAME, f"Die Datenbank konnte nicht geöffnet werden:\n{exc}")
        return 1
    if db.is_empty() and not db.get_setting("seeded", False):
        seed(db)
        db.set_setting("seeded", True)
    pending = local_config.get("pending_merge")
    if pending:
        local_config.set("pending_merge", None)
        try:
            package.import_package(db, pending)
        except Exception:
            pass

    ctx = AppContext(db)
    mode = db.get_setting("theme", "system")
    ctx.dark = theme.system_prefers_dark() if mode == "system" else mode == "dark"
    theme.apply_palette(app, ctx.dark)
    app.setStyleSheet(theme.stylesheet(ctx.dark, int(db.get_setting("font_size", 11))))

    win = MainWindow(ctx)
    win.show()
    if local_config.get("assistant_at_start"):
        win.open_edge()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
