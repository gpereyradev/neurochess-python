"""Motor de reglas de ajedrez puro Python (0x88, sin dependencias).

Este archivo NO implementa la IA: aquí viven las reglas, jugadas legales,
notación SAN, jaque, enroque, captura al paso, promoción y finales.
"""
from dataclasses import dataclass
from typing import Optional

START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
FILES = 'abcdefgh'
KNIGHT = (-33, -31, -18, -14, 14, 18, 31, 33)
BISHOP = (-17, -15, 15, 17)
ROOK = (-16, -1, 1, 16)
KING = (-17, -16, -15, -1, 1, 15, 16, 17)
ALL_DIRS = {'n': KNIGHT, 'b': BISHOP, 'r': ROOK, 'q': BISHOP + ROOK, 'k': KING}


def on_board(i: int) -> bool:
    return 0 <= i < 128 and not (i & 0x88)


def square_name(i: int) -> str:
    return FILES[i & 7] + str(8 - (i >> 4))


def parse_square(s: str) -> int:
    if not isinstance(s, str) or len(s) != 2 or s[0] not in FILES or s[1] not in '12345678':
        raise ValueError('Casilla inválida')
    return (8 - int(s[1])) * 16 + FILES.index(s[0])


def color(piece: str) -> int:
    if piece == '.':
        return 0
    return 1 if piece.isupper() else -1


@dataclass(frozen=True)
class Move:
    src: int
    dst: int
    promotion: str = ''
    flag: str = ''

    @property
    def uci(self) -> str:
        return square_name(self.src) + square_name(self.dst) + self.promotion


@dataclass(frozen=True)
class Position:
    board: tuple[str, ...]
    turn: int
    castle: int  # 1 K, 2 Q, 4 k, 8 q
    ep: int = -1
    halfmove: int = 0
    fullmove: int = 1

    def fen(self) -> str:
        rows = []
        for r in range(8):
            row, empty = '', 0
            for c in range(8):
                p = self.board[r*16+c]
                if p == '.':
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p
            if empty:
                row += str(empty)
            rows.append(row)
        castle = ''.join(letter for bit,letter in ((1,'K'),(2,'Q'),(4,'k'),(8,'q')) if self.castle & bit) or '-'
        return f"{'/'.join(rows)} {'w' if self.turn == 1 else 'b'} {castle} {square_name(self.ep) if self.ep >= 0 else '-'} {self.halfmove} {self.fullmove}"


def from_fen(fen: str = START_FEN) -> Position:
    parts = fen.split()
    if len(parts) != 6:
        raise ValueError('FEN debe contener 6 campos')
    board = ['.'] * 128
    ranks = parts[0].split('/')
    if len(ranks) != 8:
        raise ValueError('FEN debe contener 8 filas')
    for rank, row in enumerate(ranks):
        file = 0
        for p in row:
            if p in '12345678':
                file += int(p)
            elif p in 'PRNBQKprnbqk' and file < 8:
                board[rank*16+file] = p
                file += 1
            else:
                raise ValueError('Pieza inválida en FEN')
        if file != 8:
            raise ValueError('Fila FEN inválida')
    if board.count('K') != 1 or board.count('k') != 1:
        raise ValueError('FEN requiere un rey de cada color')
    if parts[1] not in ('w','b'):
        raise ValueError('Turno FEN inválido')
    rights = 0
    if parts[2] != '-':
        if len(set(parts[2])) != len(parts[2]) or any(c not in 'KQkq' for c in parts[2]):
            raise ValueError('Enroque FEN inválido')
        for ch, bit in (('K',1),('Q',2),('k',4),('q',8)):
            if ch in parts[2]: rights |= bit
    ep = -1 if parts[3] == '-' else parse_square(parts[3])
    if ep >= 0 and square_name(ep)[1] not in '36':
        raise ValueError('En passant FEN inválido')
    half, full = int(parts[4]), int(parts[5])
    if half < 0 or full < 1:
        raise ValueError('Contadores FEN inválidos')
    return Position(tuple(board), 1 if parts[1]=='w' else -1, rights, ep, half, full)


def attacked(s: Position, dest: int, by: int) -> bool:
    b = s.board
    for f in range(128):
        if not on_board(f) or color(b[f]) != by:
            continue
        kind = b[f].lower()
        if kind == 'p':
            if dest == f - 16*by - 1 or dest == f - 16*by + 1:
                return True
            continue
        for d in ALL_DIRS[kind]:
            t = f+d
            while on_board(t):
                if t == dest:
                    return True
                if b[t] != '.' or kind in ('k','n'):
                    break
                t += d
    return False


def in_check(s: Position, who: Optional[int] = None) -> bool:
    who = s.turn if who is None else who
    king = 'K' if who == 1 else 'k'
    return attacked(s, s.board.index(king), -who)


def make_move(s: Position, m: Move) -> Position:
    b = list(s.board)
    piece, captured = b[m.src], b[m.dst]
    b[m.src] = '.'
    b[m.dst] = m.promotion.upper() if m.promotion and s.turn == 1 else (m.promotion if m.promotion else piece)
    if m.flag == 'ep':
        b[m.dst + 16*s.turn] = '.'
    if m.flag == 'castle':
        rook_from = m.src+3 if m.dst > m.src else m.src-4
        rook_to = m.src+1 if m.dst > m.src else m.src-1
        b[rook_to], b[rook_from] = b[rook_from], '.'
    rights = s.castle
    if piece == 'K': rights &= ~3
    if piece == 'k': rights &= ~12
    rook_rights = {119:1,112:2,7:4,0:8}
    if piece.lower() == 'r': rights &= ~rook_rights.get(m.src,0)
    if captured.lower() == 'r': rights &= ~rook_rights.get(m.dst,0)
    ep = (m.src+m.dst)//2 if piece.lower() == 'p' and abs(m.dst-m.src) == 32 else -1
    half = 0 if piece.lower() == 'p' or captured != '.' or m.flag == 'ep' else s.halfmove+1
    return Position(tuple(b), -s.turn, rights, ep, half, s.fullmove + (s.turn == -1))


