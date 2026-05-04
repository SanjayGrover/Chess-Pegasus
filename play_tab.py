"""
play_tab.py  —  Play vs Engine Tab
=====================================
Lets the user play a full game against Stockfish.
  • Choose side (White / Black / Random)
  • Set engine depth (1-30)
  • Engine moves run in a QThread (GUI never freezes)
  • Live eval bar updates after every move
  • Game-over detection with result banner on the board
"""

import random
import chess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QSizePolicy,
    QFrame
)
from PyQt6.QtCore    import Qt, QThread, QSettings
from PyQt6.QtGui     import QFont

from board_widget    import BoardWidget
from engine          import ChessEngine, BestMoveWorker, EngineWorker
from analysis_panel  import AnalysisPanel

APP_NAME = "ChessMasterPro"
ORG_NAME = "ChessMasterPro"


class PlayTab(QWidget):
    """Full Play-vs-Engine tab wired to the board and analysis panel."""

    def __init__(self, engine: ChessEngine, parent=None):
        super().__init__(parent)
        self._engine      = engine
        self._settings    = QSettings(ORG_NAME, APP_NAME)
        self._player_color: chess.Color = chess.WHITE
        self._game_active  = False
        self._thread : QThread | None = None
        self._worker       = None

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 8, 16)
        root.setSpacing(12)

        # ── Left: board + controls ─────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(10)

        # Control bar
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)

        # Side selector
        side_lbl = QLabel("Play as:")
        side_lbl.setStyleSheet("color:#8a7a5a;")
        ctrl.addWidget(side_lbl)

        self.side_combo = QComboBox()
        self.side_combo.addItems(["White ♔", "Black ♚", "Random"])
        self.side_combo.setFixedWidth(120)
        ctrl.addWidget(self.side_combo)

        ctrl.addSpacing(16)

        # Depth spinner
        depth_lbl = QLabel("Depth:")
        depth_lbl.setStyleSheet("color:#8a7a5a;")
        ctrl.addWidget(depth_lbl)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 30)
        self.depth_spin.setValue(
            int(self._settings.value("default_depth", 15))
        )
        self.depth_spin.setFixedWidth(64)
        ctrl.addWidget(self.depth_spin)

        ctrl.addStretch()

        # New Game button
        self.new_game_btn = QPushButton("New Game  ▶")
        self.new_game_btn.setFixedWidth(130)
        self.new_game_btn.clicked.connect(self._start_game)
        ctrl.addWidget(self.new_game_btn)

        # Undo button
        self.undo_btn = QPushButton("⟵ Undo")
        self.undo_btn.setFixedWidth(90)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo_move)
        ctrl.addWidget(self.undo_btn)

        left.addLayout(ctrl)

        # Board
        self.board_w = BoardWidget()
        self.board_w.set_interactive(False)
        self.board_w.move_made.connect(self._on_player_move)
        left.addWidget(self.board_w)

        # Status label
        self.status_lbl = QLabel("Press 'New Game' to start.")
        self.status_lbl.setStyleSheet("color:#6a5a3a; font-size:12px;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.status_lbl)

        root.addLayout(left, stretch=3)

        # ── Right: analysis panel ──────────────────────────────────────────
        self.panel = AnalysisPanel()
        root.addWidget(self.panel, stretch=1)

    # ── Game flow ──────────────────────────────────────────────────────────────

    def _start_game(self):
        """Reset everything and start a fresh game."""
        if self._thread and self._thread.isRunning():
            if self._worker:
                self._worker  # no abort on BestMoveWorker, just wait
            self._thread.quit()
            self._thread.wait()

        choice = self.side_combo.currentText()
        if "White" in choice:
            self._player_color = chess.WHITE
        elif "Black" in choice:
            self._player_color = chess.BLACK
        else:
            self._player_color = random.choice([chess.WHITE, chess.BLACK])

        self.board_w.reset_game() if hasattr(self.board_w, 'reset_game') \
            else self.board_w.set_board(chess.Board())
        self.board_w._flipped = (self._player_color == chess.BLACK)
        self.board_w.set_interactive(True)
        self.panel.clear()

        self._game_active = True
        self.undo_btn.setEnabled(True)
        self.new_game_btn.setText("Restart  ↺")

        side_str = "White" if self._player_color == chess.WHITE else "Black"
        self.status_lbl.setText(f"You are playing {side_str}. Your move.")

        # If player chose Black, engine plays first
        if self._player_color == chess.BLACK:
            self.status_lbl.setText("Engine is thinking…")
            self.board_w.set_interactive(False)
            self._request_engine_move()

    def _on_player_move(self, move: chess.Move):
        """Called after the player makes a move on the board."""
        if not self._game_active:
            return

        board = self.board_w.board
        if board.is_game_over():
            self._handle_game_over(board)
            return

        # Request engine reply
        self.status_lbl.setText("Engine is thinking…")
        self.board_w.set_interactive(False)
        self._request_engine_move()
        self._update_eval()

    def _request_engine_move(self):
        """Start engine move calculation in a background thread."""
        if not self._engine.is_open():
            self.status_lbl.setText("Engine not available.")
            return

        board = self.board_w.board.copy()
        depth = self.depth_spin.value()

        self._thread = QThread()
        self._worker = BestMoveWorker(self._engine, board, depth=depth)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_engine_move)
        self._worker.error.connect(self._on_engine_error)
        self._worker.finished.connect(self._thread.quit)

        self._thread.start()

    def _on_engine_move(self, move: chess.Move):
        """Apply the engine's move to the board."""
        if not self._game_active:
            return

        self.board_w.push_move(move)
        board = self.board_w.board

        if board.is_game_over():
            self._handle_game_over(board)
            return

        self.board_w.set_interactive(True)
        side_str = "White" if self._player_color == chess.WHITE else "Black"
        self.status_lbl.setText(f"Your move ({side_str}).")
        self._update_eval()

    def _on_engine_error(self, msg: str):
        self.status_lbl.setText(f"Engine error: {msg}")
        self.board_w.set_interactive(True)

    def _undo_move(self):
        """Undo the last two half-moves (player + engine)."""
        board = self.board_w.board
        # Undo engine move, then player move
        if len(board.move_stack) >= 2:
            self.board_w.undo_move()
            self.board_w.undo_move()
        elif len(board.move_stack) == 1:
            self.board_w.undo_move()

        self.board_w.set_interactive(True)
        self.status_lbl.setText("Move undone. Your turn.")
        self._update_eval()

    def _handle_game_over(self, board: chess.Board):
        self._game_active = False
        self.board_w.set_interactive(False)
        outcome = board.outcome()
        if outcome:
            if outcome.winner == chess.WHITE:
                msg = "White wins! ♔"
            elif outcome.winner == chess.BLACK:
                msg = "Black wins! ♚"
            else:
                msg = f"Draw — {outcome.termination.name.replace('_', ' ').title()}"
        else:
            msg = "Game over."
        self.status_lbl.setText(msg)
        self.new_game_btn.setText("New Game  ▶")

    def _update_eval(self):
        """Request a quick eval update for the eval bar (depth 10 for speed)."""
        if not self._engine.is_open():
            return
        board = self.board_w.board.copy()
        try:
            pos = self._engine.evaluate(board, depth=10, multipv=1)
            if pos.best:
                ev = pos.best
                # Convert side-to-move score to White's absolute POV
                score_cp = ev.score_cp
                mate_in  = ev.mate_in
                if board.turn == chess.BLACK:
                    score_cp = -score_cp if score_cp is not None else None
                    mate_in  = -mate_in  if mate_in  is not None else None
                self.panel.set_eval(score_cp, mate_in)
        except Exception:
            pass

    # ── Called by main window when engine path changes ─────────────────────────

    def set_engine(self, engine: ChessEngine):
        self._engine = engine