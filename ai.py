"""Inteligencia artificial: Minimax con poda alfa-beta y ordenación de jugadas.

Las puntuaciones son centipeones (+ favorece blancas, - favorece negras).
No usa modelos generativos, APIs ni motores externos como Stockfish.
"""
from dataclasses import dataclass
from time import monotonic
from chess_core import Position, Move, legal_moves, make_move, in_check, insufficient_material, color, on_board

VALUES = {'p':100, 'n':320, 'b':330, 'r':500, 'q':900, 'k':0}
MATE = 100_000
MAX_DEPTH = 4


class SearchTimeout(Exception):
    pass


@dataclass
class Metrics:
    nodes: int = 0
    cutoffs: int = 0
    elapsed_ms: int = 0
    depth: int = 0
    score_cp: int = 0
    best_uci: str = ''
    principal_variation: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            'nodes':self.nodes, 'cutoffs':self.cutoffs, 'elapsed_ms':self.elapsed_ms,
            'depth':self.depth, 'score_cp':self.score_cp,
            'best_uci':self.best_uci, 'principal_variation':self.principal_variation or []
        }


def evaluate(s: Position) -> int:
    """Heurística de material, desarrollo, peones y control del centro."""
    score = 0
    pawn_files = {1: [0]*8, -1:[0]*8}
    for i, p in enumerate(s.board):
        if not on_board(i) or p == '.': continue
        side = color(p)
        kind = p.lower()
        row, col = i >> 4, i & 7
        center = int(6 - (abs(row-3.5)+abs(col-3.5)))
        bonus = 0
        if kind == 'p':
            pawn_files[side][col] += 1
            advance = (6-row if side == 1 else row-1)
            bonus = advance*7 + int(center*2.0)
            if col in (3,4): bonus += 7
        elif kind in ('n','b'):
            bonus = center * (8 if kind=='n' else 5)
        elif kind == 'q':
            bonus = center*2
        elif kind == 'k':
            # Rey resguardado durante la apertura; no lo atraemos al centro temprano.
            enemy_majors = sum(VALUES[x.lower()] for x in s.board if x!='.' and color(x)==-side and x.lower() in ('r','q'))
            bonus = (-center*9 if enemy_majors else center*8)
        score += side*(VALUES[kind]+bonus)
    for side, files in pawn_files.items():
        # Peones doblados e aislados (evaluación sencilla de estructura).
        for file_index, count in enumerate(files):
            if count > 1: score -= side * (count-1)*13
            if count and not ((file_index>0 and files[file_index-1]) or (file_index<7 and files[file_index+1])):
                score -= side * 9*count
    return score


def ordering_score(s: Position, m: Move) -> int:
    attacker = VALUES[s.board[m.src].lower()]
    target = s.board[m.dst]
    capture = VALUES[target.lower()] if target != '.' else (100 if m.flag == 'ep' else 0)
    row, col = m.dst >> 4, m.dst & 7
    center = 7 - int(abs(row-3.5)+abs(col-3.5))
    return (10_000 + 12*capture - attacker if capture else 0) + (VALUES.get(m.promotion,0)+5000 if m.promotion else 0) + center


class AlphaBeta:
    def __init__(self, deadline: float):
        self.deadline = deadline
        self.nodes = 0
        self.cutoffs = 0

    def tick(self):
        self.nodes += 1
        if self.nodes % 512 == 0 and monotonic() >= self.deadline:
            raise SearchTimeout()

    def minimax(self, s: Position, depth: int, alpha: int, beta: int, ply: int = 0) -> int:
        self.tick()
        if s.halfmove >= 100 or insufficient_material(s):
            return 0
        if depth == 0:
            # Analizar mates aunque ocurran en el horizonte.
            if in_check(s) and not legal_moves(s):
                return -MATE + ply if s.turn == 1 else MATE - ply
            return evaluate(s)
        moves = legal_moves(s)
        if not moves:
            if in_check(s):
                return -MATE + ply if s.turn == 1 else MATE - ply
            return 0
        moves.sort(key=lambda m: ordering_score(s,m), reverse=True)
        if s.turn == 1:  # Las blancas MAXIMIZAN.
            score = -MATE * 2
            for move in moves:
                score = max(score, self.minimax(make_move(s,move),depth-1,alpha,beta,ply+1))
                alpha = max(alpha,score)
                if alpha >= beta:
                    self.cutoffs += 1
                    break
            return score
        else:  # Las negras MINIMIZAN.
            score = MATE * 2
            for move in moves:
                score = min(score, self.minimax(make_move(s,move),depth-1,alpha,beta,ply+1))
                beta = min(beta,score)
                if beta <= alpha:
                    self.cutoffs += 1
                    break
            return score

    def root(self, s: Position, depth: int) -> tuple[Move,int]:
        moves = legal_moves(s)
        if not moves:
            raise ValueError('No hay movimientos legales')
        moves.sort(key=lambda m: ordering_score(s,m),reverse=True)
        alpha, beta = -MATE*2, MATE*2
        best = moves[0]
        best_score = -MATE*2 if s.turn == 1 else MATE*2
        for move in moves:
            if monotonic() >= self.deadline:
                raise SearchTimeout()
            score = self.minimax(make_move(s,move),depth-1,alpha,beta,1)
            if (s.turn == 1 and score > best_score) or (s.turn == -1 and score < best_score):
                best_score, best = score, move
            if s.turn == 1: alpha = max(alpha,best_score)
            else: beta = min(beta,best_score)
        return best, best_score


def choose_move(s: Position, requested_depth: int = 2, time_limit: float | None = None) -> tuple[Move | None, Metrics]:
    """Búsqueda iterativa con presupuesto de tiempo y respuesta siempre legal."""
    depth = max(1,min(MAX_DEPTH,int(requested_depth)))
    budget = time_limit if time_limit is not None else {1:0.5,2:1.1,3:2.5,4:5.5}[depth]
    started = monotonic()
    options = legal_moves(s)
    if not options:
        return None, Metrics()
    best = max(options,key=lambda m:ordering_score(s,m))
    best_score = evaluate(make_move(s,best))
    searcher = AlphaBeta(started+budget)
    actual_depth = 0
    for current_depth in range(1,depth+1):
        try:
            candidate,score = searcher.root(s,current_depth)
        except SearchTimeout:
            break
        best,best_score = candidate,score
        actual_depth = current_depth
    metrics = Metrics(nodes=searcher.nodes,cutoffs=searcher.cutoffs,
                      elapsed_ms=round((monotonic()-started)*1000),depth=actual_depth,
                      score_cp=best_score,best_uci=best.uci,principal_variation=[best.uci])
    return best,metrics
