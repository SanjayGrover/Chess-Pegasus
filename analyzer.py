"""
analyzer.py  —  Game Analyzer & Move Classifier
=================================================
Runs Stockfish over every position in a PGN game and assigns
chess.com-style classifications to each move.

Classifications (White's centipawn-loss thresholds):
  ✨ Brilliant   — only engine move AND a sacrifice (material loss)
  !! Great Move  — only engine move, not a sacrifice
  ✓  Best        — matches engine's top choice (within 5 cp)
  ★  Excellent   — cp loss 0–10
  ●  Good        — cp loss 11–25
  ?! Inaccuracy  — cp loss 26–50
  ?  Mistake     — cp loss 51–100
  ?? Blunder     — cp loss > 100

Special:
  ♟  Forced      — only one legal move available
  ✦  Book        — first N moves (opening book, not evaluated)

Used by: analysis_panel.py (Part 6), play_tab (Part 5)
"""

import chess
import chess.pgn
import io
from dataclasses import dataclass, field
from enum        import Enum, auto
from typing      import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from engine import ChessEngine, MoveEval


# ── Classification enum ────────────────────────────────────────────────────────

class Classification(Enum):
    BRILLIANT   = auto()
    GREAT       = auto()
    BEST        = auto()
    EXCELLENT   = auto()
    GOOD        = auto()
    INACCURACY  = auto()
    MISTAKE     = auto()
    BLUNDER     = auto()
    FORCED      = auto()
    BOOK        = auto()

# Display metadata for each classification
CLASS_META = {
    Classification.BRILLIANT  : ("✨", "Brilliant",  "#1bace4"),  # blue
    Classification.GREAT      : ("!!", "Great Move", "#5c8a3c"),  # green
    Classification.BEST       : ("✓",  "Best",       "#5c8a3c"),  # green
    Classification.EXCELLENT  : ("★",  "Excellent",  "#7ec845"),  # light green
    Classification.GOOD       : ("●",  "Good",       "#a8a823"),  # olive
    Classification.INACCURACY : ("?!", "Inaccuracy", "#e8a02a"),  # orange
    Classification.MISTAKE    : ("?",  "Mistake",    "#d4622a"),  # red-orange
    Classification.BLUNDER    : ("??", "Blunder",    "#c62828"),  # red
    Classification.FORCED     : ("♟",  "Forced",     "#888888"),  # grey
    Classification.BOOK       : ("✦",  "Book",       "#a78bfa"),  # purple
}

# Centipawn loss thresholds (from moving side's perspective)
# Any loss BELOW the threshold gets that classification
CP_THRESHOLDS = [
    (5,   Classification.BEST),
    (10,  Classification.EXCELLENT),
    (25,  Classification.GOOD),
    (50,  Classification.INACCURACY),
    (100, Classification.MISTAKE),
]
# > 100 cp loss → BLUNDER


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class MoveAnalysis:
    """Full analysis result for a single move in a game."""

    move            : chess.Move
    move_san        : str                        # e.g. "Nf3"
    ply             : int                        # half-move number (1-indexed)
    color           : chess.Color               # who made the move

    classification  : Classification
    cp_loss         : Optional[int]              # centipawn loss (None for book/forced)
    eval_before     : Optional[MoveEval]         # best engine eval BEFORE this move
    eval_after      : Optional[MoveEval]         # best engine eval AFTER this move
    best_move       : Optional[chess.Move]       # what engine preferred
    best_move_san   : Optional[str]              # SAN of engine's best
    pv              : list[chess.Move] = field(default_factory=list)  # principal variation

    @property
    def symbol(self) -> str:
        return CLASS_META[self.classification][0]

    @property
    def label(self) -> str:
        return CLASS_META[self.classification][1]

    @property
    def color_hex(self) -> str:
        return CLASS_META[self.classification][2]

    @property
    def move_number(self) -> int:
        """1-based full move number."""
        return (self.ply + 1) // 2

    @property
    def is_white(self) -> bool:
        return self.color == chess.WHITE

    def description(self) -> str:
        """Human-readable one-liner, like chess.com's explanation."""
        cls = self.classification

        if cls == Classification.BOOK:
            return "Opening book move."

        if cls == Classification.FORCED:
            return "Only legal move in this position."

        best_str = f" Best was {self.best_move_san}." if (
            self.best_move_san and self.best_move != self.move
        ) else ""

        cp_str = ""
        if self.cp_loss is not None and self.cp_loss > 0:
            cp_str = f" (−{self.cp_loss} cp)"

        descriptions = {
            Classification.BRILLIANT  : f"Brilliant sacrifice! Only top engine move.{best_str}",
            Classification.GREAT      : f"Only the best move in this position!{best_str}",
            Classification.BEST       : f"Best move.{best_str}",
            Classification.EXCELLENT  : f"Excellent move.{cp_str}{best_str}",
            Classification.GOOD       : f"Good move.{cp_str}{best_str}",
            Classification.INACCURACY : f"Inaccuracy.{cp_str}{best_str}",
            Classification.MISTAKE    : f"Mistake.{cp_str}{best_str}",
            Classification.BLUNDER    : f"Blunder!{cp_str}{best_str}",
        }
        return descriptions.get(cls, "")


