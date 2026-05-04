"""
analysis_panel.py  —  Analysis Side Panel Widget
==================================================
Displays the full game analysis alongside the board:
  • Evaluation bar (live or post-analysis)
  • Move list with classification badges (Brilliant, Blunder, etc.)
  • Accuracy scores for both sides
  • Classification summary (counts per type)
  • Engine best-move suggestion + description
  • Click a move → board jumps to that position

Used by: play_tab, analyze_tab, import_tab inside main.py
"""

import chess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QSizePolicy, QProgressBar,
    QGridLayout, QPushButton, QSpacerItem
)
from PyQt6.QtCore  import Qt, pyqtSignal, QSize, QRect, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui   import (
    QPainter, QColor, QFont, QLinearGradient,
    QBrush, QPen, QFontMetrics
)

from analyzer import (
    GameAnalysis, MoveAnalysis, Classification, CLASS_META
)
from engine import MoveEval


# ── Evaluation Bar ─────────────────────────────────────────────────────────────

class EvalBar(QWidget):
    """
    Vertical evaluation bar: white portion on top, black on bottom.
    Score is in centipawns from White's absolute POV.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(28)
        self.setMinimumHeight(200)
        self._white_fraction = 0.5   # 0.0 = all black, 1.0 = all white
        self._label_text     = "0.00"

    def set_score(self, score_cp: int | None, mate_in: int | None = None):
        """
        Update bar from White's absolute centipawn score.
        Positive = White is better.
        """
        import math
        if mate_in is not None:
            self._white_fraction = 1.0 if mate_in > 0 else 0.0
            self._label_text     = f"M{abs(mate_in)}"
        elif score_cp is not None:
            # Sigmoid mapping cp → [0,1]
            frac = 1.0 / (1.0 + math.exp(-score_cp / 400.0))
            self._white_fraction = max(0.05, min(0.95, frac))
            pawns = score_cp / 100.0
            sign  = "+" if pawns > 0 else ""
            self._label_text = f"{sign}{pawns:.1f}"
        else:
            self._white_fraction = 0.5
            self._label_text     = "0.0"
        self.update()

    def reset(self):
        self._white_fraction = 0.5
        self._label_text     = "0.0"
        self.update()

    def paintEvent(self, _event):
        p    = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor("#1a1a1a"))

        # White portion (top)
        white_h = int(h * (1.0 - self._white_fraction))
        black_h = h - white_h

        # Black portion
        p.fillRect(2, 0, w - 4, white_h, QColor("#2a2a2a"))
        # White portion
        p.fillRect(2, white_h, w - 4, black_h, QColor("#f0d9b5"))

        # Centre line
        p.setPen(QPen(QColor("#888"), 1))
        p.drawLine(2, h // 2, w - 2, h // 2)

        # Score label
        font = QFont("Segoe UI", 7, QFont.Weight.Bold)
        p.setFont(font)
        label_color = QColor("#f0d9b5") if self._white_fraction < 0.5 else QColor("#2a2a2a")
        p.setPen(label_color)
        p.drawText(QRect(0, h // 2 - 10, w, 20),
                   Qt.AlignmentFlag.AlignCenter, self._label_text)
        p.end()


# ── Move Badge ─────────────────────────────────────────────────────────────────

class MoveBadge(QWidget):
    """A single move entry in the move list with its classification badge."""

    clicked = pyqtSignal(int)   # emits ply index

    def __init__(self, ma: MoveAnalysis, parent=None):
        super().__init__(parent)
        self.ma       = ma
        self.selected = False
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        sym, lbl, col = CLASS_META[self.ma.classification]

        # Move number
        if self.ma.is_white:
            num_label = QLabel(f"{self.ma.move_number}.")
            num_label.setFixedWidth(24)
            num_label.setStyleSheet("color:#555; font-size:11px;")
            layout.addWidget(num_label)
        else:
            spacer = QLabel("")
            spacer.setFixedWidth(24)
            layout.addWidget(spacer)

        # SAN move text
        san_label = QLabel(self.ma.move_san)
        san_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        san_label.setStyleSheet(f"color: #e8d5b0;")
        layout.addWidget(san_label)

        layout.addStretch()

        # Classification badge
        badge = QLabel(f"{sym} {lbl}")
        badge.setFont(QFont("Segoe UI", 10))
        badge.setStyleSheet(
            f"color: {col}; background: transparent;"
            f"border: 1px solid {col}; border-radius: 8px;"
            f"padding: 1px 6px;"
        )
        layout.addWidget(badge)

        # cp loss (if any)
        if self.ma.cp_loss and self.ma.cp_loss > 0:
            cp_label = QLabel(f"−{self.ma.cp_loss}")
            cp_label.setFont(QFont("Segoe UI", 9))
            cp_label.setStyleSheet("color:#666; min-width:36px;")
            cp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(cp_label)

        self._update_bg()

    def set_selected(self, val: bool):
        self.selected = val
        self._update_bg()

    def _update_bg(self):
        if self.selected:
            self.setStyleSheet("background:#3a3020; border-radius:4px;")
        else:
            self.setStyleSheet("background:transparent;")
            
    def mousePressEvent(self, _event):
        self.clicked.emit(self.ma.ply)

    def enterEvent(self, _event):
        if not self.selected:
            self.setStyleSheet("background:#252018; border-radius:4px;")

    def leaveEvent(self, _event):
        self._update_bg()


# ── Accuracy Card ──────────────────────────────────────────────────────────────

class AccuracyCard(QWidget):
    """Shows accuracy percentage + classification breakdown for one player."""

    def __init__(self, color_name: str, color_hex: str, parent=None):
        super().__init__(parent)
        self._color_name = color_name
        self._color_hex  = color_hex
        self.setStyleSheet(
            f"background:#1e1e1e; border:1px solid #3a3020; border-radius:8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header row
        hdr = QHBoxLayout()
        name_lbl = QLabel(color_name)
        name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{color_hex}; border:none;")
        hdr.addWidget(name_lbl)
        hdr.addStretch()

        self.acc_label = QLabel("—")
        self.acc_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.acc_label.setStyleSheet("color:#c9a96e; border:none;")
        hdr.addWidget(self.acc_label)
        layout.addLayout(hdr)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            f"QProgressBar{{background:#2a2a2a;border:none;border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{color_hex};border-radius:3px;}}"
        )
        layout.addWidget(self.bar)

        # Classification counts row
        self.counts_layout = QHBoxLayout()
        self.counts_layout.setSpacing(6)
        layout.addLayout(self.counts_layout)

    def update_stats(self, accuracy: float, counts: dict):
        self.acc_label.setText(f"{accuracy:.1f}%")
        self.bar.setValue(int(accuracy))

        # Clear old count badges
        while self.counts_layout.count():
            item = self.counts_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Add badges for non-zero classifications (skip FORCED)
        order = [
            Classification.BRILLIANT, Classification.GREAT,
            Classification.BEST,      Classification.EXCELLENT,
            Classification.GOOD,      Classification.INACCURACY,
            Classification.MISTAKE,   Classification.BLUNDER,
        ]
        for cls in order:
            n = counts.get(cls, 0)
            if n == 0:
                continue
            sym, _, col = CLASS_META[cls]
            lbl = QLabel(f"{n}{sym}")
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setStyleSheet(f"color:{col}; border:none;")
            self.counts_layout.addWidget(lbl)

        self.counts_layout.addStretch()


# ── Description Box ────────────────────────────────────────────────────────────

class DescriptionBox(QWidget):
    """Shows the classification description + engine suggestion for the selected move."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "background:#1e1e1e; border:1px solid #3a3020; border-radius:8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.title_label = QLabel("Select a move to see analysis")
        self.title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("color:#c9a96e; border:none;")
        layout.addWidget(self.title_label)

        self.desc_label = QLabel("")
        self.desc_label.setFont(QFont("Segoe UI", 11))
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color:#a0907a; border:none;")
        layout.addWidget(self.desc_label)

        self.best_label = QLabel("")
        self.best_label.setFont(QFont("Segoe UI", 10))
        self.best_label.setWordWrap(True)
        self.best_label.setStyleSheet("color:#5a8a3c; border:none;")
        layout.addWidget(self.best_label)

    def show_move(self, ma: MoveAnalysis):
        sym, lbl, col = CLASS_META[ma.classification]
        side = "White" if ma.is_white else "Black"
        self.title_label.setText(
            f"{side}'s {ma.move_number}{'.' if ma.is_white else '…'}  "
            f"<span style='color:{col};'>{sym} {ma.move_san}</span>"
        )
        self.title_label.setTextFormat(Qt.TextFormat.RichText)
        self.desc_label.setText(ma.description())

        if ma.best_move_san and ma.best_move != ma.move:
            cp_str = f"  (saves {ma.cp_loss} cp)" if ma.cp_loss else ""
            self.best_label.setText(f"✓ Best was {ma.best_move_san}{cp_str}")
        else:
            self.best_label.setText("")

    def clear(self):
        self.title_label.setText("Select a move to see analysis")
        self.desc_label.setText("")
        self.best_label.setText("")


