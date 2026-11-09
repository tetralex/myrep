"""Startpunkt der App."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtCore import QLocale
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from app.config import APP_NAME, ORGANIZATION, resource_path, user_data_dir
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

    data_dir = user_data_dir()
    db = Database(data_dir / "wissen.db", data_dir / "anhaenge")
    if db.is_empty() and not db.get_setting("seeded", False):
        seed(db)
        db.set_setting("seeded", True)

    ctx = AppContext(db)
    mode = db.get_setting("theme", "system")
    ctx.dark = theme.system_prefers_dark() if mode == "system" else mode == "dark"
    theme.apply_palette(app, ctx.dark)
    app.setStyleSheet(theme.stylesheet(ctx.dark, int(db.get_setting("font_size", 11))))

    win = MainWindow(ctx)
    win.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
