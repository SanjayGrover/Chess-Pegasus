"""
importer.py  —  Chess.com & Lichess Game Importer
===================================================
Fetches games from both platforms using their free public APIs.
No API keys or login required for either.

Chess.com API:
  GET https://api.chess.com/pub/player/{user}/games/{year}/{month}
  Returns JSON with a "games" array, each containing a "pgn" field.

Lichess API:
  GET https://lichess.org/api/games/user/{user}
  Returns a stream of PGN games (Accept: application/x-chess-pgn).
  Supports filters: max, perfType, color, rated, since/until.

Used by: import_tab (Part 6)
"""

import re
import requests
import chess.pgn
import io
from datetime  import datetime, timezone
from typing    import Optional
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal, QThread


# ── Shared request headers ─────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "ChessMasterPro/1.0 (local chess analysis app)"
}

REQUEST_TIMEOUT = 15   # seconds


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ImportedGame:
    """A single imported game with metadata."""
    pgn_text   : str
    source     : str                    # "chesscom" or "lichess"
    white      : str  = ""
    black      : str  = ""
    result     : str  = ""
    date       : str  = ""
    time_class : str  = ""              # bullet / blitz / rapid / classical
    opening    : str  = ""
    url        : str  = ""

    @property
    def display_title(self) -> str:
        result_sym = {"1-0": "1-0 ♔", "0-1": "0-1 ♚", "1/2-1/2": "½-½"}.get(
            self.result, self.result
        )
        tc = f"  [{self.time_class}]" if self.time_class else ""
        return f"{self.white} vs {self.black}  {result_sym}{tc}  {self.date}"

    @property
    def parsed_game(self) -> Optional[chess.pgn.Game]:
        try:
            return chess.pgn.read_game(io.StringIO(self.pgn_text))
        except Exception:
            return None


@dataclass
class ImportResult:
    """Result of a fetch operation."""
    games    : list[ImportedGame] = field(default_factory=list)
    errors   : list[str]         = field(default_factory=list)
    source   : str               = ""
    username : str               = ""

    @property
    def success(self) -> bool:
        return len(self.games) > 0

    @property
    def summary(self) -> str:
        n = len(self.games)
        e = f"  ({len(self.errors)} error(s))" if self.errors else ""
        return f"Imported {n} game{'s' if n != 1 else ''} from {self.source}{e}"


# ── Chess.com importer ─────────────────────────────────────────────────────────

class ChessComImporter:
    """
    Fetches games from the chess.com published-data API.

    chess.com organises games by month, so we fetch each requested month
    separately and merge.
    """

    BASE_URL = "https://api.chess.com/pub/player"

    def fetch_archives(self, username: str) -> list[str]:
        """
        Return a list of monthly archive URLs for the user,
        sorted newest-first.
        """
        url  = f"{self.BASE_URL}/{username.lower()}/games/archives"
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        archives = resp.json().get("archives", [])
        return list(reversed(archives))   # newest first

    def fetch_month(self, username: str, year: int, month: int) -> list[ImportedGame]:
        """Fetch all games for a given year/month."""
        url  = f"{self.BASE_URL}/{username.lower()}/games/{year}/{month:02d}"
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw_games = resp.json().get("games", [])
        return [self._parse_game(g) for g in raw_games if g.get("pgn")]

    def fetch_recent(
        self,
        username   : str,
        max_games  : int = 20,
        time_class : Optional[str] = None,   # "bullet","blitz","rapid","daily"
    ) -> ImportResult:
        """
        Fetch the most recent `max_games` games for `username`.
        Walks backwards through monthly archives until enough are collected.
        """
        result = ImportResult(source="chess.com", username=username)
        try:
            archives = self.fetch_archives(username)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                result.errors.append(f"User '{username}' not found on chess.com.")
            else:
                result.errors.append(f"chess.com API error: {e}")
            return result
        except Exception as e:
            result.errors.append(f"Network error: {e}")
            return result

        for archive_url in archives:
            if len(result.games) >= max_games:
                break
            try:
                # Extract year/month from URL like .../games/2024/03
                parts = archive_url.rstrip("/").split("/")
                year, month = int(parts[-2]), int(parts[-1])
                games = self.fetch_month(username, year, month)
                # Newest games are last in the month list
                games = list(reversed(games))
                for g in games:
                    if len(result.games) >= max_games:
                        break
                    if time_class and g.time_class.lower() != time_class.lower():
                        continue
                    result.games.append(g)
            except Exception as e:
                result.errors.append(f"Error fetching {archive_url}: {e}")

        return result

    @staticmethod
    def _parse_game(raw: dict) -> ImportedGame:
        """Convert a chess.com JSON game object to ImportedGame."""
        pgn_text   = raw.get("pgn", "")
        time_class = raw.get("time_class", "")
        url        = raw.get("url", "")

        # Parse PGN headers for metadata
        white  = raw.get("white", {}).get("username", "?")
        black  = raw.get("black", {}).get("username", "?")
        result_w = raw.get("white", {}).get("result", "")
        result_b = raw.get("black", {}).get("result", "")

        if result_w == "win":
            result = "1-0"
        elif result_b == "win":
            result = "0-1"
        else:
            result = "1/2-1/2"

        # Extract date from PGN headers (more reliable)
        date    = _extract_pgn_header(pgn_text, "Date") or ""
        opening = _extract_pgn_header(pgn_text, "Opening") or \
                  _extract_pgn_header(pgn_text, "ECOUrl") or ""

        # Shorten ECO URL to just the opening name
        if "/" in opening:
            opening = opening.rstrip("/").split("/")[-1].replace("-", " ").title()

        return ImportedGame(
            pgn_text   = pgn_text,
            source     = "chesscom",
            white      = white,
            black      = black,
            result     = result,
            date       = date,
            time_class = time_class,
            opening    = opening,
            url        = url,
        )


