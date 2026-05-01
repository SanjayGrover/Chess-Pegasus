"""
board_widget.py  —  Interactive Chessboard Widget
===================================================
A PyQt6 widget that renders a fully playable chessboard.

Features:
  • Click-to-select + click-to-move  (no drag needed, but drag also works)
  • Legal move dots shown on hover/select
  • Last-move highlight (golden tint)
  • Check highlight (red king square)
  • Flippable board (play as Black)
  • Emits signals:  move_made(chess.Move), position_changed(chess.Board)

Used by:  play_tab (Part 3)  and  analyze_tab (Part 4)
"""

import chess
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore    import Qt, QRect, QPoint, QPointF, QSize, pyqtSignal
from PyQt6.QtGui     import (
    QPainter, QColor, QFont, QFontMetrics,
    QBrush, QPen, QLinearGradient, QRadialGradient
)


# ── Colour palette ─────────────────────────────────────────────────────────────

LIGHT_SQ        = QColor("#f0d9b5")   # classic lichess cream
DARK_SQ         = QColor("#b58863")   # classic lichess brown
SELECTED_LIGHT  = QColor("#f6f669")   # yellow tint – selected piece on light sq
SELECTED_DARK   = QColor("#baca2b")   # yellow tint – selected piece on dark sq
LAST_MOVE_LIGHT = QColor("#cdd26a")   # last-move light square
LAST_MOVE_DARK  = QColor("#aaa23a")   # last-move dark square
CHECK_COLOR     = QColor("#e84040")   # king-in-check radial glow
LEGAL_DOT       = QColor(0, 0, 0, 80) # semi-transparent dot for legal moves
LEGAL_CAPTURE   = QColor(0, 0, 0, 60) # ring for legal capture squares
COORD_LIGHT     = QColor("#b58863")   # rank/file labels on light squares
COORD_DARK      = QColor("#f0d9b5")   # rank/file labels on dark squares
BORDER_COLOR    = QColor("#3a2a10")

# Unicode chess pieces  (white pieces, black pieces)
PIECE_UNICODE = {
    (chess.PAWN,   chess.WHITE): "♙",
    (chess.KNIGHT, chess.WHITE): "♘",
    (chess.BISHOP, chess.WHITE): "♗",
    (chess.ROOK,   chess.WHITE): "♖",
    (chess.QUEEN,  chess.WHITE): "♕",
    (chess.KING,   chess.WHITE): "♔",
    (chess.PAWN,   chess.BLACK): "♟",
    (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK,   chess.BLACK): "♜",
    (chess.QUEEN,  chess.BLACK): "♛",
    (chess.KING,   chess.BLACK): "♚",
}

PIECE_COLOR_WHITE = QColor("#ffffff")
PIECE_COLOR_BLACK = QColor("#1a1a1a")
PIECE_SHADOW      = QColor(0, 0, 0, 100)


