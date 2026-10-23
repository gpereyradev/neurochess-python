"""Servidor web sin dependencias: python app.py -> http://localhost:8000

Frontend de HTML/CSS/JS nativo; lógica ajedrecística y Minimax 100 % en Python.
"""
import json
import logging
import mimetypes
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from uuid import uuid4

from chess_core import START_FEN, from_fen, legal_moves, game_status, find_move, make_move, to_san
from ai import choose_move

ROOT = Path(__file__).resolve().parent
STATIC = ROOT/'static'
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
MAX_SESSIONS = 400


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Game:
    def __init__(self, player='white', difficulty=2):
        self.id = uuid4().hex
        self.player = player
        self.difficulty = difficulty
        self.positions = [from_fen(START_FEN)]
        self.moves = []
        self.last_search = None
        self.hint = None
        self.claimed = None
        self.revision = 0
        self.lock = threading.RLock()

    def state(self):
        s = self.positions[-1]
        status = game_status(self.positions)
        if self.claimed:
            status.update(finished=True, reason=self.claimed, winner=None)
        b = s.board
        return {
            'game_id':self.id,
            'revision':self.revision,
            'fen':s.fen(),
            'board': [[b[r*16+c] for c in range(8)] for r in range(8)],
            'turn':'white' if s.turn==1 else 'black',
            'player':self.player,
            'difficulty':self.difficulty,
            'status':status,
            'legal_moves':([] if status['finished'] else [m.uci for m in legal_moves(s)]),
            'moves':self.moves,
            'can_undo':any(item['by']=='human' for item in self.moves),
            'last_search':self.last_search,
            'hint':self.hint,
        }

    def commit(self, move, actor):
        previous = self.positions[-1]
        item = {'number':previous.fullmove, 'side':'white' if previous.turn==1 else 'black',
                'uci':move.uci, 'san':to_san(previous,move), 'by':actor}
        self.moves.append(item)
        self.positions.append(make_move(previous,move))
        self.hint = None
        self.claimed = None
        self.revision += 1
        return item


def get_game(body):
    game_id = body.get('game_id') if isinstance(body,dict) else None
    if not isinstance(game_id,str) or len(game_id)!=32:
        raise APIError('Identificador de partida inválido',404)
    with SESSIONS_LOCK:
        game = SESSIONS.get(game_id)
    if not game:
        raise APIError('La partida expiró. Inicia una nueva.',404)
    return game


