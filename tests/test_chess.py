import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from chess_core import (START_FEN,from_fen,parse_square,legal_moves,find_move,make_move,
                        game_status,to_san,in_check,repetition_key)
from ai import choose_move
from ai import AlphaBeta, MATE
from app import api_post, APIError, SESSIONS
from unittest.mock import patch
from time import monotonic


def sequence(*moves):
    states=[from_fen()]
    for uci in moves:
        states.append(make_move(states[-1],find_move(states[-1],uci)))
    return states


def perft(pos,depth):
    if depth==0:return 1
    return sum(perft(make_move(pos,m),depth-1) for m in legal_moves(pos))


class RulesTests(unittest.TestCase):
    def test_initial_position_and_turn(self):
        s=from_fen()
        self.assertEqual(s.fen(),START_FEN)
        self.assertEqual(s.turn,1)  # ¡Blancas comienzan siempre!
        self.assertEqual(s.board[parse_square('d1')],'Q')
        self.assertEqual(s.board[parse_square('d8')],'q')
        self.assertEqual(len(legal_moves(s)),20)
        self.assertEqual(perft(s,2),400)

    def test_no_illegal_moves_by_king(self):
        states=sequence('f2f3','e7e5','g2g4','d8h4')
        self.assertTrue(in_check(states[-1]))
        status=game_status(states)
        self.assertTrue(status['finished'])
        self.assertEqual(status['reason'],'Jaque mate')
        self.assertEqual(status['winner'],'black')
        self.assertEqual(len(legal_moves(states[-1])),0)
        self.assertEqual(to_san(states[-2],find_move(states[-2],'d8h4')),'Qh4#')

    def test_en_passant(self):
        states=sequence('e2e4','a7a6','e4e5','d7d5')
        before=states[-1]
        move=find_move(before,'e5d6')
        self.assertEqual(move.flag,'ep')
        self.assertEqual(to_san(before,move),'exd6')
        result=make_move(before,move)
        self.assertEqual(result.board[parse_square('d5')],'.')
        self.assertEqual(result.board[parse_square('d6')],'P')

    def test_castling_both_sides(self):
        s=from_fen('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')
        options=[m.uci for m in legal_moves(s)]
        self.assertIn('e1g1',options)
        self.assertIn('e1c1',options)
        after=make_move(s,find_move(s,'e1g1'))
        self.assertEqual(after.board[parse_square('g1')],'K')
        self.assertEqual(after.board[parse_square('f1')],'R')
        self.assertEqual(after.board[parse_square('h1')],'.')
        self.assertEqual(after.castle&3,0)

    def test_castle_through_check_forbidden(self):
        s=from_fen('4kr2/8/8/8/8/8/8/4K2R w K - 0 1')
        self.assertNotIn('e1g1',[m.uci for m in legal_moves(s)])

    def test_promotion_choices(self):
        s=from_fen('4k3/P7/8/8/8/8/8/4K3 w - - 0 1')
        options=sorted(m.uci for m in legal_moves(s) if m.uci.startswith('a7a8'))
        self.assertEqual(options,['a7a8b','a7a8n','a7a8q','a7a8r'])
        result=make_move(s,find_move(s,'a7a8n'))
        self.assertEqual(result.board[parse_square('a8')],'N')

    def test_stalemate(self):
        s=from_fen('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')
        status=game_status([s])
        self.assertTrue(status['finished'])
        self.assertEqual(status['reason'],'Tablas por ahogado')
        self.assertIsNone(status['winner'])

    def test_material_draw(self):
        s=from_fen('4k3/8/8/8/8/8/5N2/4K3 w - - 0 1')
        self.assertEqual(game_status([s])['reason'],'Tablas por material insuficiente')

    def test_position_persists_through_fen(self):
        s=sequence('e2e4','e7e5','g1f3','b8c6')[-1]
        self.assertEqual(from_fen(s.fen()),s)

    def test_standard_perft_depth_3(self):
        # 8,902 nodos es una prueba de referencia ampliamente usada para reglas.
        self.assertEqual(perft(from_fen(),3),8902)


class AITests(unittest.TestCase):
    def test_horizon_stalemate_is_draw(self):
        s=from_fen('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1')
        search=AlphaBeta(monotonic()+1)
        self.assertEqual(search.minimax(s,0,-2*MATE,2*MATE),0)

    def test_claimable_draw_does_not_force_zero_score(self):
        s=from_fen('7k/8/6K1/8/8/8/Q7/8 w - - 100 1')
        self.assertGreater(AlphaBeta(monotonic()+1).minimax(s,0,-2*MATE,2*MATE),500)

    def test_checkmate_takes_priority_over_75_move_rule(self):
        s=from_fen('7k/6Q1/6K1/8/8/8/8/8 b - - 150 1')
        self.assertGreater(AlphaBeta(monotonic()+1).minimax(s,1,-2*MATE,2*MATE),99000)

    def test_minimax_returns_legal_move_for_black(self):
        s=sequence('d2d4')[-1]
        move, metrics=choose_move(s,2,time_limit=2)
        self.assertIn(move,legal_moves(s))
        self.assertGreater(metrics.nodes,0)
        self.assertGreaterEqual(metrics.depth,1)
        self.assertEqual(metrics.best_uci,move.uci)

    def test_minimax_returns_legal_move_for_white(self):
        s=from_fen()
        move,metrics=choose_move(s,1,time_limit=1)
        self.assertIn(move,legal_moves(s))
        self.assertEqual(s.turn,1)

    def test_ai_detects_mate(self):
        # Tras 1.f3 e5 2.g4, negras pueden dar Qh4# en una jugada.
        s=sequence('f2f3','e7e5','g2g4')[-1]
        move,metrics=choose_move(s,2,time_limit=2.0)
        self.assertEqual(move.uci,'d8h4')
        self.assertLess(metrics.score_cp,-99000)


