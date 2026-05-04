"""
analyze_tab.py  —  Game Analysis Tab
======================================
Load a PGN (from file or paste), run full Stockfish analysis,
and navigate the game move-by-move with the board synced to the panel.
"""

import chess
import chess.pgn
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QTextEdit, QFileDialog,
    QProgressBar, QSizePolicy, QComboBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, QSettings
from PyQt6.QtGui  import QFont

from board_widget   import BoardWidget
from engine         import ChessEngine
from analyzer       import Analyzer, AnalyzerWorker, GameAnalysis
from analysis_panel import AnalysisPanel

APP_NAME = "ChessMasterPro"
ORG_NAME = "ChessMasterPro"


class AnalyzeTab(QWidget):

    def __init__(self, engine: ChessEngine, parent=None):
        super().__init__(parent)
        self._engine    = engine
        self._settings  = QSettings(ORG_NAME, APP_NAME)
        self._game      : chess.pgn.Game | None  = None
        self._analysis  : GameAnalysis   | None  = None
        self._positions : list[chess.Board]      = []   # board at each ply
        self._current_ply = 0
        self._thread    : QThread | None = None
        self._worker    : AnalyzerWorker | None = None

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 8, 16)
        root.setSpacing(12)

        # ── Left: board + controls ─────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)

        # Top control row
        top = QHBoxLayout()
        top.setSpacing(8)

        self.load_btn = QPushButton("📂  Load PGN")
        self.load_btn.clicked.connect(self._load_pgn_file)
        top.addWidget(self.load_btn)

        self.paste_btn = QPushButton("📋  Paste PGN")
        self.paste_btn.clicked.connect(self._show_paste_dialog)
        top.addWidget(self.paste_btn)

        top.addStretch()

        depth_lbl = QLabel("Depth:")
        depth_lbl.setStyleSheet("color:#8a7a5a;")
        top.addWidget(depth_lbl)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 30)
        self.depth_spin.setValue(int(self._settings.value("default_depth", 15)))
        self.depth_spin.setFixedWidth(64)
        top.addWidget(self.depth_spin)

        self.analyze_btn = QPushButton("🔍  Analyse")
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.clicked.connect(self._run_analysis)
        top.addWidget(self.analyze_btn)

        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_analysis)
        top.addWidget(self.stop_btn)

        left.addLayout(top)

        # Game info label
        self.game_info = QLabel("No game loaded.")
        self.game_info.setStyleSheet("color:#6a5a3a; font-size:11px;")
        left.addWidget(self.game_info)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Analysing…  %v / %m moves")
        self.progress.setStyleSheet(
            "QProgressBar{background:#252018;border:1px solid #3a3020;"
            "border-radius:4px;color:#c9a96e;font-size:11px;}"
            "QProgressBar::chunk{background:#c9a96e;border-radius:4px;}"
        )
        left.addWidget(self.progress)

        # Board
        self.board_w = BoardWidget()
        self.board_w.set_interactive(False)
        self.board_w.square_clicked.connect(self._on_square_click)
        left.addWidget(self.board_w)

        # Navigation row
        nav = QHBoxLayout()
        nav.setSpacing(6)

        btn_style = (
            "QPushButton{background:#2e2818;color:#c9a96e;border:1px solid #5a4a2a;"
            "border-radius:5px;padding:6px 14px;font-size:16px;font-weight:700;}"
            "QPushButton:hover{background:#3a3020;}"
            "QPushButton:disabled{color:#3a3020;border-color:#2a2010;}"
        )
        self.btn_start = QPushButton("⏮")
        self.btn_prev  = QPushButton("◀")
        self.btn_next  = QPushButton("▶")
        self.btn_end   = QPushButton("⏭")
        for b in (self.btn_start, self.btn_prev, self.btn_next, self.btn_end):
            b.setStyleSheet(btn_style)
            b.setEnabled(False)
            nav.addWidget(b)

        self.btn_start.clicked.connect(lambda: self._goto_ply(0))
        self.btn_prev.clicked.connect(lambda: self._goto_ply(self._current_ply - 1))
        self.btn_next.clicked.connect(lambda: self._goto_ply(self._current_ply + 1))
        self.btn_end.clicked.connect(lambda: self._goto_ply(len(self._positions) - 1))

        self.ply_label = QLabel("—")
        self.ply_label.setStyleSheet("color:#6a5a3a; font-size:11px;")
        self.ply_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.ply_label)

        nav.addStretch()

        self.flip_btn = QPushButton("⇅ Flip")
        self.flip_btn.setStyleSheet(btn_style)
        self.flip_btn.clicked.connect(self.board_w.flip)
        nav.addWidget(self.flip_btn)

        left.addLayout(nav)
        root.addLayout(left, stretch=3)

        # ── Right: analysis panel ──────────────────────────────────────────
        self.panel = AnalysisPanel()
        self.panel.move_selected.connect(self._goto_ply)
        root.addWidget(self.panel, stretch=1)

    # ── PGN loading ────────────────────────────────────────────────────────────

    def _load_pgn_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PGN File", "", "PGN Files (*.pgn);;All Files (*)"
        )
        if path:
            games = Analyzer.parse_pgn_file(path)
            if games:
                self._load_game(games[0])

    def _show_paste_dialog(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Paste PGN")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet(self.styleSheet())
        lay = QVBoxLayout(dlg)

        lbl = QLabel("Paste your PGN below:")
        lbl.setStyleSheet("color:#8a7a5a;")
        lay.addWidget(lbl)

        txt = QTextEdit()
        txt.setPlaceholderText("[Event \"...\"]\n1. e4 e5 ...")
        txt.setFont(QFont("Consolas", 10))
        txt.setStyleSheet(
            "background:#151515; color:#e8d5b0; border:1px solid #3a3020;"
            "border-radius:4px;"
        )
        lay.addWidget(txt)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec():
            pgn_text = txt.toPlainText().strip()
            if pgn_text:
                games = Analyzer.parse_pgn(pgn_text)
                if games:
                    self._load_game(games[0])

    def load_game_direct(self, game: chess.pgn.Game):
        """Called from import tab when user selects a game to analyse."""
        self._load_game(game)

    def _load_game(self, game: chess.pgn.Game):
        self._game    = game
        self._analysis = None
        self._build_positions(game)

        h = game.headers
        white  = h.get("White",  "?")
        black  = h.get("Black",  "?")
        result = h.get("Result", "?")
        date   = h.get("Date",   "")
        self.game_info.setText(
            f"{white} vs {black}  [{result}]  {date}  "
            f"— {len(self._positions)-1} moves"
        )
        self.analyze_btn.setEnabled(True)
        self._goto_ply(0)
        self.panel.clear()
        self._enable_nav(True)

    def _build_positions(self, game: chess.pgn.Game):
        """Pre-compute all board positions for fast navigation."""
        self._positions = []
        board = game.board()
        self._positions.append(board.copy())
        node = game
        while node.variations:
            node = node.variations[0]
            board.push(node.move)
            self._positions.append(board.copy())

    # ── Analysis ───────────────────────────────────────────────────────────────

    def _run_analysis(self):
        if not self._game or not self._engine.is_open():
            return

        total = len(self._positions) - 1
        self.progress.setMaximum(total)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.analyze_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        depth = self.depth_spin.value()
        self._thread = QThread()
        self._worker = AnalyzerWorker(self._engine, self._game, depth=depth)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(
            lambda cur, tot: self.progress.setValue(cur)
        )
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(lambda: self.stop_btn.setEnabled(False))

        self._thread.start()

    def _stop_analysis(self):
        if self._worker:
            self._worker.abort()
        self.stop_btn.setEnabled(False)
        self.analyze_btn.setEnabled(True)
        self.progress.setVisible(False)

    def _on_analysis_done(self, analysis: GameAnalysis):
        self._analysis = analysis
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.panel.load_analysis(analysis)
        # Select current ply if possible
        if self._current_ply > 0:
            self.panel.select_ply(self._current_ply)

    def _on_analysis_error(self, msg: str):
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.game_info.setText(f"Analysis error: {msg}")

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _goto_ply(self, ply: int):
        if not self._positions:
            return
        ply = max(0, min(ply, len(self._positions) - 1))
        self._current_ply = ply

        board = self._positions[ply]
        last_move = None
        if ply > 0 and self._game:
            # Recover last move from the game tree
            node = self._game
            for _ in range(ply):
                if node.variations:
                    node = node.variations[0]
            last_move = node.move

        self.board_w.set_board(board, last_move=last_move)
        total = len(self._positions) - 1
        self.ply_label.setText(f"Move {ply}/{total}")

        # Sync panel selection
        if self._analysis and ply > 0:
            self.panel.select_ply(ply)

        # Update nav buttons
        self.btn_start.setEnabled(ply > 0)
        self.btn_prev.setEnabled(ply > 0)
        self.btn_next.setEnabled(ply < total)
        self.btn_end.setEnabled(ply < total)

    def _on_square_click(self, _sq: int):
        pass   # non-interactive in analysis mode

    def _enable_nav(self, val: bool):
        for b in (self.btn_start, self.btn_prev, self.btn_next, self.btn_end):
            b.setEnabled(val)
        self.flip_btn.setEnabled(val)

    def set_engine(self, engine: ChessEngine):
        self._engine = engine