def api_post(path, body):
    if not isinstance(body,dict):
        raise APIError('Se requiere un objeto JSON')
    if path == '/api/new':
        player = body.get('player','white')
        if player not in ('white','black'):
            raise APIError('Color inválido')
        try: depth = int(body.get('difficulty',2))
        except (ValueError,TypeError): raise APIError('Dificultad inválida')
        if depth not in (1,2,3,4):
            raise APIError('Dificultad inválida')
        game = Game(player,depth)
        with SESSIONS_LOCK:
            if len(SESSIONS) >= MAX_SESSIONS:
                # Tope sencillo de sesiones volátiles para demostración sin BD.
                SESSIONS.pop(next(iter(SESSIONS)))
            SESSIONS[game.id] = game
        return game.state()

    game = get_game(body)
    if path == '/api/state':
        with game.lock:
            return game.state()
    if path == '/api/move':
        with game.lock:
            status = game_status(game.positions)
            if status['finished'] or game.claimed:
                raise APIError('La partida ya terminó')
            s = game.positions[-1]
            if ('white' if s.turn==1 else 'black') != game.player:
                raise APIError('Ahora le toca a la IA')
            move_str = body.get('move')
            if not isinstance(move_str,str) or not 4<=len(move_str)<=5:
                raise APIError('Movimiento inválido')
            try: move = find_move(s,move_str)
            except ValueError: raise APIError('Movimiento ilegal')
            game.commit(move,'human')
            return game.state()
    if path in ('/api/ai','/api/hint'):
        with game.lock:
            status = game_status(game.positions)
            if status['finished'] or game.claimed:
                raise APIError('La partida ya terminó')
            s = game.positions[-1]
            current_side = 'white' if s.turn==1 else 'black'
            if (path=='/api/ai' and current_side==game.player) or (path=='/api/hint' and current_side!=game.player):
                raise APIError('No corresponde este turno')
            revision, depth = game.revision, game.difficulty
        # La búsqueda sucede fuera del bloqueo. Deshacer o reiniciar no queda bloqueado.
        move, data = choose_move(s,depth)
        with game.lock:
            if revision != game.revision:
                raise APIError('La posición cambió durante el cálculo',409)
            if move is None:
                raise APIError('No quedan movimientos')
            if path == '/api/hint':
                game.hint = {'uci':move.uci, 'score_cp':data.score_cp, 'depth':data.depth}
            else:
                game.commit(move,'ai')
                game.last_search = data.to_dict()
            return game.state()
    if path == '/api/undo':
        with game.lock:
            if not any(item['by']=='human' for item in game.moves):
                raise APIError('Aún no hay un turno del jugador para deshacer')
            # Deshace la respuesta de la IA (si existe) y la última jugada humana.
            while game.moves and game.moves[-1]['by'] != 'human':
                game.moves.pop()
                game.positions.pop()
            if game.moves and game.moves[-1]['by']=='human':
                game.moves.pop()
                game.positions.pop()
            game.last_search = None
            game.hint = None
            game.claimed = None
            game.revision += 1
            return game.state()
    if path == '/api/claim-draw':
        with game.lock:
            status = game_status(game.positions)
            if not status.get('claimable_draw'):
                raise APIError('No se pueden reclamar tablas en esta posición')
            side_to_move = 'white' if game.positions[-1].turn == 1 else 'black'
            if side_to_move != game.player:
                raise APIError('Solo puedes reclamar tablas durante tu turno')
            game.claimed = 'Tablas por ' + status['claimable_draw'].lower()
            game.revision += 1
            return game.state()
    raise APIError('Ruta inexistente',404)


class Handler(BaseHTTPRequestHandler):
    server_version = 'NeuroChess/2'

    def _respond(self, status, data, mime='application/json; charset=utf-8'):
        if isinstance(data,dict):
            data = json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/health':
            self._respond(200,{'ok':True,'engine':'Python Minimax + alpha-beta'})
            return
        names = {'/':'index.html','/index.html':'index.html','/styles.css':'styles.css','/app.js':'app.js',
                 '/favicon.svg':'favicon.svg'}
        name = names.get(path)
        if not name:
            self._respond(404,{'error':'No encontrado'})
            return
        filepath = STATIC/name
        try:
            content = filepath.read_bytes()
        except OSError:
            self._respond(404,{'error':'Recurso no encontrado'})
            return
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        self._respond(200,content,mime+('; charset=utf-8' if mime.startswith('text/') or mime in ('application/javascript','image/svg+xml') else ''))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get('Content-Length','0'))
            if length > 16384 or length < 2:
                raise APIError('Tamaño de solicitud inválido',413)
            raw = self.rfile.read(length)
            try: body = json.loads(raw)
            except (UnicodeDecodeError,json.JSONDecodeError): raise APIError('JSON inválido')
            response = api_post(path,body)
            self._respond(200,response)
        except APIError as exc:
            self._respond(exc.status,{'error':str(exc)})
        except Exception:
            logging.exception('Error inesperado en API')
            self._respond(500,{'error':'Error interno del servidor'})


def main():
    port = int(os.environ.get('PORT','8000'))
    host = os.environ.get('HOST','0.0.0.0')
    server = ThreadingHTTPServer((host,port),Handler)
    print(f'NeuroChess Python listo en http://localhost:{port}  (Ctrl+C para detener)',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor detenido')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