# ── Lichess importer ───────────────────────────────────────────────────────────

class LichessImporter:
    """
    Fetches games from the Lichess public API.

    Lichess streams PGN directly, which is very fast.
    Supports filtering by time control, color, and rated status.
    """

    BASE_URL = "https://lichess.org/api/games/user"

    def fetch_recent(
        self,
        username   : str,
        max_games  : int = 20,
        perf_type  : Optional[str] = None,    # "bullet","blitz","rapid","classical","correspondence"
        rated_only : bool = False,
        as_color   : Optional[str] = None,    # "white" or "black"
    ) -> ImportResult:
        """
        Fetch the most recent `max_games` games for `username` from Lichess.
        """
        result = ImportResult(source="lichess", username=username)

        params: dict = {
            "max"    : max_games,
            "clocks" : "false",
            "evals"  : "false",
            "opening": "true",
        }
        if perf_type:
            params["perfType"] = perf_type
        if rated_only:
            params["rated"] = "true"
        if as_color in ("white", "black"):
            params["color"] = as_color

        url = f"{self.BASE_URL}/{username.lower()}"

        try:
            resp = requests.get(
                url,
                params  = params,
                headers = {**HEADERS, "Accept": "application/x-chess-pgn"},
                timeout = REQUEST_TIMEOUT,
                stream  = True,
            )
            if resp.status_code == 404:
                result.errors.append(f"User '{username}' not found on Lichess.")
                return result
            resp.raise_for_status()

            # The response is a stream of PGN games separated by blank lines
            pgn_text = resp.text
            result.games = self._parse_pgn_stream(pgn_text)

        except requests.HTTPError as e:
            result.errors.append(f"Lichess API error: {e}")
        except Exception as e:
            result.errors.append(f"Network error: {e}")

        return result

    @staticmethod
    def _parse_pgn_stream(pgn_text: str) -> list[ImportedGame]:
        """Split a multi-game PGN stream into individual ImportedGame objects."""
        games  = []
        reader = io.StringIO(pgn_text)

        while True:
            try:
                game = chess.pgn.read_game(reader)
                if game is None:
                    break

                h          = game.headers
                white      = h.get("White", "?")
                black      = h.get("Black", "?")
                result     = h.get("Result", "?")
                date       = h.get("UTCDate", h.get("Date", ""))
                opening    = h.get("Opening", "")
                url        = h.get("Site", "")
                time_ctrl  = h.get("TimeControl", "")
                time_class = _lichess_time_class(time_ctrl)

                # Re-export to PGN string
                exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
                pgn_out  = game.accept(exporter)

                games.append(ImportedGame(
                    pgn_text   = pgn_out,
                    source     = "lichess",
                    white      = white,
                    black      = black,
                    result     = result,
                    date       = date,
                    time_class = time_class,
                    opening    = opening,
                    url        = url,
                ))
            except Exception:
                break   # malformed game — skip

        return games


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_pgn_header(pgn_text: str, header: str) -> Optional[str]:
    """Quick regex extract of a PGN header value without full parsing."""
    m = re.search(rf'\[{header}\s+"([^"]+)"\]', pgn_text)
    return m.group(1) if m else None


def _lichess_time_class(time_control: str) -> str:
    """
    Convert a Lichess time control string like '300+3' to a time class name.
    Uses FIDE classification: bullet<3min, blitz 3-10min, rapid 10-60min.
    """
    if not time_control or time_control == "-":
        return "correspondence"
    try:
        if "+" in time_control:
            base, inc = time_control.split("+")
            total_seconds = int(base) + int(inc) * 40   # estimate for 40 moves
        else:
            total_seconds = int(time_control)

        minutes = total_seconds / 60
        if minutes < 3:
            return "bullet"
        elif minutes < 10:
            return "blitz"
        elif minutes < 60:
            return "rapid"
        else:
            return "classical"
    except Exception:
        return "unknown"


# ── Qt Workers ─────────────────────────────────────────────────────────────────

class ImportWorker(QObject):
    """
    Runs a fetch operation in a background QThread so the GUI stays responsive.

    Signals
    -------
    finished(ImportResult)  — emitted when fetch completes (success or partial)
    error(str)              — emitted on unrecoverable exception
    progress(str)           — status messages during fetch
    """

    finished = pyqtSignal(object)   # ImportResult
    error    = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        source     : str,             # "chesscom" or "lichess"
        username   : str,
        max_games  : int  = 20,
        time_class : Optional[str] = None,
        rated_only : bool = False,
        as_color   : Optional[str] = None,
    ):
        super().__init__()
        self._source     = source
        self._username   = username
        self._max_games  = max_games
        self._time_class = time_class
        self._rated_only = rated_only
        self._as_color   = as_color

    def run(self):
        try:
            if self._source == "chesscom":
                self.progress.emit(f"Connecting to chess.com…")
                importer = ChessComImporter()
                result   = importer.fetch_recent(
                    self._username,
                    max_games  = self._max_games,
                    time_class = self._time_class,
                )
            else:
                self.progress.emit(f"Connecting to Lichess…")
                importer = LichessImporter()
                result   = importer.fetch_recent(
                    self._username,
                    max_games  = self._max_games,
                    perf_type  = self._time_class,
                    rated_only = self._rated_only,
                    as_color   = self._as_color,
                )

            self.progress.emit(result.summary)
            self.finished.emit(result)

        except Exception as exc:
            self.error.emit(str(exc))