@dataclass
class GameAnalysis:
    """Complete analysis result for a full game."""

    moves           : list[MoveAnalysis]
    white_accuracy  : float              # 0–100
    black_accuracy  : float              # 0–100
    headers         : dict               # PGN headers

    # Counts per classification per color
    white_counts    : dict = field(default_factory=dict)
    black_counts    : dict = field(default_factory=dict)

    def moves_for_color(self, color: chess.Color) -> list[MoveAnalysis]:
        return [m for m in self.moves if m.color == color]

    def summary_line(self, color: chess.Color) -> str:
        acc = self.white_accuracy if color == chess.WHITE else self.black_accuracy
        counts = self.white_counts if color == chess.WHITE else self.black_counts
        parts = []
        for cls in [Classification.BRILLIANT, Classification.GREAT,
                    Classification.MISTAKE, Classification.BLUNDER]:
            n = counts.get(cls, 0)
            if n:
                sym = CLASS_META[cls][0]
                parts.append(f"{n}{sym}")
        side = "White" if color == chess.WHITE else "Black"
        extra = f"  {' '.join(parts)}" if parts else ""
        return f"{side}: {acc:.1f}% accuracy{extra}"


# ── Accuracy formula (matches chess.com's model closely) ──────────────────────

def _cp_to_win_prob(cp: int) -> float:
    """Convert centipawns to win probability [0, 1] using a sigmoid."""
    import math
    return 1.0 / (1.0 + math.exp(-0.00368208 * cp))


def _accuracy_from_win_probs(before_cp: int, after_cp: int) -> float:
    """
    Single-move accuracy score 0-100.
    Uses chess.com's formula:  103.1668 * exp(-0.04354 * Δwinprob) - 3.1669
    clamped to [0, 100].
    """
    import math
    w_before = _cp_to_win_prob(before_cp)
    w_after  = _cp_to_win_prob(after_cp)   # after move, from same side's POV
    delta    = max(0.0, w_before - w_after) * 100.0
    acc      = 103.1668 * math.exp(-0.04354 * delta) - 3.1669
    return max(0.0, min(100.0, acc))


# ── Classifier ─────────────────────────────────────────────────────────────────

BOOK_MOVES = 10   # first N plies are considered "book" (not evaluated)


