"""
import_tab.py  —  Game Import Tab
=====================================
Fetch games from chess.com or Lichess by username,
browse the list, and send any game to the Analyze tab.
"""

import chess.pgn
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QLineEdit,
    QListWidget, QListWidgetItem, QCheckBox,
    QSizePolicy, QFrame, QSplitter
)
from PyQt6.QtCore import Qt, QThread, QSettings
from PyQt6.QtGui  import QFont, QColor

from importer       import ImportWorker, ImportResult, ImportedGame
from analyzer       import Analyzer

APP_NAME = "ChessMasterPro"
ORG_NAME = "ChessMasterPro"


class ImportTab(QWidget):
    """Import tab — fetch + browse + send to analyzer."""

    def __init__(self, on_analyze_game, parent=None):
        """
        Parameters
        ----------
        on_analyze_game : callable(chess.pgn.Game)
            Called when user clicks 'Analyse' on a game.
            Should switch to the Analyze tab and load the game.
        """
        super().__init__(parent)
        self._on_analyze = on_analyze_game
        self._settings   = QSettings(ORG_NAME, APP_NAME)
        self._games      : list[ImportedGame] = []
        self._thread     : QThread | None = None
        self._worker     = None

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # ── Source selector ────────────────────────────────────────────────
        src_row = QHBoxLayout()

        src_lbl = QLabel("Source:")
        src_lbl.setStyleSheet("color:#8a7a5a;")
        src_row.addWidget(src_lbl)

        self.source_combo = QComboBox()
        self.source_combo.addItems(["chess.com", "lichess.org"])
        self.source_combo.setFixedWidth(140)
        self.source_combo.currentIndexChanged.connect(self._on_source_change)
        src_row.addWidget(self.source_combo)

        src_row.addSpacing(16)

        user_lbl = QLabel("Username:")
        user_lbl.setStyleSheet("color:#8a7a5a;")
        src_row.addWidget(user_lbl)

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("enter username…")
        self.user_edit.setFixedWidth(180)
        self.user_edit.returnPressed.connect(self._fetch)
        src_row.addWidget(self.user_edit)

        src_row.addStretch()
        root.addLayout(src_row)

        # ── Filters row ────────────────────────────────────────────────────
        flt_row = QHBoxLayout()
        flt_row.setSpacing(12)

        tc_lbl = QLabel("Time class:")
        tc_lbl.setStyleSheet("color:#8a7a5a;")
        flt_row.addWidget(tc_lbl)

        self.tc_combo = QComboBox()
        self.tc_combo.addItems(["All", "Bullet", "Blitz", "Rapid", "Classical", "Daily"])
        self.tc_combo.setFixedWidth(110)
        flt_row.addWidget(self.tc_combo)

        flt_row.addSpacing(12)

        n_lbl = QLabel("Max games:")
        n_lbl.setStyleSheet("color:#8a7a5a;")
        flt_row.addWidget(n_lbl)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 200)
        self.max_spin.setValue(20)
        self.max_spin.setFixedWidth(70)
        flt_row.addWidget(self.max_spin)

        flt_row.addSpacing(12)

        # Lichess-only options (hidden for chess.com)
        self.rated_cb = QCheckBox("Rated only")
        self.rated_cb.setStyleSheet("color:#8a7a5a;")
        flt_row.addWidget(self.rated_cb)

        self.color_combo = QComboBox()
        self.color_combo.addItems(["Both colors", "As White", "As Black"])
        self.color_combo.setFixedWidth(120)
        flt_row.addWidget(self.color_combo)

        flt_row.addStretch()

        self.fetch_btn = QPushButton("⬇  Fetch Games")
        self.fetch_btn.setFixedWidth(140)
        self.fetch_btn.clicked.connect(self._fetch)
        flt_row.addWidget(self.fetch_btn)

        root.addLayout(flt_row)

        # ── Status label ───────────────────────────────────────────────────
        self.status_lbl = QLabel("Enter a username and click Fetch.")
        self.status_lbl.setStyleSheet("color:#6a5a3a; font-size:11px;")
        root.addWidget(self.status_lbl)

        # ── Game list ──────────────────────────────────────────────────────
        list_lbl = QLabel("IMPORTED GAMES")
        list_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        list_lbl.setStyleSheet("color:#555; letter-spacing:1px;")
        root.addWidget(list_lbl)

        self.game_list = QListWidget()
        self.game_list.setStyleSheet(
            "QListWidget{background:#111;border:1px solid #3a3020;"
            "border-radius:6px;color:#e8d5b0;outline:none;}"
            "QListWidget::item{padding:10px 12px;border-bottom:1px solid #222;}"
            "QListWidget::item:selected{background:#3a3020;color:#c9a96e;}"
            "QListWidget::item:hover{background:#1e1e1e;}"
        )
        self.game_list.setFont(QFont("Segoe UI", 11))
        self.game_list.currentRowChanged.connect(self._on_selection_change)
        root.addWidget(self.game_list, stretch=1)

        # ── Action buttons ─────────────────────────────────────────────────
        act_row = QHBoxLayout()

        self.analyze_btn = QPushButton("🔍  Analyse Selected Game")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._analyze_selected)
        act_row.addWidget(self.analyze_btn)

        self.pgn_btn = QPushButton("📋  Copy PGN")
        self.pgn_btn.setEnabled(False)
        self.pgn_btn.clicked.connect(self._copy_pgn)
        act_row.addWidget(self.pgn_btn)

        act_row.addStretch()
        root.addLayout(act_row)

        # Pre-fill username from settings
        self.user_edit.setText(
            self._settings.value("chesscom_username", "")
        )
        self._on_source_change()

    # ── Source switching ───────────────────────────────────────────────────────

    def _on_source_change(self):
        is_lichess = "lichess" in self.source_combo.currentText()
        self.rated_cb.setVisible(is_lichess)
        self.color_combo.setVisible(is_lichess)

        # Swap stored username
        if is_lichess:
            self.user_edit.setText(
                self._settings.value("lichess_username", "")
            )
        else:
            self.user_edit.setText(
                self._settings.value("chesscom_username", "")
            )

    # ── Fetch ──────────────────────────────────────────────────────────────────

    def _fetch(self):
        username = self.user_edit.text().strip()
        if not username:
            self.status_lbl.setText("Please enter a username.")
            return

        source    = "lichess" if "lichess" in self.source_combo.currentText() else "chesscom"
        max_games = self.max_spin.value()
        tc_text   = self.tc_combo.currentText()
        tc        = None if tc_text == "All" else tc_text.lower()
        rated     = self.rated_cb.isChecked()

        color_text = self.color_combo.currentText()
        color = None
        if "White" in color_text:
            color = "white"
        elif "Black" in color_text:
            color = "black"

        self.fetch_btn.setEnabled(False)
        self.status_lbl.setText(f"Fetching from {self.source_combo.currentText()}…")
        self.game_list.clear()
        self._games = []

        self._thread = QThread()
        self._worker = ImportWorker(
            source     = source,
            username   = username,
            max_games  = max_games,
            time_class = tc,
            rated_only = rated,
            as_color   = color,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.status_lbl.setText)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(lambda: self.fetch_btn.setEnabled(True))
        self._thread.start()

    def _on_fetch_done(self, result: ImportResult):
        self._games = result.games
        self.game_list.clear()

        if result.errors:
            self.status_lbl.setText(
                result.summary + "  ⚠ " + result.errors[0]
            )
        else:
            self.status_lbl.setText(result.summary)

        for g in result.games:
            item = QListWidgetItem(g.display_title)
            item.setToolTip(g.url)
            # Color-code result
            if g.result == "1-0":
                item.setForeground(QColor("#7ec845"))
            elif g.result == "0-1":
                item.setForeground(QColor("#ef5350"))
            else:
                item.setForeground(QColor("#c9a96e"))
            self.game_list.addItem(item)

        if not result.games:
            self.analyze_btn.setEnabled(False)
            self.pgn_btn.setEnabled(False)

    def _on_fetch_error(self, msg: str):
        self.status_lbl.setText(f"Error: {msg}")

    # ── Selection ──────────────────────────────────────────────────────────────

    def _on_selection_change(self, row: int):
        valid = 0 <= row < len(self._games)
        self.analyze_btn.setEnabled(valid)
        self.pgn_btn.setEnabled(valid)

    def _analyze_selected(self):
        row = self.game_list.currentRow()
        if not (0 <= row < len(self._games)):
            return
        game = self._games[row].parsed_game
        if game:
            self._on_analyze(game)

    def _copy_pgn(self):
        row = self.game_list.currentRow()
        if not (0 <= row < len(self._games)):
            return
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._games[row].pgn_text)
        self.status_lbl.setText("PGN copied to clipboard.")