# ── Main Analysis Panel ────────────────────────────────────────────────────────

class AnalysisPanel(QWidget):
    """
    Full right-side analysis panel.

    Signals
    -------
    move_selected(int)   — ply index the user clicked in the move list
    """

    move_selected = pyqtSignal(int)   # ply (1-indexed)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._badges     : list[MoveBadge]    = []
        self._selected   : int | None         = None   # currently selected ply
        self._analysis   : GameAnalysis | None = None

        self._build_ui()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Eval bar on the left edge
        self.eval_bar = EvalBar()
        outer.addWidget(self.eval_bar)

        # Main content column
        content = QVBoxLayout()
        content.setContentsMargins(8, 8, 8, 8)
        content.setSpacing(8)

        # ── Accuracy cards ─────────────────────────────────────────────────
        acc_row = QHBoxLayout()
        acc_row.setSpacing(6)
        self.white_card = AccuracyCard("White ♔", "#f0d9b5")
        self.black_card = AccuracyCard("Black ♚", "#aaaaaa")
        acc_row.addWidget(self.white_card)
        acc_row.addWidget(self.black_card)
        content.addLayout(acc_row)

        # ── Description box ────────────────────────────────────────────────
        self.desc_box = DescriptionBox()
        content.addWidget(self.desc_box)

        # ── Move list ──────────────────────────────────────────────────────
        move_header = QLabel("MOVES")
        move_header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        move_header.setStyleSheet("color:#555; letter-spacing:1px;")
        content.addWidget(move_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;")

        self._move_container = QWidget()
        self._move_container.setStyleSheet("background:transparent;")
        self._move_layout = QVBoxLayout(self._move_container)
        self._move_layout.setContentsMargins(0, 0, 0, 0)
        self._move_layout.setSpacing(1)
        self._move_layout.addStretch()

        scroll.setWidget(self._move_container)
        self._scroll = scroll
        content.addWidget(scroll)

        outer.addLayout(content)

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_analysis(self, analysis: GameAnalysis):
        """Populate the panel with a completed GameAnalysis."""
        self._analysis = analysis
        self._selected = None

        # Accuracy cards
        self.white_card.update_stats(analysis.white_accuracy, analysis.white_counts)
        self.black_card.update_stats(analysis.black_accuracy, analysis.black_counts)

        # Rebuild move list
        self._clear_moves()
        for ma in analysis.moves:
            badge = MoveBadge(ma)
            badge.clicked.connect(self._on_badge_clicked)
            self._badges.append(badge)
            # Insert before the stretch at the end
            self._move_layout.insertWidget(self._move_layout.count() - 1, badge)

        self.desc_box.clear()
        self.eval_bar.reset()

    def select_ply(self, ply: int):
        """Highlight the badge for a given ply and show its description."""
        # Deselect old
        if self._selected is not None:
            old = self._badge_for_ply(self._selected)
            if old:
                old.set_selected(False)

        self._selected = ply
        badge = self._badge_for_ply(ply)
        if badge:
            badge.set_selected(True)
            self._scroll_to_badge(badge)
            self.desc_box.show_move(badge.ma)

            # Update eval bar from White's absolute POV
            ev = badge.ma.eval_before
            if ev:
                # eval_before is in side-to-move POV; convert to absolute White POV
                score_cp = ev.score_cp
                mate_in  = ev.mate_in
                if badge.ma.color == chess.BLACK:
                    # Black's side-to-move score: negate for White's POV
                    score_cp = -score_cp if score_cp is not None else None
                    mate_in  = -mate_in  if mate_in  is not None else None
                self.eval_bar.set_score(score_cp, mate_in)

    def set_eval(self, score_cp: int | None, mate_in: int | None = None):
        """Update eval bar live (e.g. during play)."""
        self.eval_bar.set_score(score_cp, mate_in)

    def clear(self):
        """Reset the panel to empty state."""
        self._analysis = None
        self._selected = None
        self._clear_moves()
        self.white_card.update_stats(0.0, {})
        self.black_card.update_stats(0.0, {})
        self.desc_box.clear()
        self.eval_bar.reset()

    # ── Internals ──────────────────────────────────────────────────────────────

    def _clear_moves(self):
        self._badges.clear()
        while self._move_layout.count() > 1:   # keep the stretch
            item = self._move_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _badge_for_ply(self, ply: int) -> MoveBadge | None:
        return next((b for b in self._badges if b.ma.ply == ply), None)

    def _on_badge_clicked(self, ply: int):
        self.select_ply(ply)
        self.move_selected.emit(ply)

    def _scroll_to_badge(self, badge: MoveBadge):
        """Scroll the move list to keep the selected badge visible."""
        self._scroll.ensureWidgetVisible(badge, 0, 40)