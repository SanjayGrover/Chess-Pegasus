"""
play_tab.py  —  Play Tab  (vs Engine  +  vs Player)
=====================================================
Mode toggle in the control bar selects the game type:
  • vs Engine — play against Stockfish at a configurable depth
  • vs Player — two humans on the same board

PvP extras:
  • Board auto-flips after every move so each side sees their pieces at the bottom
  • Optional chess clock — configurable minutes per side, increments supported
  • Clock starts on the first move, switches after each move
  • Flagging (time runs out) ends the game immediately
"""

import random
import chess

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QComboBox, QCheckBox,
    QSizePolicy, QFrame
)
from PyQt6.QtCore import Qt, QThread, QTimer, QSettings
from PyQt6.QtGui  import QFont

from board_widget   import BoardWidget
from engine         import ChessEngine, BestMoveWorker
from analysis_panel import AnalysisPanel

APP_NAME = "ChessMasterPro"
ORG_NAME = "ChessMasterPro"


# ── Clock Widget ───────────────────────────────────────────────────────────────

class ClockWidget(QWidget):
    """
    Displays two countdown timers — one per side.
    The active side's timer is highlighted in gold; the inactive one is dimmed.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._white_ms  : int  = 0      # milliseconds remaining
        self._black_ms  : int  = 0
        self._active    : chess.Color | None = None
        self._increment : int  = 0      # seconds added after each move
        self._flagged   : chess.Color | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(100)    # tick every 100 ms
        self._timer.timeout.connect(self._tick)

        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._black_lbl = self._make_label("♚  Black")
        self._white_lbl = self._make_label("♔  White")

        layout.addWidget(self._black_lbl)
        layout.addStretch()
        layout.addWidget(self._white_lbl)

    def _make_label(self, title: str) -> QLabel:
        lbl = QLabel(f"{title}\n--:--")
        lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "background:#1e1e1e; border:1px solid #3a3020;"
            "border-radius:8px; padding:10px 20px; color:#4a4030;"
        )
        lbl.setFixedWidth(160)
        return lbl

    # ── Public API ─────────────────────────────────────────────────────────────

    def setup(self, minutes: int, increment_sec: int = 0):
        """Configure both clocks.  Call before starting the game."""
        self._white_ms  = minutes * 60 * 1000
        self._black_ms  = minutes * 60 * 1000
        self._increment = increment_sec * 1000
        self._active    = None
        self._flagged   = None
        self._timer.stop()
        self._refresh()

    def start_for(self, color: chess.Color):
        """Switch the running clock to `color`."""
        # Add increment to the side that just finished their move
        if self._active is not None and self._active != color:
            if self._active == chess.WHITE:
                self._white_ms = min(self._white_ms + self._increment,
                                     self._white_ms + self._increment)
            else:
                self._black_ms = min(self._black_ms + self._increment,
                                     self._black_ms + self._increment)

        self._active = color
        self._timer.start()
        self._refresh()

    def stop(self):
        self._timer.stop()
        self._active = None
        self._refresh()

    def reset(self):
        self._timer.stop()
        self._active  = None
        self._flagged = None
        self._white_ms = 0
        self._black_ms = 0
        self._refresh()

    @property
    def flagged(self) -> chess.Color | None:
        return self._flagged

    # ── Internals ──────────────────────────────────────────────────────────────

    def _tick(self):
        if self._active == chess.WHITE:
            self._white_ms -= 100
            if self._white_ms <= 0:
                self._white_ms = 0
                self._flagged  = chess.WHITE
                self._timer.stop()
        else:
            self._black_ms -= 100
            if self._black_ms <= 0:
                self._black_ms = 0
                self._flagged  = chess.BLACK
                self._timer.stop()
        self._refresh()

    @staticmethod
    def _fmt(ms: int) -> str:
        ms      = max(0, ms)
        total_s = ms // 1000
        m, s    = divmod(total_s, 60)
        return f"{m:02d}:{s:02d}"

    def _refresh(self):
        # White label
        w_time   = self._fmt(self._white_ms)
        w_active = self._active == chess.WHITE
        w_flag   = self._flagged == chess.WHITE
        self._white_lbl.setText(f"♔  White\n{w_time}")
        self._white_lbl.setStyleSheet(self._style(w_active, w_flag))

        # Black label
        b_time   = self._fmt(self._black_ms)
        b_active = self._active == chess.BLACK
        b_flag   = self._flagged == chess.BLACK
        self._black_lbl.setText(f"♚  Black\n{b_time}")
        self._black_lbl.setStyleSheet(self._style(b_active, b_flag))

    @staticmethod
    def _style(active: bool, flagged: bool) -> str:
        if flagged:
            border = "#c62828"
            color  = "#ef5350"
            bg     = "#2a1010"
        elif active:
            border = "#c9a96e"
            color  = "#f0d9b5"
            bg     = "#2e2818"
        else:
            border = "#3a3020"
            color  = "#4a4030"
            bg     = "#1e1e1e"
        return (
            f"background:{bg}; border:1px solid {border};"
            f"border-radius:8px; padding:10px 20px; color:{color};"
        )


# ── Play Tab ───────────────────────────────────────────────────────────────────

class PlayTab(QWidget):

    def __init__(self, engine: ChessEngine, parent=None):
        super().__init__(parent)
        self._engine        = engine
        self._settings      = QSettings(ORG_NAME, APP_NAME)
        self._player_color  : chess.Color = chess.WHITE
        self._game_active   = False
        self._pvp_mode      = False
        self._thread        : QThread | None = None
        self._worker        = None

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 8, 16)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(8)

        # ── Row 1: mode toggle ─────────────────────────────────────────────
        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)

        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("color:#8a7a5a;")
        mode_row.addWidget(mode_lbl)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["vs Engine  🤖", "vs Player  👥"])
        self.mode_combo.setFixedWidth(150)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        mode_row.addWidget(self.mode_combo)

        mode_row.addSpacing(20)

        # Engine-only controls (hidden in PvP)
        self._side_lbl = QLabel("Play as:")
        self._side_lbl.setStyleSheet("color:#8a7a5a;")
        mode_row.addWidget(self._side_lbl)

        self.side_combo = QComboBox()
        self.side_combo.addItems(["White ♔", "Black ♚", "Random"])
        self.side_combo.setFixedWidth(120)
        mode_row.addWidget(self.side_combo)

        mode_row.addSpacing(12)

        self._depth_lbl = QLabel("Depth:")
        self._depth_lbl.setStyleSheet("color:#8a7a5a;")
        mode_row.addWidget(self._depth_lbl)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 30)
        self.depth_spin.setValue(int(self._settings.value("default_depth", 15)))
        self.depth_spin.setFixedWidth(64)
        mode_row.addWidget(self.depth_spin)

        mode_row.addStretch()

        # New game + Undo
        self.new_game_btn = QPushButton("New Game  ▶")
        self.new_game_btn.setFixedWidth(130)
        self.new_game_btn.clicked.connect(self._start_game)
        mode_row.addWidget(self.new_game_btn)

        self.undo_btn = QPushButton("⟵ Undo")
        self.undo_btn.setFixedWidth(90)
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._undo_move)
        mode_row.addWidget(self.undo_btn)

        left.addLayout(mode_row)

        # ── Row 2: clock controls (always visible, optional) ───────────────
        clock_row = QHBoxLayout()
        clock_row.setSpacing(10)

        self.clock_cb = QCheckBox("Clock")
        self.clock_cb.setStyleSheet("color:#8a7a5a;")
        self.clock_cb.stateChanged.connect(self._on_clock_toggle)
        clock_row.addWidget(self.clock_cb)

        mins_lbl = QLabel("Minutes per side:")
        mins_lbl.setStyleSheet("color:#8a7a5a;")
        clock_row.addWidget(mins_lbl)

        self.mins_spin = QSpinBox()
        self.mins_spin.setRange(1, 180)
        self.mins_spin.setValue(10)
        self.mins_spin.setFixedWidth(64)
        self.mins_spin.setEnabled(False)
        clock_row.addWidget(self.mins_spin)

        inc_lbl = QLabel("Increment (sec):")
        inc_lbl.setStyleSheet("color:#8a7a5a;")
        clock_row.addWidget(inc_lbl)

        self.inc_spin = QSpinBox()
        self.inc_spin.setRange(0, 60)
        self.inc_spin.setValue(0)
        self.inc_spin.setFixedWidth(56)
        self.inc_spin.setEnabled(False)
        clock_row.addWidget(self.inc_spin)

        clock_row.addStretch()
        left.addLayout(clock_row)

        # ── Clock display ──────────────────────────────────────────────────
        self.clock_widget = ClockWidget()
        self.clock_widget.setVisible(False)
        # Connect flagging check — poll via a separate QTimer
        self._flag_timer = QTimer(self)
        self._flag_timer.setInterval(150)
        self._flag_timer.timeout.connect(self._check_flag)
        left.addWidget(self.clock_widget)

        # ── Board ──────────────────────────────────────────────────────────
        self.board_w = BoardWidget()
        self.board_w.set_interactive(False)
        self.board_w.move_made.connect(self._on_move)
        left.addWidget(self.board_w)

        # ── Status ─────────────────────────────────────────────────────────
        self.status_lbl = QLabel("Press 'New Game' to start.")
        self.status_lbl.setStyleSheet("color:#6a5a3a; font-size:12px;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.status_lbl)

        root.addLayout(left, stretch=3)

        # ── Right: analysis panel ──────────────────────────────────────────
        self.panel = AnalysisPanel()
        root.addWidget(self.panel, stretch=1)

    # ── Mode switching ─────────────────────────────────────────────────────────

    def _on_mode_change(self):
        self._pvp_mode = "Player" in self.mode_combo.currentText()
        # Show/hide engine-only controls
        for w in (self._side_lbl, self.side_combo,
                  self._depth_lbl, self.depth_spin):
            w.setVisible(not self._pvp_mode)
        # In PvP, eval bar is not meaningful — clear it
        if self._pvp_mode:
            self.panel.eval_bar.reset()

    def _on_clock_toggle(self, state: int):
        enabled = bool(state)
        self.mins_spin.setEnabled(enabled)
        self.inc_spin.setEnabled(enabled)
        self.clock_widget.setVisible(enabled)
        if not enabled:
            self.clock_widget.reset()
            self._flag_timer.stop()

    # ── Game flow ──────────────────────────────────────────────────────────────

    def _start_game(self):
        # Stop any running engine thread
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()

        # Stop old clock
        self.clock_widget.stop()
        self._flag_timer.stop()

        # Reset board
        if hasattr(self.board_w, "reset_game"):
            self.board_w.reset_game()
        else:
            self.board_w.set_board(chess.Board())

        self.panel.clear()
        self._game_active = True
        self.undo_btn.setEnabled(True)
        self.new_game_btn.setText("Restart  ↺")

        if self._pvp_mode:
            self._start_pvp()
        else:
            self._start_vs_engine()

    # ── PvP ────────────────────────────────────────────────────────────────────

    def _start_pvp(self):
        self.board_w._flipped = False   # start with White at bottom
        self.board_w.set_interactive(True)
        self.status_lbl.setText("Player vs Player — White to move.")

        # Setup clock if enabled
        if self.clock_cb.isChecked():
            self.clock_widget.setup(
                minutes       = self.mins_spin.value(),
                increment_sec = self.inc_spin.value(),
            )
            # Clock starts on first move, not before

    def _pvp_after_move(self):
        """Called after any move in PvP mode."""
        board    = self.board_w.board
        to_move  = board.turn   # side that must move next

        # Auto-flip board so the next player sees their pieces at the bottom
        self.board_w._flipped = (to_move == chess.BLACK)
        self.board_w.update()

        # Switch clock
        if self.clock_cb.isChecked():
            self.clock_widget.start_for(to_move)
            self._flag_timer.start()

        side = "White" if to_move == chess.WHITE else "Black"
        self.status_lbl.setText(f"{side}'s turn.")

    def _check_flag(self):
        """Poll clock for flag fall."""
        flagged = self.clock_widget.flagged
        if flagged is not None:
            self._flag_timer.stop()
            winner = "Black" if flagged == chess.WHITE else "White"
            self._end_game(f"⏱ Time out!  {winner} wins on time.")

    # ── vs Engine ──────────────────────────────────────────────────────────────

    def _start_vs_engine(self):
        choice = self.side_combo.currentText()
        if "White" in choice:
            self._player_color = chess.WHITE
        elif "Black" in choice:
            self._player_color = chess.BLACK
        else:
            self._player_color = random.choice([chess.WHITE, chess.BLACK])

        self.board_w._flipped = (self._player_color == chess.BLACK)
        self.board_w.update()

        side_str = "White" if self._player_color == chess.WHITE else "Black"
        self.status_lbl.setText(f"You are playing {side_str}.")

        if self._player_color == chess.BLACK:
            # Engine goes first
            self.board_w.set_interactive(False)
            self.status_lbl.setText("Engine is thinking…")
            self._request_engine_move()
        else:
            self.board_w.set_interactive(True)

        # Clock (vs engine — both sides share one clock side for the player only,
        # but we support the full two-sided clock here too)
        if self.clock_cb.isChecked():
            self.clock_widget.setup(
                minutes       = self.mins_spin.value(),
                increment_sec = self.inc_spin.value(),
            )

    def _request_engine_move(self):
        if not self._engine.is_open():
            self.status_lbl.setText("Engine not available.")
            self.board_w.set_interactive(True)
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

        if self.clock_cb.isChecked():
            self.clock_widget.start_for(self._player_color)
            self._flag_timer.start()

    def _on_engine_error(self, msg: str):
        self.status_lbl.setText(f"Engine error: {msg}")
        self.board_w.set_interactive(True)

    # ── Shared move handler ────────────────────────────────────────────────────

    def _on_move(self, move: chess.Move):
        """Unified handler for any move made on the board."""
        if not self._game_active:
            return

        board = self.board_w.board
        if board.is_game_over():
            self._handle_game_over(board)
            return

        if self._pvp_mode:
            self._pvp_after_move()
        else:
            # vs Engine: request engine reply
            self.status_lbl.setText("Engine is thinking…")
            self.board_w.set_interactive(False)

            # Switch clock to engine's side while it thinks
            if self.clock_cb.isChecked():
                engine_color = chess.BLACK if self._player_color == chess.WHITE \
                               else chess.WHITE
                self.clock_widget.start_for(engine_color)

            self._request_engine_move()
            self._update_eval()

    # ── Undo ───────────────────────────────────────────────────────────────────

    def _undo_move(self):
        board = self.board_w.board
        if self._pvp_mode:
            # Undo one half-move in PvP
            if board.move_stack:
                self.board_w.undo_move()
                to_move = self.board_w.board.turn
                self.board_w._flipped = (to_move == chess.BLACK)
                self.board_w.update()
                side = "White" if to_move == chess.WHITE else "Black"
                self.status_lbl.setText(f"Move undone — {side}'s turn.")
        else:
            # Undo player + engine half-moves
            if len(board.move_stack) >= 2:
                self.board_w.undo_move()
                self.board_w.undo_move()
            elif board.move_stack:
                self.board_w.undo_move()
            self.board_w.set_interactive(True)
            self.status_lbl.setText("Move undone. Your turn.")
            self._update_eval()

    # ── Game over ──────────────────────────────────────────────────────────────

    def _handle_game_over(self, board: chess.Board):
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
        self._end_game(msg)

    def _end_game(self, message: str):
        self._game_active = False
        self.board_w.set_interactive(False)
        self.clock_widget.stop()
        self._flag_timer.stop()
        self.status_lbl.setText(message)
        self.new_game_btn.setText("New Game  ▶")

    # ── Eval (vs Engine only) ──────────────────────────────────────────────────

    def _update_eval(self):
        if self._pvp_mode or not self._engine.is_open():
            return
        board = self.board_w.board.copy()
        try:
            pos = self._engine.evaluate(board, depth=10, multipv=1)
            if pos.best:
                ev       = pos.best
                score_cp = ev.score_cp
                mate_in  = ev.mate_in
                if board.turn == chess.BLACK:
                    score_cp = -score_cp if score_cp is not None else None
                    mate_in  = -mate_in  if mate_in  is not None else None
                self.panel.set_eval(score_cp, mate_in)
        except Exception:
            pass

    # ── External API ──────────────────────────────────────────────────────────

    def set_engine(self, engine: ChessEngine):
        self._engine = engine