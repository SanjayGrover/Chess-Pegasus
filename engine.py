"""
engine.py  —  Stockfish Engine Wrapper
========================================
A clean, thread-safe wrapper around python-chess's Stockfish integration.

Features:
  • Configurable search depth per call
  • Best move retrieval
  • Position evaluation in centipawns (normalised to White's POV)
  • Top-N multipv analysis (multiple candidate moves + their scores)
  • Runs analysis in a QThread so the GUI never freezes
  • Emits Qt signals on completion

Used by:  play_tab (Part 4),  analyzer.py (Part 5)
"""

import chess
import chess.engine
from typing   import Optional

from PyQt6.QtCore import QThread, pyqtSignal, QObject


# ── Data classes ───────────────────────────────────────────────────────────────

class MoveEval:
    """Evaluation result for a single candidate move."""

    def __init__(
        self,
        move       : chess.Move,
        score_cp   : Optional[int],   # centipawns from White's POV; None if mate
        mate_in    : Optional[int],   # mate in N (positive = winning, negative = losing)
        pv         : list[chess.Move] # principal variation
    ):
        self.move     = move
        self.score_cp = score_cp
        self.mate_in  = mate_in
        self.pv       = pv

    @property
    def is_mate(self) -> bool:
        return self.mate_in is not None

    def score_display(self) -> str:
        """Human-readable score string, e.g. '+1.23' or 'M4'."""
        if self.mate_in is not None:
            sign = "+" if self.mate_in > 0 else "-"
            return f"{sign}M{abs(self.mate_in)}"
        if self.score_cp is not None:
            pawns = self.score_cp / 100.0
            sign  = "+" if pawns >= 0 else ""
            return f"{sign}{pawns:.2f}"
        return "?"

    def __repr__(self):
        return f"<MoveEval {self.move.uci()} {self.score_display()}>"


class PositionEval:
    """Full evaluation of a position: top candidates + best move."""

    def __init__(self, candidates: list[MoveEval]):
        self.candidates = candidates   # ordered best-first

    @property
    def best(self) -> Optional[MoveEval]:
        return self.candidates[0] if self.candidates else None

    @property
    def best_move(self) -> Optional[chess.Move]:
        return self.best.move if self.best else None

    @property
    def best_score_cp(self) -> Optional[int]:
        return self.best.score_cp if self.best else None

    @property
    def best_mate_in(self) -> Optional[int]:
        return self.best.mate_in if self.best else None


# ── Engine wrapper (synchronous) ───────────────────────────────────────────────

