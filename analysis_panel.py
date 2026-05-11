"""
analysis_panel.py  —  Analysis Side Panel
==========================================
Two stacked panels controlled by AnalysisPanel:

  1. GameReviewPanel  — shown before analysis runs
     • Player names + pawn avatars
     • Accuracy scores
     • Classification table (icon + label + white count + black count)
     matching chess.com's Game Review layout (Image 2)

  2. MoveListPanel    — shown after analysis runs (replaces Game Review)
     • Scrollable move list with classification badges
     • Per-move description box
     • Eval bar

The board_widget's classification badge (circular icon on destination
square) is driven by AnalysisPanel.select_ply().
"""

import chess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QSizePolicy, QStackedWidget,
    QGridLayout, QPushButton
)
from PyQt6.QtCore  import Qt, pyqtSignal, QPoint, QRect, QSize
from PyQt6.QtGui   import (
    QPainter, QColor, QFont, QBrush, QPen,
    QLinearGradient, QFontMetrics
)

from analyzer import GameAnalysis, MoveAnalysis, Classification


# ── Classification display data ────────────────────────────────────────────────
# Matches chess.com icons (Image 2):
#   symbol shown inside circle, bg_color, label, text_color for counts

CLASS_DISPLAY = {
    Classification.BRILLIANT  : ("!!",  "#21b89a", "Brilliant",  "#21b89a"),
    Classification.GREAT      : ("!",   "#4a90d9", "Great",      "#4a90d9"),
    Classification.BEST       : ("★",   "#5c9e3a", "Best",       "#5c9e3a"),
    Classification.EXCELLENT  : ("👍",  "#5c9e3a", "Excellent",  "#5c9e3a"),
    Classification.GOOD       : ("✓",   "#5c9e3a", "Good",       "#5c9e3a"),
    Classification.INACCURACY : ("?!",  "#e8a02a", "Inaccuracy", "#e8a02a"),
    Classification.MISTAKE    : ("?",   "#d4622a", "Mistake",    "#d4622a"),
    Classification.BLUNDER    : ("??",  "#c62828", "Blunder",    "#c62828"),
    Classification.FORCED     : ("♟",   "#888888", "Forced",     "#888888"),
}

# Order to display in the review table (matches Image 2)
REVIEW_ORDER = [
    Classification.BRILLIANT,
    Classification.GREAT,
    Classification.BEST,
    Classification.EXCELLENT,
    Classification.GOOD,
    Classification.INACCURACY,
    Classification.MISTAKE,
    Classification.BLUNDER,
]


# ── Eval Bar ───────────────────────────────────────────────────────────────────

class EvalBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(26)
        self.setMinimumHeight(200)
        self._white_fraction = 0.5
        self._label_text     = "0.0"

    def set_score(self, score_cp, mate_in=None):
        import math
        if mate_in is not None:
            self._white_fraction = 1.0 if mate_in > 0 else 0.0
            self._label_text     = f"M{abs(mate_in)}"
        elif score_cp is not None:
            frac = 1.0 / (1.0 + math.exp(-score_cp / 400.0))
            self._white_fraction = max(0.05, min(0.95, frac))
            pawns = score_cp / 100.0
            self._label_text = f"{'+'if pawns>0 else ''}{pawns:.1f}"
        else:
            self._white_fraction = 0.5
            self._label_text     = "0.0"
        self.update()

    def reset(self):
        self._white_fraction = 0.5
        self._label_text     = "0.0"
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#1a1a1a"))
        white_h = int(h * (1.0 - self._white_fraction))
        p.fillRect(2, 0,        w - 4, white_h,      QColor("#2a2a2a"))
        p.fillRect(2, white_h,  w - 4, h - white_h,  QColor("#f0d9b5"))
        p.setPen(QPen(QColor("#888"), 1))
        p.drawLine(2, h // 2, w - 2, h // 2)
        font = QFont("Segoe UI", 7, QFont.Weight.Bold)
        p.setFont(font)
        col = QColor("#f0d9b5") if self._white_fraction < 0.5 else QColor("#2a2a2a")
        p.setPen(col)
        p.drawText(QRect(0, h // 2 - 10, w, 20), Qt.AlignmentFlag.AlignCenter, self._label_text)
        p.end()


# ── Classification icon widget ─────────────────────────────────────────────────

class ClassIcon(QWidget):
    """A circular icon matching chess.com's classification badges."""

    def __init__(self, cls: Classification, size: int = 32, parent=None):
        super().__init__(parent)
        self._cls  = cls
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sym, bg, _, _ = CLASS_DISPLAY.get(self._cls, ("?", "#888", "", ""))
        r  = self._size // 2
        cx = cy = r
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(bg)))
        p.drawEllipse(QPoint(cx, cy), r - 1, r - 1)
        font_size = max(7, int(r * 0.75))
        # Use smaller font for multi-char symbols
        if len(sym) > 1:
            font_size = max(6, int(r * 0.55))
        font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(0, 0, self._size, self._size), Qt.AlignmentFlag.AlignCenter, sym)
        p.end()