def pseudo_moves(s: Position) -> list[Move]:
    b, turn = s.board, s.turn
    moves = []
    for f in range(128):
        if not on_board(f) or color(b[f]) != turn: continue
        piece = b[f].lower()
        def add(dst: int, flag: str = ''):
            if b[dst].lower() == 'k': return  # Un rey no se captura; se da mate.
            if piece == 'p' and dst >> 4 in (0,7):
                for promotion in ('q','r','b','n'):
                    moves.append(Move(f,dst,promotion,flag))
            else:
                moves.append(Move(f,dst,'',flag))
        if piece == 'p':
            one = f - 16*turn
            if on_board(one) and b[one] == '.':
                add(one)
                two = one - 16*turn
                if f >> 4 == (6 if turn == 1 else 1) and b[two] == '.':
                    add(two)
            for d in (-1,1):
                t = one+d
                if not on_board(t): continue
                if color(b[t]) == -turn:
                    add(t)
                elif t == s.ep and b[t] == '.' and b[t + 16*turn] == ('p' if turn == 1 else 'P'):
                    add(t,'ep')
        else:
            for d in ALL_DIRS[piece]:
                t = f+d
                while on_board(t):
                    if color(b[t]) == turn: break
                    add(t)
                    if b[t] != '.' or piece in ('k','n'): break
                    t += d
            if piece == 'k':
                home = 116 if turn == 1 else 4
                rook = 'R' if turn == 1 else 'r'
                kingside_bit, queenside_bit = ((1,2) if turn == 1 else (4,8))
                if f == home and not in_check(s):
                    if (s.castle & kingside_bit and b[f+3] == rook and b[f+1] == b[f+2] == '.'
                            and not attacked(s,f+1,-turn) and not attacked(s,f+2,-turn)):
                        add(f+2, 'castle')
                    if (s.castle & queenside_bit and b[f-4] == rook and b[f-1] == b[f-2] == b[f-3] == '.'
                            and not attacked(s,f-1,-turn) and not attacked(s,f-2,-turn)):
                        add(f-2, 'castle')
    return moves


def legal_moves(s: Position) -> list[Move]:
    return [m for m in pseudo_moves(s) if not in_check(make_move(s,m),s.turn)]


def find_move(s: Position, uci: str) -> Move:
    for m in legal_moves(s):
        if m.uci == uci:
            return m
    raise ValueError('Movimiento ilegal: ' + str(uci))


def to_san(s: Position, move: Move) -> str:
    p = s.board[move.src].upper()
    capture = s.board[move.dst] != '.' or move.flag == 'ep'
    if move.flag == 'castle':
        name = 'O-O' if move.dst > move.src else 'O-O-O'
    else:
        name = ''
        if p != 'P':
            name = p
            others = [m for m in legal_moves(s) if m.src != move.src and m.dst == move.dst and s.board[m.src] == s.board[move.src]]
            if others:
                same_file = any(m.src & 7 == move.src & 7 for m in others)
                same_rank = any(m.src >> 4 == move.src >> 4 for m in others)
                name += (square_name(move.src)[0] if not same_file else
                         square_name(move.src)[1] if not same_rank else square_name(move.src))
        elif capture:
            name = square_name(move.src)[0]
        name += ('x' if capture else '') + square_name(move.dst)
        if move.promotion:
            name += '=' + move.promotion.upper()
    after = make_move(s,move)
    if in_check(after):
        name += '#' if not legal_moves(after) else '+'
    return name


def repetition_key(s: Position) -> tuple:
    # La casilla EP solo cambia derechos efectivos si existe captura al paso legal.
    ep = s.ep if s.ep >= 0 and any(m.flag == 'ep' for m in legal_moves(s)) else -1
    return (s.board,s.turn,s.castle,ep)


def insufficient_material(s: Position) -> bool:
    other = [(p.lower(),((i >> 4) + (i&7))&1) for i,p in enumerate(s.board) if on_board(i) and p not in ('.','k','K')]
    if not other: return True
    if len(other) == 1 and other[0][0] in ('n','b'): return True
    # Solo alfiles en casillas de un mismo color.
    return all(p == 'b' for p,c in other) and len({c for p,c in other}) == 1


def game_status(history: list[Position]) -> dict:
    s = history[-1]
    legal = legal_moves(s)
    check = in_check(s)
    status = {'finished':False, 'winner':None, 'reason':'', 'check':check}
    if not legal:
        status.update(finished=True, winner=('black' if s.turn == 1 else 'white') if check else None,
                      reason='Jaque mate' if check else 'Tablas por ahogado')
    elif insufficient_material(s):
        status.update(finished=True, reason='Tablas por material insuficiente')
    elif s.halfmove >= 150:
        status.update(finished=True, reason='Tablas por regla de 75 movimientos')
    elif sum(repetition_key(old)==repetition_key(s) for old in history) >= 5:
        status.update(finished=True, reason='Tablas por repetición quíntuple')
    elif s.halfmove >= 100:
        status['claimable_draw'] = 'Regla de 50 movimientos'
    elif sum(repetition_key(old)==repetition_key(s) for old in history) >= 3:
        status['claimable_draw'] = 'Triple repetición'
    return status