class ChessEngine:
    """
    Thin synchronous wrapper around chess.engine.SimpleEngine (Stockfish).

    Usage
    -----
        engine = ChessEngine(r"C:\\stockfish\\stockfish.exe")
        engine.open()
        eval_  = engine.evaluate(board, depth=15, multipv=3)
        print(eval_.best_move, eval_.best.score_display())
        engine.close()

    Always call open() before use and close() when done.
    Use EngineWorker (below) for non-blocking GUI calls.
    """

    def __init__(self, stockfish_path: str):
        self.path    : str                          = stockfish_path
        self._engine : Optional[chess.engine.SimpleEngine] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def open(self):
        """Start the Stockfish process."""
        if self._engine is not None:
            return
        self._engine = chess.engine.SimpleEngine.popen_uci(self.path)

    def close(self):
        """Terminate the Stockfish process."""
        if self._engine:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None

    def is_open(self) -> bool:
        return self._engine is not None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    # ── Core analysis ──────────────────────────────────────────────────────────

    def evaluate(
        self,
        board   : chess.Board,
        depth   : int = 15,
        multipv : int = 1,
    ) -> PositionEval:
        """
        Analyse a position and return the top `multipv` candidate moves.

        Parameters
        ----------
        board   : position to evaluate
        depth   : search depth in plies (1-30)
        multipv : number of candidate lines to return

        Returns
        -------
        PositionEval  with `.candidates` sorted best-first (White's POV)
        """
        if self._engine is None:
            raise RuntimeError("Engine not open. Call open() first.")

        if board.is_game_over():
            return PositionEval([])

        limit      = chess.engine.Limit(depth=depth)
        multipv    = max(1, min(multipv, len(list(board.legal_moves))))
        info_list  = self._engine.analyse(board, limit, multipv=multipv)

        candidates: list[MoveEval] = []
        for info in info_list:
            move = info.get("pv", [None])[0]
            if move is None:
                continue

            score  = info.get("score")
            pv     = info.get("pv", [])

            # Normalise score to White's absolute POV
            cp_score : Optional[int] = None
            mate     : Optional[int] = None

            if score is not None:
                white_score = score.white()
                if white_score.is_mate():
                    mate = white_score.mate()
                else:
                    cp_score = white_score.score()

            candidates.append(MoveEval(move, cp_score, mate, pv))

        # Sort best-first from White's perspective
        def sort_key(e: MoveEval):
            if e.mate_in is not None:
                # Mate wins > any cp score; closer mate = better
                return (1, -e.mate_in if e.mate_in > 0 else e.mate_in)
            return (0, e.score_cp if e.score_cp is not None else -99999)

        candidates.sort(key=sort_key, reverse=True)
        return PositionEval(candidates)

    def best_move(self, board: chess.Board, depth: int = 15) -> Optional[chess.Move]:
        """Convenience: return only the single best move."""
        result = self.evaluate(board, depth=depth, multipv=1)
        return result.best_move

    def score_after_move(
        self,
        board : chess.Board,
        move  : chess.Move,
        depth : int = 15,
    ) -> MoveEval:
        """
        Push `move` on a copy of `board`, evaluate the resulting position,
        and return a MoveEval from the *moving side's* perspective.

        Used by the analyzer to score each played move.
        """
        b2 = board.copy()
        b2.push(move)
        pos = self.evaluate(b2, depth=depth, multipv=1)

        if pos.best is None:
            # Game over after the move
            outcome = b2.outcome()
            if outcome is not None and outcome.winner == board.turn:
                return MoveEval(move, None, 1, [])    # checkmate delivered
            return MoveEval(move, 0, None, [])

        best = pos.best
        # Flip sign: the engine score is from the side that just moved TO
        # We want it from the side that MADE the move (board.turn before push)
        if best.mate_in is not None:
            flipped_mate = -best.mate_in
            return MoveEval(move, None, flipped_mate, best.pv)
        else:
            flipped_cp = -(best.score_cp or 0)
            return MoveEval(move, flipped_cp, None, best.pv)


# ── Qt Worker — non-blocking engine calls ──────────────────────────────────────

class EngineWorker(QObject):
    """
    Runs engine.evaluate() in a background QThread so the GUI stays responsive.

    Usage
    -----
        self._thread = QThread()
        self._worker = EngineWorker(engine, board, depth=15, multipv=3)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_eval_done)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    Signals
    -------
    finished(PositionEval)   — emitted when analysis is complete
    error(str)               — emitted if Stockfish raises an exception
    """

    finished = pyqtSignal(object)   # PositionEval
    error    = pyqtSignal(str)

    def __init__(
        self,
        engine  : ChessEngine,
        board   : chess.Board,
        depth   : int = 15,
        multipv : int = 1,
        tag     : object = None,   # optional caller-defined tag (e.g. move index)
    ):
        super().__init__()
        self._engine  = engine
        self._board   = board.copy()
        self._depth   = depth
        self._multipv = multipv
        self.tag      = tag

    def run(self):
        try:
            result = self._engine.evaluate(self._board, self._depth, self._multipv)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class BestMoveWorker(QObject):
    """
    Lighter worker that just fetches the single best move.
    Used by the Play tab when it's the engine's turn.

    Signals
    -------
    finished(chess.Move)
    error(str)
    """

    finished = pyqtSignal(object)   # chess.Move
    error    = pyqtSignal(str)

    def __init__(self, engine: ChessEngine, board: chess.Board, depth: int = 15):
        super().__init__()
        self._engine = engine
        self._board  = board.copy()
        self._depth  = depth

    def run(self):
        try:
            move = self._engine.best_move(self._board, self._depth)
            if move:
                self.finished.emit(move)
            else:
                self.error.emit("Engine returned no move (game over?)")
        except Exception as exc:
            self.error.emit(str(exc))