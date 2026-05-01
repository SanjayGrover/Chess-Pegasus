"""
ChessMaster Pro - Main Entry Point
===================================
A feature-rich Chess GUI with Stockfish integration, move classification,
game import, and puzzle solving.

Requirements:
    pip install PyQt6 python-chess requests

Usage:
    python main.py
"""

import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QStatusBar, QDialog,
    QLineEdit, QFormLayout, QDialogButtonBox, QSpinBox
)
from PyQt6.QtCore import Qt, QSettings, QSize
from PyQt6.QtGui import QIcon, QFont, QPalette, QColor, QAction


# ── App-wide config ────────────────────────────────────────────────────────────

APP_NAME    = "ChessMaster Pro"
APP_VERSION = "1.0.0"
ORG_NAME    = "ChessMasterPro"

# Default Stockfish path — user can override in Settings
DEFAULT_STOCKFISH_PATH = r"C:\stockfish\stockfish.exe"


# ── Placeholder tab widgets (will be replaced in later parts) ──────────────────

class PlaceholderTab(QWidget):
    """Temporary placeholder shown until the real module is built."""

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel("♟")
        icon_label.setFont(QFont("Segoe UI", 64))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("color: #c9a96e;")

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #e8d5b0;")

        desc_label = QLabel(description)
        desc_label.setFont(QFont("Segoe UI", 11))
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #8a7a5a; max-width: 400px;")

        layout.addWidget(icon_label)
        layout.addSpacing(12)
        layout.addWidget(title_label)
        layout.addSpacing(8)
        layout.addWidget(desc_label)


