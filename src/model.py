from dataclasses import dataclass, field
from typing import Optional
from enum import StrEnum


class ReasonCode(StrEnum):
    OCCLUDED = "OCCLUDED"
    OTHER = "OTHER"


def reason_code(reason):
    """Convert legacy reasons without changing their display or serialization."""
    if "팝업" in reason or "가림" in reason:
        return ReasonCode.OCCLUDED
    return ReasonCode.OTHER


@dataclass(frozen=True)
class Reading:
    kind: Optional[str]  # None means empty ONLY when valid is True
    confidence: float
    updated: float
    valid: bool = True
    reason: str = ""
    seen: float = 0
    state: str = "unknown"
    available: Optional[bool] = None


@dataclass(frozen=True)
class Active:
    kind: str
    state: tuple
    cells: frozenset
    confidence: float
    updated: float
    rotation_candidates: tuple = ()


@dataclass
class Observation:
    seq: int
    captured: float
    updated: float
    fixed: list
    active: Optional[Active]
    ghost: list
    hold: Reading
    nexts: list
    confidence: float
    stable: int
    reason: str = ""
    capture_ms: float = 0
    vision_ms: float = 0
    fps: float = 0
    raw: list = field(default_factory=list)
    fixed_updated: float = 0
    fixed_confidence: float = 0
    ghost_confidence: float = 0
    ghost_updated: float = 0
    prediction_match: Optional[bool] = None
    hold_stable: int = 0
    next_stable: int = 0
    generation: int = 0
    transition: str = "initial"
    generation_first_seen: float = 0
    gravity_cps: float = 0
    motion_samples: int = 0
    frame_interval_ms: float = 17
    fall_cells: int = 0
    fall_ms: Optional[float] = None
    motion_tracked: bool = False
    grounded_ms: float = 0
    grounded_known: bool = False

    @property
    def board_key(self):
        return tuple(tuple(r) for r in self.fixed)

    @property
    def queue(self):
        return tuple(r.kind if r.valid else "?" for r in self.nexts)

    @property
    def valid(self):
        return self.active is not None and self.confidence >= 0.8 and self.stable >= 2


class Phase(StrEnum):
    DECIDE = "DECIDE"
    DIAGNOSTIC = "DIAGNOSTIC"
    ERROR = "ERROR"
    IDLE = "IDLE"
    SEARCH = "SEARCH"
    STOPPED = "STOPPED"
    VISION_WAIT = "VISION_WAIT"
    WAIT_ACK = "WAIT_ACK"
    WAIT_DROP = "WAIT_DROP"
    WAIT_HOLD = "WAIT_HOLD"
    WAIT_VALID = "WAIT_VALID"


@dataclass
class PendingAction:
    action: str
    sent: float
    seq: int
    before: Observation
    hits: int = 0
    seen: bool = False
    expected_board: Optional[tuple] = None
    expected: Optional[tuple] = None
    score_spin: str = "none"
    hard_distance: int = 0
    mismatch_hits: int = 0
    mismatch_board: Optional[tuple] = None
    resync_checked: bool = False
    resynchronized: bool = False
    mismatch_logged: bool = False


@dataclass(init=False, repr=False, eq=False)
class Placement(dict):
    """Named placement fields with the existing sparse mapping/JSON contract.

    Optional scoring and opener metadata retain their original key presence.
    Keep dict construction, copies, equality and serialization during migration.
    """

    kind: str
    x: int
    y: int
    r: int
    cells: list
    board: list
    lines: int
    path: tuple
    score: float

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self[name] = value