class APITests(unittest.TestCase):
    def test_settings_apply_without_resetting_game(self):
        s=api_post('/api/new',{'difficulty':1})
        moved=api_post('/api/move',{'game_id':s['game_id'],'move':'e2e4'})
        changed=api_post('/api/settings',{'game_id':s['game_id'],'difficulty':3,'revision':moved['revision']})
        self.assertEqual(changed['difficulty'],3)
        self.assertEqual(changed['fen'],moved['fen'])
        self.assertEqual(changed['moves'],moved['moves'])
        with self.assertRaises(APIError):
            api_post('/api/settings',{'game_id':s['game_id'],'difficulty':5})

    def test_resign_result_and_undo(self):
        s=api_post('/api/new',{})
        api_post('/api/move',{'game_id':s['game_id'],'move':'e2e4'})
        resigned=api_post('/api/resign',{'game_id':s['game_id']})
        self.assertTrue(resigned['status']['finished'])
        self.assertEqual(resigned['status']['winner'],'black')
        with self.assertRaises(APIError): api_post('/api/ai',{'game_id':s['game_id']})
        resumed=api_post('/api/undo',{'game_id':s['game_id']})
        self.assertFalse(resumed['status']['finished'])
        self.assertEqual(resumed['fen'],START_FEN)

    def test_stale_revision_cannot_reapply_a_move_or_undo(self):
        s=api_post('/api/new',{})
        api_post('/api/move',{'game_id':s['game_id'],'move':'e2e4','revision':0})
        with self.assertRaises(APIError) as caught:
            api_post('/api/undo',{'game_id':s['game_id'],'revision':0})
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(len(api_post('/api/state',{'game_id':s['game_id']})['moves']),1)

    def test_inflight_ai_does_not_commit_after_resignation(self):
        s=api_post('/api/new',{'difficulty':1})
        api_post('/api/move',{'game_id':s['game_id'],'move':'e2e4'})
        def resign_during_search(position,depth):
            api_post('/api/resign',{'game_id':s['game_id']})
            return choose_move(position,1)
        with patch('app.choose_move',side_effect=resign_during_search):
            with self.assertRaises(APIError) as caught:
                api_post('/api/ai',{'game_id':s['game_id']})
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(len(api_post('/api/state',{'game_id':s['game_id']})['moves']),1)

    def test_captured_piece_includes_en_passant(self):
        s=api_post('/api/new',{})
        game=SESSIONS[s['game_id']]
        for uci in ['e2e4','a7a6','e4e5','d7d5','e5d6']:
            game.commit(find_move(game.positions[-1],uci),'human')
        self.assertEqual(game.state()['moves'][-1]['captured'],'p')

    def test_new_game_and_move(self):
        state=api_post('/api/new',{'player':'white','difficulty':1})
        self.assertEqual(state['turn'],'white')
        self.assertEqual(len(state['board']),8)
        self.assertTrue(all(len(row)==8 for row in state['board']))
        self.assertIn('e2e4',state['legal_moves'])
        self.assertEqual(state['board'][7][3],'Q')
        self.assertEqual(state['board'][0][3],'q')
        result=api_post('/api/move',{'game_id':state['game_id'],'move':'e2e4'})
        self.assertEqual(result['turn'],'black')
        self.assertEqual(result['moves'][0]['san'],'e4')
        answered=api_post('/api/ai',{'game_id':state['game_id']})
        self.assertEqual(answered['turn'],'white')
        self.assertEqual(len(answered['moves']),2)
        self.assertTrue(answered['last_search']['nodes']>0)
        undo=api_post('/api/undo',{'game_id':state['game_id']})
        self.assertEqual(undo['turn'],'white')
        self.assertEqual(undo['fen'],START_FEN)
        self.assertFalse(undo['can_undo'])

    def test_black_player_receives_white_ai_first(self):
        s=api_post('/api/new',{'player':'black','difficulty':1})
        self.assertEqual(s['turn'],'white')
        reply=api_post('/api/ai',{'game_id':s['game_id']})
        self.assertEqual(reply['moves'][0]['side'],'white')
        self.assertEqual(reply['turn'],'black')

if __name__=='__main__': unittest.main()