# ── Game Review Panel ──────────────────────────────────────────────────────────

class GameReviewPanel(QWidget):
    """
    Shown BEFORE analysis runs.
    After analysis completes, AnalysisPanel swaps this out for MoveListPanel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        # ── Title ──────────────────────────────────────────────────────────
        title = QLabel("Game Review")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color:#e8d5b0; padding-bottom:10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # ── Player header row ──────────────────────────────────────────────
        header = QGridLayout()
        header.setColumnStretch(0, 2)
        header.setColumnStretch(1, 1)
        header.setColumnStretch(2, 1)

        lbl_players = QLabel("Players")
        lbl_players.setStyleSheet("color:#888; font-size:12px;")
        header.addWidget(lbl_players, 0, 0, Qt.AlignmentFlag.AlignVCenter)

        self.white_avatar = self._make_avatar("♙", "#5c9e3a")
        self.black_avatar = self._make_avatar("♟", "#888888")
        header.addWidget(self.white_avatar, 0, 1, Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.black_avatar, 0, 2, Qt.AlignmentFlag.AlignCenter)

        self.white_name_lbl = QLabel("White")
        self.white_name_lbl.setStyleSheet("color:#e8d5b0; font-size:11px; font-weight:600;")
        self.white_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.black_name_lbl = QLabel("Black")
        self.black_name_lbl.setStyleSheet("color:#e8d5b0; font-size:11px; font-weight:600;")
        self.black_name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.white_name_lbl, 1, 1, Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.black_name_lbl, 1, 2, Qt.AlignmentFlag.AlignCenter)

        # Accuracy row
        lbl_acc = QLabel("Accuracy")
        lbl_acc.setStyleSheet("color:#888; font-size:12px;")
        header.addWidget(lbl_acc, 2, 0, Qt.AlignmentFlag.AlignVCenter)

        self.white_acc_box = self._make_acc_box("—")
        self.black_acc_box = self._make_acc_box("—")
        header.addWidget(self.white_acc_box, 2, 1, Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.black_acc_box, 2, 2, Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(header)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color:#3a3020; margin: 10px 0;")
        layout.addWidget(div)

        # ── Classification table ───────────────────────────────────────────
        self._count_labels: dict[Classification, tuple[QLabel, QLabel]] = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(0, 3)   # label
        grid.setColumnStretch(1, 1)   # white count
        grid.setColumnStretch(2, 1)   # icon
        grid.setColumnStretch(3, 1)   # black count

        for row_idx, cls in enumerate(REVIEW_ORDER):
            sym, bg, label_text, count_color = CLASS_DISPLAY[cls]

            # Row label
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color:#cccccc; font-size:12px;")
            grid.addWidget(lbl, row_idx, 0, Qt.AlignmentFlag.AlignVCenter)

            # White count
            w_count = QLabel("—")
            w_count.setStyleSheet(f"color:{count_color}; font-size:13px; font-weight:700;")
            w_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(w_count, row_idx, 1, Qt.AlignmentFlag.AlignCenter)

            # Icon
            icon = ClassIcon(cls, size=30)
            grid.addWidget(icon, row_idx, 2, Qt.AlignmentFlag.AlignCenter)

            # Black count
            b_count = QLabel("—")
            b_count.setStyleSheet(f"color:{count_color}; font-size:13px; font-weight:700;")
            b_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(b_count, row_idx, 3, Qt.AlignmentFlag.AlignCenter)

            self._count_labels[cls] = (w_count, b_count)

        layout.addLayout(grid)
        layout.addStretch()

        # Hint text
        hint = QLabel("Click 'Analyse' to see the full review")
        hint.setStyleSheet("color:#555; font-size:11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def _make_avatar(self, symbol: str, border_color: str) -> QLabel:
        lbl = QLabel(symbol)
        lbl.setFont(QFont("Segoe UI", 22))
        lbl.setFixedSize(52, 52)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"background:#2a2a2a; border:2px solid {border_color};"
            f"border-radius:4px; color:#e8d5b0;"
        )
        return lbl

    def _make_acc_box(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl.setFixedSize(64, 36)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "background:#2a2a2a; border:1px solid #3a3020;"
            "border-radius:4px; color:#e8d5b0;"
        )
        return lbl

    def update_review(self, analysis: "GameAnalysis", white_name: str = "White", black_name: str = "Black"):
        self.white_name_lbl.setText(white_name)
        self.black_name_lbl.setText(black_name)
        self.white_acc_box.setText(f"{analysis.white_accuracy:.1f}")
        self.black_acc_box.setText(f"{analysis.black_accuracy:.1f}")

        for cls, (w_lbl, b_lbl) in self._count_labels.items():
            wc = analysis.white_counts.get(cls, 0)
            bc = analysis.black_counts.get(cls, 0)
            w_lbl.setText(str(wc))
            b_lbl.setText(str(bc))

    def clear(self):
        self.white_name_lbl.setText("White")
        self.black_name_lbl.setText("Black")
        self.white_acc_box.setText("—")
        self.black_acc_box.setText("—")
        for w_lbl, b_lbl in self._count_labels.values():
            w_lbl.setText("—")
            b_lbl.setText("—")


# ── Move Badge ─────────────────────────────────────────────────────────────────

class MoveBadge(QWidget):
    clicked = pyqtSignal(int)

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

        sym, bg, label_text, _ = CLASS_DISPLAY.get(
            self.ma.classification,
            ("?", "#888", "Unknown", "#888")
        )

        if self.ma.is_white:
            num = QLabel(f"{self.ma.move_number}.")
            num.setFixedWidth(24)
            num.setStyleSheet("color:#555; font-size:11px;")
            layout.addWidget(num)
        else:
            sp = QLabel("")
            sp.setFixedWidth(24)
            layout.addWidget(sp)

        san = QLabel(self.ma.move_san)
        san.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        san.setStyleSheet("color:#e8d5b0;")
        layout.addWidget(san)
        layout.addStretch()

        icon = ClassIcon(self.ma.classification, size=22)
        layout.addWidget(icon)

        if self.ma.cp_loss and self.ma.cp_loss > 0:
            cp = QLabel(f"−{self.ma.cp_loss}")
            cp.setFont(QFont("Segoe UI", 9))
            cp.setStyleSheet("color:#666; min-width:32px;")
            cp.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(cp)

        self._update_bg()

    def set_selected(self, val: bool):
        self.selected = val
        self._update_bg()

    def _update_bg(self):
        self.setStyleSheet(
            "background:#3a3020; border-radius:4px;" if self.selected
            else "background:transparent;"
        )

    def mousePressEvent(self, _):
        self.clicked.emit(self.ma.ply)

    def enterEvent(self, _):
        if not self.selected:
            self.setStyleSheet("background:#252018; border-radius:4px;")

    def leaveEvent(self, _):
        self._update_bg()


# ── Description Box ────────────────────────────────────────────────────────────

class DescriptionBox(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#1e1e1e; border:1px solid #3a3020; border-radius:8px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.title_lbl = QLabel("Select a move")
        self.title_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setStyleSheet("color:#c9a96e; border:none;")
        layout.addWidget(self.title_lbl)

        self.desc_lbl = QLabel("")
        self.desc_lbl.setFont(QFont("Segoe UI", 10))
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet("color:#a0907a; border:none;")
        layout.addWidget(self.desc_lbl)

        self.best_lbl = QLabel("")
        self.best_lbl.setFont(QFont("Segoe UI", 10))
        self.best_lbl.setWordWrap(True)
        self.best_lbl.setStyleSheet("color:#5a8a3c; border:none;")
        layout.addWidget(self.best_lbl)

    def show_move(self, ma: MoveAnalysis):
        sym, bg, label_text, _ = CLASS_DISPLAY.get(
            ma.classification, ("?", "#888", "?", "#888")
        )
        side = "White" if ma.is_white else "Black"
        dot  = "." if ma.is_white else "…"
        self.title_lbl.setText(f"{side} {ma.move_number}{dot} {ma.move_san} — {label_text}")
        self.desc_lbl.setText(ma.description())
        if ma.best_move_san and ma.best_move != ma.move:
            cp_str = f"  (saves {ma.cp_loss} cp)" if ma.cp_loss else ""
            self.best_lbl.setText(f"✓ Best was {ma.best_move_san}{cp_str}")
        else:
            self.best_lbl.setText("")

    def clear(self):
        self.title_lbl.setText("Select a move")
        self.desc_lbl.setText("")
        self.best_lbl.setText("")


# ── Move List Panel ────────────────────────────────────────────────────────────

class MoveListPanel(QWidget):
    move_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._badges  : list[MoveBadge] = []
        self._selected: int | None      = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel("Move Analysis")
        header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        header.setStyleSheet("color:#e8d5b0;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        self.desc_box = DescriptionBox()
        layout.addWidget(self.desc_box)

        moves_lbl = QLabel("MOVES")
        moves_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        moves_lbl.setStyleSheet("color:#555; letter-spacing:1px;")
        layout.addWidget(moves_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;")

        self._container = QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(1)
        self._list_layout.addStretch()

        scroll.setWidget(self._container)
        self._scroll = scroll
        layout.addWidget(scroll)

    def load(self, analysis: "GameAnalysis"):
        self._clear()
        for ma in analysis.moves:
            badge = MoveBadge(ma)
            badge.clicked.connect(self._on_badge_clicked)
            self._badges.append(badge)
            self._list_layout.insertWidget(self._list_layout.count() - 1, badge)
        self.desc_box.clear()

    def select_ply(self, ply: int):
        if self._selected is not None:
            old = self._badge_for(self._selected)
            if old:
                old.set_selected(False)
        self._selected = ply
        badge = self._badge_for(ply)
        if badge:
            badge.set_selected(True)
            self._scroll.ensureWidgetVisible(badge, 0, 40)
            self.desc_box.show_move(badge.ma)

    def clear(self):
        self._clear()
        self.desc_box.clear()

    def _clear(self):
        self._badges.clear()
        self._selected = None
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _badge_for(self, ply: int):
        return next((b for b in self._badges if b.ma.ply == ply), None)

    def _on_badge_clicked(self, ply: int):
        self.select_ply(ply)
        self.move_selected.emit(ply)


# ── Main Analysis Panel ────────────────────────────────────────────────────────

class AnalysisPanel(QWidget):
    """
    Container that holds:
      • EvalBar (always on left edge)
      • QStackedWidget:
          page 0 → GameReviewPanel (before analysis)
          page 1 → MoveListPanel   (after analysis)
    """

    move_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.eval_bar = EvalBar()
        outer.addWidget(self.eval_bar)

        self._stack = QStackedWidget()
        self.review_panel = GameReviewPanel()
        self.movelist_panel = MoveListPanel()
        self.movelist_panel.move_selected.connect(self.move_selected)
        self._stack.addWidget(self.review_panel)    # index 0
        self._stack.addWidget(self.movelist_panel)  # index 1
        self._stack.setCurrentIndex(0)

        outer.addWidget(self._stack)

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_analysis(self, analysis: "GameAnalysis",
                      white_name: str = "White", black_name: str = "Black"):
        """
        Called when analysis completes.
        1. Updates the Game Review panel with stats
        2. Loads the move list
        3. Switches to the move list panel
        """
        self.review_panel.update_review(analysis, white_name, black_name)
        self.movelist_panel.load(analysis)
        self._stack.setCurrentIndex(1)   # switch to move list

    def show_review(self):
        """Switch back to the Game Review summary panel."""
        self._stack.setCurrentIndex(0)

    def select_ply(self, ply: int):
        if self._stack.currentIndex() == 1:
            self.movelist_panel.select_ply(ply)
            # Update eval bar
            badge = self.movelist_panel._badge_for(ply)
            if badge:
                ev = badge.ma.eval_before
                if ev:
                    score_cp = ev.score_cp
                    mate_in  = ev.mate_in
                    if badge.ma.color == chess.BLACK:
                        score_cp = -score_cp if score_cp is not None else None
                        mate_in  = -mate_in  if mate_in  is not None else None
                    self.eval_bar.set_score(score_cp, mate_in)

    def set_eval(self, score_cp, mate_in=None):
        self.eval_bar.set_score(score_cp, mate_in)

    def clear(self):
        self.review_panel.clear()
        self.movelist_panel.clear()
        self.eval_bar.reset()
        self._stack.setCurrentIndex(0)   # back to review on clear

    def classification_for_ply(self, ply: int):
        """Return (symbol, bg_color) for the given ply, or None."""
        badge = self.movelist_panel._badge_for(ply)
        if badge:
            sym, bg, _, _ = CLASS_DISPLAY.get(badge.ma.classification, (None, None, None, None))
            if sym and bg:
                return sym, bg
        return None