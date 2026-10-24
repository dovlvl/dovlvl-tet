from dataclasses import dataclass,field
from typing import Optional
@dataclass(frozen=True)
class Reading:
    kind:Optional[str] # None means empty ONLY when valid is True
    confidence:float
    updated:float
    valid:bool=True
    reason:str=''
    seen:float=0
    state:str='unknown'
    available:Optional[bool]=None
@dataclass(frozen=True)
class Active:
    kind:str
    state:tuple
    cells:frozenset
    confidence:float
    updated:float
@dataclass
class Observation:
    seq:int
    captured:float
    updated:float
    fixed:list
    active:Optional[Active]
    ghost:list
    hold:Reading
    nexts:list
    confidence:float
    stable:int
    reason:str=''
    capture_ms:float=0
    vision_ms:float=0
    fps:float=0
    raw:list=field(default_factory=list)
    fixed_updated:float=0
    fixed_confidence:float=0
    ghost_confidence:float=0
    ghost_updated:float=0
    @property
    def board_key(self):return tuple(tuple(r) for r in self.fixed)
    @property
    def queue(self):return tuple(r.kind if r.valid else '?' for r in self.nexts)
    @property
    def valid(self):return self.active is not None and self.confidence>=.8 and self.stable>=2