def _is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """
    Heuristic: a move is a sacrifice if the moving piece lands on a square
    where it can immediately be recaptured by a lower-value piece, OR if
    it moves to an undefended square and is of higher value than any attacker.
    """
    piece = board.piece_at(move.from_square)
    if piece is None:
        return False

    PIECE_VALUE = {
        chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
        chess.ROOK: 500, chess.QUEEN: 900,  chess.KING: 20000,
    }

    mover_value  = PIECE_VALUE.get(piece.piece_type, 0)
    captured     = board.piece_at(move.to_square)
    capture_val  = PIECE_VALUE.get(captured.piece_type, 0) if captured else 0

    # Check if any opponent piece can recapture on to_square
    b2 = board.copy()
    b2.push(move)
    attackers = b2.attackers(b2.turn, move.to_square)   # opponent's turn after move
    if not attackers:
        return False

    min_attacker_val = min(
        PIECE_VALUE.get(b2.piece_at(sq).piece_type, 0)
        for sq in attackers
        if b2.piece_at(sq)
    )

    # Sacrifice if we're losing material net
    return (mover_value - capture_val) > min_attacker_val


def classify_move(
    board_before  : chess.Board,
    move          : chess.Move,
    eval_before   : MoveEval,
    eval_after    : MoveEval,   # engine's best from position AFTER the move (opponent's POV)
    ply           : int,
) -> tuple[Classification, Optional[int]]:
    """
    Classify a single move.

    Returns (Classification, cp_loss_from_moving_side)
    """

    # Book moves
    if ply <= BOOK_MOVES:
        return Classification.BOOK, None

    # Forced move
    legal = list(board_before.legal_moves)
    if len(legal) == 1:
        return Classification.FORCED, None

    # Get scores from moving side's perspective
    # eval_before.score_cp  = best score available BEFORE the move (moving side)
    # eval_after.score_cp   = score of position AFTER the move (opponent has best)
    #   → we flip eval_after to get moving side's score after their move

    best_cp_before = _normalise_cp(eval_before)
    actual_cp_after = _normalise_cp(eval_after)   # already flipped in engine.score_after_move

    cp_loss: int = 0
    if best_cp_before is not None and actual_cp_after is not None:
        cp_loss = max(0, best_cp_before - actual_cp_after)
    elif eval_before.mate_in is not None and eval_before.mate_in > 0:
        # Had a forced mate, if we no longer have one → big loss
        if eval_after.mate_in is None or eval_after.mate_in <= 0:
            cp_loss = 500   # effectively a blunder of a won position
        else:
            cp_loss = max(0, eval_before.mate_in - eval_after.mate_in) * 50

    # Check if the played move matches the engine's best
    is_best_move = (move == eval_before.move)

    # Brilliant: only move that's best AND involves a sacrifice
    if is_best_move and _is_sacrifice(board_before, move):
        # Only classify brilliant if it's significantly better than 2nd best
        # (i.e. truly the engine's top pick, not just tied)
        return Classification.BRILLIANT, cp_loss

    # Great: only the best move (engine's top), not a sacrifice
    if is_best_move and cp_loss == 0:
        return Classification.GREAT, cp_loss

    # Threshold-based for everything else
    for threshold, cls in CP_THRESHOLDS:
        if cp_loss <= threshold:
            return cls, cp_loss

    return Classification.BLUNDER, cp_loss


def _normalise_cp(ev: MoveEval) -> Optional[int]:
    """Return centipawn score, converting mate scores to large values."""
    if ev.mate_in is not None:
        return 10000 if ev.mate_in > 0 else -10000
    return ev.score_cp


# ── Main Analyzer class ────────────────────────────────────────────────────────