class BoardWidget(QWidget):
    """Renders a chess.Board and handles user interaction."""

    # Emitted after the user successfully completes a move
    move_made         = pyqtSignal(object)   # chess.Move
    # Emitted whenever the board position changes (after move or set_board)
    position_changed  = pyqtSignal(object)   # chess.Board
    # Emitted when a square is clicked (for analysis arrow navigation etc.)
    square_clicked    = pyqtSignal(int)      # chess.square

    def __init__(self, parent=None, flipped: bool = False):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(QSize(360, 360))

        self._board        : chess.Board       = chess.Board()
        self._flipped      : bool              = flipped
        self._selected_sq  : int | None        = None   # square user clicked
        self._legal_targets: set[int]          = set()  # squares piece can go to
        self._last_move    : chess.Move | None = None
        self._hover_sq      : int | None        = None
        self._interactive   : bool              = True   # False in analysis replay
        self._game_over_text: str | None        = None   # set when game ends

        self.setMouseTracking(True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_board(self, board: chess.Board, last_move: chess.Move | None = None):
        """Replace the displayed position."""
        self._board          = board.copy()
        self._last_move      = last_move
        self._selected_sq    = None
        self._legal_targets  = set()
        self._game_over_text = None
        self.update()
        self.position_changed.emit(self._board)

    def set_interactive(self, value: bool):
        """Disable interaction during analysis playback."""
        self._interactive = value
        self._selected_sq = None
        self._legal_targets = set()
        self.update()

    def flip(self):
        self._flipped = not self._flipped
        self.update()
        
    def reset_game(self):
        """Clears the game-over state and resets the board to the starting position."""
        self._board = chess.Board()
        self._last_move = None
        self._selected_sq = None
        self._legal_targets = set()
        self._game_over_text = None
        self._interactive = True
        self.update()
        self.position_changed.emit(self._board)

    @property
    def board(self) -> chess.Board:
        return self._board

    def push_move(self, move: chess.Move):
        """Push a move programmatically (e.g. engine move)."""
        if move in self._board.legal_moves:
            self._board.push(move)
            self._last_move   = move
            self._selected_sq = None
            self._legal_targets = set()
            self.update()
            self.position_changed.emit(self._board)
            self._check_game_over()

    def undo_move(self):
        if self._board.move_stack:
            self._board.pop()
            self._last_move = (
                self._board.peek() if self._board.move_stack else None
            )
            self._selected_sq  = None
            self._legal_targets = set()
            self.update()
            self.position_changed.emit(self._board)

    # ── Geometry helpers ───────────────────────────────────────────────────────

    def _square_size(self) -> int:
        return min(self.width(), self.height()) // 8

    def _board_origin(self) -> QPoint:
        sq = self._square_size()
        bw = sq * 8
        return QPoint((self.width() - bw) // 2, (self.height() - bw) // 2)

    def _sq_to_rect(self, square: int) -> QRect:
        sq   = self._square_size()
        orig = self._board_origin()
        col  = chess.square_file(square)
        row  = chess.square_rank(square)
        if self._flipped:
            x = (7 - col) * sq + orig.x()
            y = row       * sq + orig.y()
        else:
            x =       col * sq + orig.x()
            y = (7 - row) * sq + orig.y()
        return QRect(x, y, sq, sq)

    def _point_to_square(self, point: QPoint) -> int | None:
        sq   = self._square_size()
        orig = self._board_origin()
        x    = point.x() - orig.x()
        y    = point.y() - orig.y()
        if not (0 <= x < sq * 8 and 0 <= y < sq * 8):
            return None
        col = x // sq
        row = y // sq
        if self._flipped:
            col = 7 - col
            row = 7 - row
        else:
            row = 7 - row
        return chess.square(col, row)

    @staticmethod
    def _is_light(square: int) -> bool:
        return (chess.square_file(square) + chess.square_rank(square)) % 2 == 1

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._draw_border(p)
        self._draw_squares(p)
        self._draw_coordinates(p)
        self._draw_pieces(p)
        self._draw_legal_dots(p)
        self._draw_game_over_overlay(p)
        p.end()

    def _draw_border(self, p: QPainter):
        sq   = self._square_size()
        orig = self._board_origin()
        rect = QRect(orig.x() - 2, orig.y() - 2, sq * 8 + 4, sq * 8 + 4)
        p.setPen(QPen(BORDER_COLOR, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)

    def _draw_squares(self, p: QPainter):
        in_check = self._board.is_check()
        king_sq  = self._board.king(self._board.turn) if in_check else None

        for sq in chess.SQUARES:
            rect  = self._sq_to_rect(sq)
            light = self._is_light(sq)

            # Base colour
            if sq == self._selected_sq:
                color = SELECTED_LIGHT if light else SELECTED_DARK
            elif self._last_move and sq in (self._last_move.from_square,
                                            self._last_move.to_square):
                color = LAST_MOVE_LIGHT if light else LAST_MOVE_DARK
            else:
                color = LIGHT_SQ if light else DARK_SQ

            p.fillRect(rect, color)

            # Check glow on king square
            if sq == king_sq:
                c    = rect.center()
                grad = QRadialGradient(c.x(), c.y(), rect.width() * 0.6)
                grad.setColorAt(0.0, QColor(255, 0, 0, 180))
                grad.setColorAt(1.0, QColor(255, 0, 0, 0))
                p.fillRect(rect, QBrush(grad))

    def _draw_coordinates(self, p: QPainter):
        sq      = self._square_size()
        orig    = self._board_origin()
        font    = QFont("Segoe UI", max(7, sq // 7), QFont.Weight.Bold)
        p.setFont(font)
        fm      = QFontMetrics(font)
        padding = 3

        files = "abcdefgh"
        ranks = "12345678"

        for i in range(8):
            # File letters — bottom edge of each column
            col   = i if not self._flipped else 7 - i
            x     = orig.x() + i * sq + padding
            y     = orig.y() + 8 * sq - padding
            light = self._is_light(chess.square(col, 0))
            p.setPen(COORD_DARK if light else COORD_LIGHT)
            p.drawText(x, y, files[col])

            # Rank numbers — left edge of each row
            row   = 7 - i if not self._flipped else i
            x2    = orig.x() + padding
            y2    = orig.y() + i * sq + fm.ascent() + padding
            light2 = self._is_light(chess.square(0, row))
            p.setPen(COORD_DARK if light2 else COORD_LIGHT)
            p.drawText(x2, y2, ranks[row])

    def _draw_pieces(self, p: QPainter):
        sq_size = self._square_size()
        font    = QFont("Segoe UI", int(sq_size * 0.72))
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        p.setFont(font)

        for square in chess.SQUARES:
            piece = self._board.piece_at(square)
            if piece is None:
                continue

            rect   = self._sq_to_rect(square)
            symbol = PIECE_UNICODE[(piece.piece_type, piece.color)]

            # Shadow
            p.setPen(PIECE_SHADOW)
            shadow_rect = rect.translated(1, 2)
            p.drawText(shadow_rect, Qt.AlignmentFlag.AlignCenter, symbol)

            # Piece
            p.setPen(PIECE_COLOR_WHITE if piece.color == chess.WHITE else PIECE_COLOR_BLACK)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, symbol)

    def _draw_legal_dots(self, p: QPainter):
        if not self._legal_targets:
            return
        sq_size = self._square_size()
        for target in self._legal_targets:
            rect     = self._sq_to_rect(target)
            cx, cy   = rect.center().x(), rect.center().y()
            occupied = self._board.piece_at(target) is not None

            if occupied:
                # Draw a hollow ring (capture indicator)
                pen = QPen(LEGAL_CAPTURE, sq_size * 0.1)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = int(sq_size * 0.44)
                p.drawEllipse(QPoint(cx, cy), r, r)
            else:
                # Filled dot
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(LEGAL_DOT))
                r = int(sq_size * 0.18)
                p.drawEllipse(QPoint(cx, cy), r, r)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(Qt.PenStyle.NoPen)

    def _draw_game_over_overlay(self, p: QPainter):
        """Semi-transparent banner across the board announcing the result."""
        if not self._game_over_text:
            return

        sq_size = self._square_size()
        orig    = self._board_origin()
        board_rect = QRect(orig.x(), orig.y(), sq_size * 8, sq_size * 8)

        # Dark translucent full-board wash
        p.fillRect(board_rect, QColor(0, 0, 0, 140))

        # Banner strip in the middle third
        banner_h = max(70, sq_size * 2)
        banner_y = orig.y() + (sq_size * 8 - banner_h) // 2
        banner   = QRect(orig.x(), banner_y, sq_size * 8, banner_h)

        # Gold gradient banner background
        grad = QLinearGradient(QPointF(banner.topLeft()), QPointF(banner.bottomLeft()))
        grad.setColorAt(0.0, QColor("#3a2a00"))
        grad.setColorAt(0.5, QColor("#5a4200"))
        grad.setColorAt(1.0, QColor("#3a2a00"))
        p.fillRect(banner, QBrush(grad))

        # Gold border lines
        p.setPen(QPen(QColor("#c9a96e"), 2))
        p.drawLine(banner.topLeft(),    banner.topRight())
        p.drawLine(banner.bottomLeft(), banner.bottomRight())

        # Main result text
        lines = self._game_over_text.split("\n")
        main_text = lines[0]
        sub_text  = lines[1] if len(lines) > 1 else ""

        # FIX: Combine PyQt6 flags safely by casting to int
        main_flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
        sub_flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.AlignmentFlag.AlignBottom) | int(Qt.TextFlag.TextWordWrap)

        main_font = QFont("Segoe UI", max(16, sq_size // 3), QFont.Weight.Bold)
        p.setFont(main_font)
        p.setPen(QColor("#f0d060"))
        p.drawText(banner, main_flags, "\n" + main_text)

        if sub_text:
            sub_font = QFont("Segoe UI", max(10, sq_size // 5))
            p.setFont(sub_font)
            p.setPen(QColor("#c9a96e"))
            p.drawText(banner, sub_flags, sub_text + "\n")

    # ── Mouse interaction ──────────────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        sq = self._point_to_square(event.pos())
        if sq != self._hover_sq:
            self._hover_sq = sq
            self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._game_over_text:
            return   # board is locked after game ends
        if not self._interactive:
            sq = self._point_to_square(event.pos())
            if sq is not None:
                self.square_clicked.emit(sq)
            return

        sq = self._point_to_square(event.pos())
        if sq is None:
            return

        self.square_clicked.emit(sq)

        # ── State machine ──────────────────────────────────────────────────
        if self._selected_sq is None:
            # First click: select a piece of the side to move
            piece = self._board.piece_at(sq)
            if piece and piece.color == self._board.turn:
                self._selected_sq   = sq
                self._legal_targets = {
                    m.to_square
                    for m in self._board.legal_moves
                    if m.from_square == sq
                }
        else:
            if sq in self._legal_targets:
                # Second click on a legal target: make the move
                move = self._build_move(self._selected_sq, sq)
                self._board.push(move)
                self._last_move     = move
                self._selected_sq   = None
                self._legal_targets = set()
                self.update()
                self.move_made.emit(move)
                self.position_changed.emit(self._board)
                self._check_game_over()
            elif sq == self._selected_sq:
                # Click same square: deselect
                self._selected_sq   = None
                self._legal_targets = set()
            else:
                # Click different own piece: re-select
                piece = self._board.piece_at(sq)
                if piece and piece.color == self._board.turn:
                    self._selected_sq   = sq
                    self._legal_targets = {
                        m.to_square
                        for m in self._board.legal_moves
                        if m.from_square == sq
                    }
                else:
                    self._selected_sq   = None
                    self._legal_targets = set()

        self.update()

    def _check_game_over(self):
        """Detect end-of-game and set the overlay text."""
        b = self._board
        if b.is_checkmate():
            winner = "White" if b.turn == chess.BLACK else "Black"
            self._game_over_text = f"Checkmate!  {winner} wins ♚\nClick Reset to play again"
        elif b.is_stalemate():
            self._game_over_text = "Stalemate!\nIt's a draw — Click Reset to play again"
        elif b.is_insufficient_material():
            self._game_over_text = "Draw!\nInsufficient material"
        elif b.is_seventyfive_moves():
            self._game_over_text = "Draw!\n75-move rule"
        elif b.is_fivefold_repetition():
            self._game_over_text = "Draw!\nFivefold repetition"
        else:
            return   # game still going
        self._interactive = False
        self.update()

    def _build_move(self, from_sq: int, to_sq: int) -> chess.Move:
        """Build a Move, handling pawn promotion (auto-queen for now)."""
        piece = self._board.piece_at(from_sq)
        promotion = None
        if piece and piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and chess.square_rank(to_sq) == 7) or \
               (piece.color == chess.BLACK and chess.square_rank(to_sq) == 0):
                promotion = chess.QUEEN   # TODO: promotion dialog in Part 3
        return chess.Move(from_sq, to_sq, promotion=promotion)

    # ── Resize ─────────────────────────────────────────────────────────────────

    def resizeEvent(self, _event):
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(600, 600)

    def heightForWidth(self, w: int) -> int:
        return w

    def hasHeightForWidth(self) -> bool:
        return True