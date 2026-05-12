"""
ChessMaster Pro - Main Entry Point
===================================
Wires all tabs together:
  ♟  Play     — play vs Stockfish       (play_tab.py)
  🔍 Analyze  — load PGN + classify     (analyze_tab.py)
  ⬇  Import   — chess.com / lichess     (import_tab.py)
  🧩 Puzzles  — Lichess puzzle training  (puzzle_tab.py)

Run:
    python main.py
"""

import sys
import os

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget,
    QMessageBox, QStatusBar, QFileDialog,
    QDialog, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QSpinBox,
    QDialogButtonBox, QPushButton
)
from PyQt6.QtCore import Qt, QSettings, QSize
from PyQt6.QtGui  import QAction

from engine      import ChessEngine
from play_tab    import PlayTab
from analyze_tab import AnalyzeTab
from import_tab  import ImportTab
from puzzle_tab  import PuzzleTab

APP_NAME    = "ChessMasterPro"
APP_VERSION = "1.0.0"
ORG_NAME    = "ChessMasterPro"
DEFAULT_SF  = r"C:\stockfish\stockfish.exe"


# ── Settings Dialog ────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(500)

        form = QFormLayout()
        form.setSpacing(14)

        # Stockfish path
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(
            self.settings.value("stockfish_path", DEFAULT_SF)
        )
        browse = QPushButton("Browse…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse)
        form.addRow("Stockfish Path:", path_row)

        # Default depth
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 30)
        self.depth_spin.setValue(int(self.settings.value("default_depth", 15)))
        self.depth_spin.setSuffix("  plies")
        form.addRow("Default Depth:", self.depth_spin)

        # Usernames
        self.cc_user = QLineEdit(self.settings.value("chesscom_username", ""))
        self.cc_user.setPlaceholderText("your chess.com username")
        form.addRow("Chess.com Username:", self.cc_user)

        self.lc_user = QLineEdit(self.settings.value("lichess_username", ""))
        self.lc_user.setPlaceholderText("your lichess username")
        form.addRow("Lichess Username:", self.lc_user)

        # Buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addSpacing(8)
        lay.addWidget(btns)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Stockfish Executable",
            os.path.dirname(self.path_edit.text()),
            "Executable (*.exe);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def _save(self):
        self.settings.setValue("stockfish_path",    self.path_edit.text().strip())
        self.settings.setValue("default_depth",     self.depth_spin.value())
        self.settings.setValue("chesscom_username",  self.cc_user.text().strip())
        self.settings.setValue("lichess_username",   self.lc_user.text().strip())
        self.accept()