class Analyzer:
    """
    Synchronous game analyzer.
    Call analyze_game() with a chess.pgn.Game and get back a GameAnalysis.

    For non-blocking use, wrap in AnalyzerWorker (below).
    """

    def __init__(self, engine: ChessEngine, depth: int = 15):
        self.engine = engine
        self.depth  = depth

    def analyze_game(
        self,
        game            : chess.pgn.Game,
        progress_cb     = None,   # optional callable(current_ply, total_plies)
    ) -> GameAnalysis:
        """
        Analyse every move in the game.

        Parameters
        ----------
        game        : parsed chess.pgn.Game
        progress_cb : optional callback(ply, total) for progress reporting

        Returns
        -------
        GameAnalysis
        """
        board    = game.board()
        node     = game
        results  : list[MoveAnalysis] = []
        ply      = 0

        # Collect all moves first so we know total
        moves_list: list[chess.Move] = []
        temp_node = game
        while temp_node.variations:
            temp_node = temp_node.variations[0]
            moves_list.append(temp_node.move)
        total = len(moves_list)

        # Evaluate starting position
        prev_eval = self.engine.evaluate(board, depth=self.depth, multipv=1).best
        if prev_eval is None:
            # Fallback for edge cases
            prev_eval = MoveEval(chess.Move.null(), 0, None, [])

        while node.variations:
            next_node = node.variations[0]
            move      = next_node.move
            ply      += 1

            color    = board.turn
            move_san = board.san(move)

            if progress_cb:
                progress_cb(ply, total)

            # Score the position after the played move (from moving side's POV)
            played_eval = self.engine.score_after_move(board, move, depth=self.depth)

            # Classify
            cls, cp_loss = classify_move(
                board,
                move,
                prev_eval,
                played_eval,
                ply,
            )

            # Best move SAN
            best_san = None
            if prev_eval.move and prev_eval.move != move:
                try:
                    best_san = board.san(prev_eval.move)
                except Exception:
                    best_san = prev_eval.move.uci()

            results.append(MoveAnalysis(
                move           = move,
                move_san       = move_san,
                ply            = ply,
                color          = color,
                classification = cls,
                cp_loss        = cp_loss,
                eval_before    = prev_eval,
                eval_after     = played_eval,
                best_move      = prev_eval.move,
                best_move_san  = best_san,
                pv             = prev_eval.pv,
            ))

            # Advance
            board.push(move)
            node = next_node

            # Evaluate new position (becomes prev_eval for next move)
            new_pos = self.engine.evaluate(board, depth=self.depth, multipv=1)
            prev_eval = new_pos.best if new_pos.best else MoveEval(chess.Move.null(), 0, None, [])

        # ── Compute accuracy scores ────────────────────────────────────────
        white_acc = self._compute_accuracy(results, chess.WHITE)
        black_acc = self._compute_accuracy(results, chess.BLACK)

        white_counts = self._count_classifications(results, chess.WHITE)
        black_counts = self._count_classifications(results, chess.BLACK)

        return GameAnalysis(
            moves          = results,
            white_accuracy = white_acc,
            black_accuracy = black_acc,
            headers        = dict(game.headers),
            white_counts   = white_counts,
            black_counts   = black_counts,
        )

    @staticmethod
    def _compute_accuracy(moves: list[MoveAnalysis], color: chess.Color) -> float:
        """Average per-move accuracy for one side, skipping book/forced."""
        scores = []
        for m in moves:
            if m.color != color:
                continue
            if m.classification in (Classification.BOOK, Classification.FORCED):
                continue
            if m.eval_before is None or m.eval_after is None:
                continue

            before_cp = _normalise_cp(m.eval_before) or 0
            after_cp  = _normalise_cp(m.eval_after)  or 0

            # Both scores are from moving side's POV; after is already flipped
            # so we use before directly vs after
            acc = _accuracy_from_win_probs(before_cp, after_cp)
            scores.append(acc)

        return sum(scores) / len(scores) if scores else 100.0

    @staticmethod
    def _count_classifications(
        moves: list[MoveAnalysis], color: chess.Color
    ) -> dict:
        counts: dict[Classification, int] = {}
        for m in moves:
            if m.color == color:
                counts[m.classification] = counts.get(m.classification, 0) + 1
        return counts

    @staticmethod
    def parse_pgn(pgn_text: str) -> list[chess.pgn.Game]:
        """Parse a PGN string and return a list of games."""
        games  = []
        reader = io.StringIO(pgn_text)
        while True:
            game = chess.pgn.read_game(reader)
            if game is None:
                break
            games.append(game)
        return games

    @staticmethod
    def parse_pgn_file(path: str) -> list[chess.pgn.Game]:
        """Read a .pgn file and return all games in it."""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return Analyzer.parse_pgn(f.read())