# ── Settings Dialog ────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """Lets the user configure Stockfish path and default engine depth."""

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setStyleSheet(parent.styleSheet() if parent else "")

        form = QFormLayout()
        form.setSpacing(14)

        # Stockfish path
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(
            self.settings.value("stockfish_path", DEFAULT_STOCKFISH_PATH)
        )
        self.path_edit.setPlaceholderText(r"C:\stockfish\stockfish.exe")
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_stockfish)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        form.addRow("Stockfish Path:", path_row)

        # Default depth
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 30)
        self.depth_spin.setValue(int(self.settings.value("default_depth", 15)))
        self.depth_spin.setSuffix("  (plies)")
        form.addRow("Default Engine Depth:", self.depth_spin)

        # Username defaults
        self.chesscom_user = QLineEdit(
            self.settings.value("chesscom_username", "")
        )
        self.chesscom_user.setPlaceholderText("your chess.com username")
        form.addRow("Chess.com Username:", self.chesscom_user)

        self.lichess_user = QLineEdit(
            self.settings.value("lichess_username", "")
        )
        self.lichess_user.setPlaceholderText("your lichess username")
        form.addRow("Lichess Username:", self.lichess_user)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(form)
        main_layout.addSpacing(12)
        main_layout.addWidget(buttons)

    def _browse_stockfish(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Stockfish Executable",
            os.path.dirname(self.path_edit.text()),
            "Executable (*.exe);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def _save_and_accept(self):
        self.settings.setValue("stockfish_path",   self.path_edit.text())
        self.settings.setValue("default_depth",    self.depth_spin.value())
        self.settings.setValue("chesscom_username", self.chesscom_user.text().strip())
        self.settings.setValue("lichess_username",  self.lichess_user.text().strip())
        self.accept()


# ── Main Window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self._apply_theme()
        self._build_ui()
        self._build_menu()
        self._validate_stockfish()

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        """Dark chessboard-inspired colour scheme."""
        self.setStyleSheet("""
            /* ── Global ──────────────────────────────────────────────── */
            QMainWindow, QDialog, QWidget {
                background-color: #1a1a1a;
                color: #e8d5b0;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }

            /* ── Tab Bar ─────────────────────────────────────────────── */
            QTabWidget::pane {
                border: 1px solid #3a3020;
                background: #1a1a1a;
            }
            QTabBar::tab {
                background: #252018;
                color: #8a7a5a;
                padding: 10px 28px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
                font-weight: 600;
                letter-spacing: 0.5px;
            }
            QTabBar::tab:selected {
                background: #2e2818;
                color: #c9a96e;
                border-bottom: 2px solid #c9a96e;
            }
            QTabBar::tab:hover:!selected {
                background: #2a2218;
                color: #b09050;
            }

            /* ── Buttons ─────────────────────────────────────────────── */
            QPushButton {
                background-color: #2e2818;
                color: #c9a96e;
                border: 1px solid #5a4a2a;
                border-radius: 5px;
                padding: 7px 18px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3a3020;
                border-color: #c9a96e;
            }
            QPushButton:pressed {
                background-color: #c9a96e;
                color: #1a1a1a;
            }
            QPushButton:disabled {
                color: #4a4030;
                border-color: #3a3020;
            }

            /* ── Inputs ──────────────────────────────────────────────── */
            QLineEdit, QSpinBox, QComboBox {
                background-color: #252018;
                color: #e8d5b0;
                border: 1px solid #5a4a2a;
                border-radius: 4px;
                padding: 5px 8px;
                selection-background-color: #c9a96e;
                selection-color: #1a1a1a;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #c9a96e;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background: #3a3020;
                border: none;
                width: 18px;
            }

            /* ── Menus ───────────────────────────────────────────────── */
            QMenuBar {
                background-color: #141414;
                color: #c9a96e;
                border-bottom: 1px solid #3a3020;
                padding: 2px 0;
            }
            QMenuBar::item:selected {
                background: #2e2818;
            }
            QMenu {
                background-color: #1e1e1e;
                color: #e8d5b0;
                border: 1px solid #3a3020;
            }
            QMenu::item:selected {
                background-color: #3a3020;
                color: #c9a96e;
            }
            QMenu::separator {
                height: 1px;
                background: #3a3020;
                margin: 4px 0;
            }

            /* ── Status Bar ──────────────────────────────────────────── */
            QStatusBar {
                background-color: #141414;
                color: #6a5a3a;
                border-top: 1px solid #2a2010;
                font-size: 11px;
            }

            /* ── Dialog buttons ──────────────────────────────────────── */
            QDialogButtonBox QPushButton {
                min-width: 80px;
            }

            /* ── Scrollbars ───────────────────────────────────────────── */
            QScrollBar:vertical {
                background: #1a1a1a;
                width: 10px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #3a3020;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #5a4a2a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }

            /* ── Labels ──────────────────────────────────────────────── */
            QLabel {
                color: #e8d5b0;
            }
            QFormLayout QLabel {
                color: #8a7a5a;
            }
        """)

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setMinimumSize(QSize(1100, 760))
        self.resize(1280, 860)

        # Central tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # ── Tab 1: Play ──────────────────────────────────────────────────────
        self.play_tab = PlaceholderTab(
            "Play vs Engine",
            "Set your desired depth, choose your colour, and play a full game\n"
            "against Stockfish. Coming in Part 2."
        )
        self.tabs.addTab(self.play_tab, "♟  Play")

        # ── Tab 2: Analyze ───────────────────────────────────────────────────
        self.analyze_tab = PlaceholderTab(
            "Game Analysis",
            "Load a PGN and get a full move-by-move breakdown with\n"
            "Brilliant ✨, Great !, Mistake ?, Blunder ?? classifications.\n"
            "Coming in Part 3 & 4."
        )
        self.tabs.addTab(self.analyze_tab, "🔍  Analyze")

        # ── Tab 3: Import ────────────────────────────────────────────────────
        self.import_tab = PlaceholderTab(
            "Import Games",
            "Fetch your games directly from chess.com or lichess.org\n"
            "by username, then analyze them instantly. Coming in Part 5."
        )
        self.tabs.addTab(self.import_tab, "⬇  Import")

        # ── Tab 4: Puzzles ───────────────────────────────────────────────────
        self.puzzle_tab = PlaceholderTab(
            "Puzzle Training",
            "Solve Lichess-powered puzzles filtered by rating range.\n"
            "Get hints and explanations. Coming in Part 6."
        )
        self.tabs.addTab(self.puzzle_tab, "🧩  Puzzles")

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._refresh_status()

    def _build_menu(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("File")

        open_pgn = QAction("Open PGN…", self)
        open_pgn.setShortcut("Ctrl+O")
        open_pgn.triggered.connect(self._open_pgn)
        file_menu.addAction(open_pgn)

        file_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Settings
        settings_menu = menubar.addMenu("Settings")
        prefs_action = QAction("Preferences…", self)
        prefs_action.setShortcut("Ctrl+,")
        prefs_action.triggered.connect(self._open_settings)
        settings_menu.addAction(prefs_action)

        # Help
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _refresh_status(self):
        sf_path = self.settings.value("stockfish_path", DEFAULT_STOCKFISH_PATH)
        depth   = self.settings.value("default_depth", 15)
        exists  = "✔ Engine ready" if os.path.isfile(sf_path) else "✘ Engine not found"
        self.status.showMessage(
            f"{exists}   |   Default depth: {depth}   |   {sf_path}"
        )

    def _validate_stockfish(self):
        sf_path = self.settings.value("stockfish_path", DEFAULT_STOCKFISH_PATH)
        if not os.path.isfile(sf_path):
            QMessageBox.warning(
                self,
                "Stockfish Not Found",
                f"Stockfish was not found at:\n{sf_path}\n\n"
                "Please go to Settings → Preferences and set the correct path.",
            )

    def _open_pgn(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PGN File", "", "PGN Files (*.pgn);;All Files (*)"
        )
        if path:
            # Will be wired to the analyzer tab in Part 3
            self.status.showMessage(f"Loaded PGN: {path}", 4000)
            self.tabs.setCurrentIndex(1)   # Switch to Analyze tab

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, parent=self)
        if dlg.exec():
            self._refresh_status()

    def _show_about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME} v{APP_VERSION}</h3>"
            "<p>A powerful chess GUI with Stockfish engine integration,<br>"
            "chess.com-style move classifications, game import,<br>"
            "and Lichess puzzle training.</p>"
            "<p>Built with PyQt6 + python-chess.</p>"
        )


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)

    # High-DPI support (PyQt6 handles this by default, but explicit is good)
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()