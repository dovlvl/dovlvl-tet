"""Single-player score projection, separate from survival utility and attacks.

Published site table: https://play.tetris.com/games/
Unpublished combo/PC/mini bonuses are deliberately not imported from other games.
The three-corner/pointing-side spin model needs live-site confirmation.
"""
from dataclasses import dataclass,replace

@dataclass(frozen=True)
class ScoreState:
    level:int=1
    back_to_back:object=None  # Unknown if Auto was attached mid-game.
    combo:object=None
    lines:int=0

@dataclass(frozen=True)
class Rules:
    combo_per_step:object=None
    pc_bonus:object=None
    mini_scores:object=None
    spin_model_verified:bool=False
    source:str='https://play.tetris.com/games/'

SITE_RULES=Rules()

def tspin(board,kind,state,last_rotation=False,kick_index=0,drop_distance=0):
    if kind!='T' or not last_rotation or drop_distance:return 'none'
    x,y,r=state;cx,cy=x+1,y+1
    def occupied(a,b):return a<0 or a>=10 or b>=20 or (b>=0 and bool(board[b][a]))
    corners=[occupied(cx-1,cy-1),occupied(cx+1,cy-1),occupied(cx-1,cy+1),occupied(cx+1,cy+1)]
    if sum(corners)<3:return 'none'
    front=((0,1),(1,3),(2,3),(0,2))[r]
    return 'full' if all(corners[i] for i in front) or kick_index==4 else 'mini'

def award(lines,spin='none',perfect_clear=False,hard_distance=0,soft_distance=0,state=None,rules=SITE_RULES):
    state=state or ScoreState()
    perfect_clear=bool(perfect_clear and lines)
    regular=(0,100,300,500,800)[lines]
    if spin=='full':base=(400,800,1200,1600)[min(3,lines)]
    elif spin=='mini' and rules.mini_scores is not None:base=rules.mini_scores[min(lines,len(rules.mini_scores)-1)]
    else:base=regular
    difficult=bool(lines and (lines==4 or spin=='full' or (spin=='mini' and rules.mini_scores is not None)))
    b2b_bonus=base//2 if difficult and state.back_to_back is True else 0
    combo=state.combo+1 if lines and state.combo is not None else 0 if lines else -1
    combo_bonus=(rules.combo_per_step or 0)*max(0,combo) if lines else 0
    pc_bonus=(rules.pc_bonus or 0) if perfect_clear else 0
    lock_points=(base+b2b_bonus+combo_bonus+pc_bonus)*state.level
    # The current site states that its scores are level multiplied; keep the
    # drop component separate so different site revisions can be compared.
    drop_points=(2*max(0,hard_distance)+max(0,soft_distance))*state.level
    next_b2b=difficult if lines else state.back_to_back
    following=replace(state,back_to_back=next_b2b,combo=combo,lines=state.lines+lines)
    return dict(expected_points=lock_points+drop_points,lock_points=lock_points,drop_points=drop_points,
                back_to_back_bonus=b2b_bonus*state.level,combo_bonus=combo_bonus*state.level,
                perfect_clear=perfect_clear,perfect_clear_bonus=pc_bonus*state.level,spin=spin,
                score_state=following,points_basis='site table projection; level supplied, actual score not read',
                spin_judgment='model_only' if spin!='none' and not rules.spin_model_verified else 'not_required' if spin=='none' else 'verified_model',
                combo_bonus_verified=rules.combo_per_step is not None,pc_bonus_verified=rules.pc_bonus is not None)