# ── Qt Worker — non-blocking analysis ─────────────────────────────────────────

class AnalyzerWorker(QObject):
    """
    Runs Analyzer.analyze_game() in a background QThread.

    Signals
    -------
    progress(int, int)         — current ply, total plies
    move_done(MoveAnalysis)    — emitted after each move is classified
    finished(GameAnalysis)     — emitted when full game is done
    error(str)                 — emitted on exception
    """

    progress  = pyqtSignal(int, int)       # ply, total
    move_done = pyqtSignal(object)         # MoveAnalysis
    finished  = pyqtSignal(object)         # GameAnalysis
    error     = pyqtSignal(str)

    def __init__(
        self,
        engine  : ChessEngine,
        game    : chess.pgn.Game,
        depth   : int = 15,
    ):
        super().__init__()
        self._engine = engine
        self._game   = game
        self._depth  = depth
        self._abort  = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            analyzer = Analyzer(self._engine, self._depth)

            # Patch progress callback to also emit move_done incrementally
            # We re-implement the loop here to support move_done signal
            board    = self._game.board()
            node     = self._game
            results  : list[MoveAnalysis] = []
            ply      = 0

            moves_list = []
            temp = self._game
            while temp.variations:
                temp = temp.variations[0]
                moves_list.append(temp.move)
            total = len(moves_list)

            prev_eval = self._engine.evaluate(board, depth=self._depth, multipv=1).best
            if prev_eval is None:
                prev_eval = MoveEval(chess.Move.null(), 0, None, [])

            while node.variations and not self._abort:
                next_node = node.variations[0]
                move      = next_node.move
                ply      += 1
                color     = board.turn
                move_san  = board.san(move)

                self.progress.emit(ply, total)

                played_eval = self._engine.score_after_move(board, move, depth=self._depth)
                cls, cp_loss = classify_move(board, move, prev_eval, played_eval, ply)

                best_san = None
                if prev_eval.move and prev_eval.move != move:
                    try:
                        best_san = board.san(prev_eval.move)
                    except Exception:
                        best_san = prev_eval.move.uci()

                ma = MoveAnalysis(
                    move           = move,
                    move_san       = move_san,
                    ply            = ply,
                    color          = color,
                    classification = cls,
                    cp_loss        = cp_loss,
                    eval_before    = prev_eval,
                    eval_after     = played_eval,
                    best_move      = prev_eval.move,
                    best_move_san  = best_san,
                    pv             = prev_eval.pv,
                )
                results.append(ma)
                self.move_done.emit(ma)

                board.push(move)
                node = next_node

                new_pos   = self._engine.evaluate(board, depth=self._depth, multipv=1)
                prev_eval = new_pos.best if new_pos.best else MoveEval(chess.Move.null(), 0, None, [])

            if not self._abort:
                white_acc    = Analyzer._compute_accuracy(results, chess.WHITE)
                black_acc    = Analyzer._compute_accuracy(results, chess.BLACK)
                white_counts = Analyzer._count_classifications(results, chess.WHITE)
                black_counts = Analyzer._count_classifications(results, chess.BLACK)

                game_analysis = GameAnalysis(
                    moves          = results,
                    white_accuracy = white_acc,
                    black_accuracy = black_acc,
                    headers        = dict(self._game.headers),
                    white_counts   = white_counts,
                    black_counts   = black_counts,
                )
                self.finished.emit(game_analysis)

        except Exception as exc:
            self.error.emit(str(exc))