# ── Main Window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self._engine  : ChessEngine | None = None

        self._apply_theme()
        self._open_engine()
        self._build_ui()
        self._build_menu()
        self._refresh_status()

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet("""
            /* ── Global ─────────────────────────────────────────────────── */
            QMainWindow, QDialog, QWidget {
                background-color: #1a1a1a;
                color: #e8d5b0;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }

            /* ── Tabs ────────────────────────────────────────────────────── */
            QTabWidget::pane {
                border: 1px solid #3a3020;
                background: #1a1a1a;
            }
            QTabBar::tab {
                background: #252018; color: #8a7a5a;
                padding: 10px 28px; margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px; font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #2e2818; color: #c9a96e;
                border-bottom: 2px solid #c9a96e;
            }
            QTabBar::tab:hover:!selected {
                background: #2a2218; color: #b09050;
            }

            /* ── Buttons ─────────────────────────────────────────────────── */
            QPushButton {
                background-color: #2e2818; color: #c9a96e;
                border: 1px solid #5a4a2a; border-radius: 5px;
                padding: 7px 18px; font-weight: 600;
            }
            QPushButton:hover   { background-color: #3a3020; border-color: #c9a96e; }
            QPushButton:pressed { background-color: #c9a96e; color: #1a1a1a; }
            QPushButton:disabled{ color: #4a4030; border-color: #3a3020; }

            /* ── Inputs ──────────────────────────────────────────────────── */
            QLineEdit, QSpinBox, QComboBox {
                background-color: #252018; color: #e8d5b0;
                border: 1px solid #5a4a2a; border-radius: 4px;
                padding: 5px 8px;
                selection-background-color: #c9a96e;
                selection-color: #1a1a1a;
            }
            QLineEdit:focus, QSpinBox:focus { border-color: #c9a96e; }
            QSpinBox::up-button, QSpinBox::down-button {
                background: #3a3020; border: none; width: 18px;
            }
            QComboBox::drop-down { background: #3a3020; border: none; width: 22px; }
            QComboBox QAbstractItemView {
                background: #1e1e1e; color: #e8d5b0;
                selection-background-color: #3a3020;
                border: 1px solid #3a3020;
            }

            /* ── Menus ───────────────────────────────────────────────────── */
            QMenuBar {
                background-color: #141414; color: #c9a96e;
                border-bottom: 1px solid #3a3020; padding: 2px 0;
            }
            QMenuBar::item:selected { background: #2e2818; }
            QMenu {
                background-color: #1e1e1e; color: #e8d5b0;
                border: 1px solid #3a3020;
            }
            QMenu::item:selected { background-color: #3a3020; color: #c9a96e; }
            QMenu::separator { height: 1px; background: #3a3020; margin: 4px 0; }

            /* ── Status bar ──────────────────────────────────────────────── */
            QStatusBar {
                background-color: #141414; color: #6a5a3a;
                border-top: 1px solid #2a2010; font-size: 11px;
            }

            /* ── Scrollbars ──────────────────────────────────────────────── */
            QScrollBar:vertical {
                background: #1a1a1a; width: 10px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #3a3020; border-radius: 5px; min-height: 20px;
            }
            QScrollBar::handle:vertical:hover { background: #5a4a2a; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }

            /* ── Misc ────────────────────────────────────────────────────── */
            QCheckBox { color: #8a7a5a; }
            QCheckBox::indicator {
                width: 14px; height: 14px;
                border: 1px solid #5a4a2a; border-radius: 3px;
                background: #252018;
            }
            QCheckBox::indicator:checked {
                background: #c9a96e; border-color: #c9a96e;
            }
            QLabel { color: #e8d5b0; }
            QProgressBar {
                background: #252018; border: 1px solid #3a3020;
                border-radius: 4px; height: 14px;
            }
            QProgressBar::chunk { background: #c9a96e; border-radius: 4px; }
            QListWidget { outline: none; }
            QTextEdit {
                background: #151515; color: #e8d5b0;
                border: 1px solid #3a3020; border-radius: 4px;
            }
            QDialogButtonBox QPushButton { min-width: 80px; }
            QFormLayout QLabel { color: #8a7a5a; }
        """)

    # ── Engine lifecycle ───────────────────────────────────────────────────────

    def _open_engine(self):
        """Start Stockfish. Shows a warning if path is wrong."""
        sf_path = self.settings.value("stockfish_path", DEFAULT_SF)
        if os.path.isfile(sf_path):
            try:
                self._engine = ChessEngine(sf_path)
                self._engine.open()
            except Exception as e:
                self._engine = None
                QMessageBox.warning(
                    self, "Engine Error",
                    f"Could not start Stockfish:\n{e}\n\n"
                    "Go to Settings → Preferences to fix the path."
                )
        else:
            self._engine = None
            QMessageBox.warning(
                self, "Stockfish Not Found",
                f"Stockfish was not found at:\n{sf_path}\n\n"
                "Go to Settings → Preferences and set the correct path."
            )

    def _reload_engine(self):
        """Close and restart engine after a settings change."""
        if self._engine and self._engine.is_open():
            self._engine.close()
        self._engine = None
        self._open_engine()

        # Push new engine reference to tabs that need it
        engine = self._engine or ChessEngine(DEFAULT_SF)
        self.play_tab.set_engine(engine)
        self.analyze_tab.set_engine(engine)
        self._refresh_status()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle(f"ChessMaster Pro  v{APP_VERSION}")
        self.setMinimumSize(QSize(1100, 760))
        self.resize(1320, 900)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # Use a dummy engine object if Stockfish isn't found yet — tabs handle
        # the None case gracefully via their set_engine() guard.
        engine = self._engine if self._engine else ChessEngine(DEFAULT_SF)

        # ── Tab 1: Play ────────────────────────────────────────────────────
        self.play_tab = PlayTab(engine)
        self.tabs.addTab(self.play_tab, "♟  Play")

        # ── Tab 2: Analyze ─────────────────────────────────────────────────
        self.analyze_tab = AnalyzeTab(engine)
        self.tabs.addTab(self.analyze_tab, "🔍  Analyze")

        # ── Tab 3: Import ──────────────────────────────────────────────────
        self.import_tab = ImportTab(on_analyze_game=self._send_to_analyzer)
        self.tabs.addTab(self.import_tab, "⬇  Import")

        # ── Tab 4: Puzzles ─────────────────────────────────────────────────
        self.puzzle_tab = PuzzleTab()
        self.tabs.addTab(self.puzzle_tab, "🧩  Puzzles")

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)

    def _build_menu(self):
        mb = self.menuBar()

        # File
        file_m   = mb.addMenu("File")

        open_pgn = QAction("Open PGN…", self)
        open_pgn.setShortcut("Ctrl+O")
        open_pgn.triggered.connect(self._open_pgn)
        file_m.addAction(open_pgn)

        file_m.addSeparator()

        quit_a = QAction("Quit", self)
        quit_a.setShortcut("Ctrl+Q")
        quit_a.triggered.connect(self.close)
        file_m.addAction(quit_a)

        # Settings
        settings_m = mb.addMenu("Settings")
        prefs = QAction("Preferences…", self)
        prefs.setShortcut("Ctrl+,")
        prefs.triggered.connect(self._open_settings)
        settings_m.addAction(prefs)

        # Help
        help_m = mb.addMenu("Help")
        about  = QAction("About", self)
        about.triggered.connect(self._show_about)
        help_m.addAction(about)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _refresh_status(self):
        sf_path = self.settings.value("stockfish_path", DEFAULT_SF)
        depth   = self.settings.value("default_depth", 15)
        ok      = self._engine is not None and self._engine.is_open()
        mark    = "✔ Engine ready" if ok else "✘ Engine not found"
        self.status.showMessage(
            f"{mark}   |   Default depth: {depth}   |   {sf_path}"
        )

    def _open_pgn(self):
        """Open a PGN file directly from the File menu → send to Analyze tab."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PGN File", "", "PGN Files (*.pgn);;All Files (*)"
        )
        if not path:
            return
        from analyzer import Analyzer
        games = Analyzer.parse_pgn_file(path)
        if games:
            self._send_to_analyzer(games[0])
        else:
            QMessageBox.warning(self, "PGN Error",
                                "Could not parse any games from that file.")

    def _send_to_analyzer(self, game):
        """
        Load a chess.pgn.Game into the Analyze tab and switch to it.
        Called from both the File menu and the Import tab's Analyse button.
        """
        self.analyze_tab.load_game_direct(game)
        self.tabs.setCurrentWidget(self.analyze_tab)

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, parent=self)
        if dlg.exec():
            self._reload_engine()

    def _show_about(self):
        QMessageBox.about(
            self, "About ChessMaster Pro",
            f"<h3>ChessMaster Pro  v{APP_VERSION}</h3>"
            "<p>A feature-rich chess GUI with:</p>"
            "<ul>"
            "<li>Play vs Stockfish at configurable depth</li>"
            "<li>Chess.com-style move classifications<br>"
            "&nbsp;&nbsp;✨ Brilliant &nbsp; !! Great &nbsp; ✓ Best &nbsp;"
            "★ Excellent &nbsp; ● Good<br>"
            "&nbsp;&nbsp;?! Inaccuracy &nbsp; ? Mistake &nbsp; ?? Blunder</li>"
            "<li>Import from chess.com &amp; lichess.org</li>"
            "<li>Lichess puzzle training</li>"
            "</ul>"
            "<p>Built with <b>PyQt6</b> + <b>python-chess</b>.</p>"
        )

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Cleanly shut down Stockfish when the window closes."""
        if self._engine and self._engine.is_open():
            self._engine.close()
        event.accept()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    # Must be set before QApplication is created
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()