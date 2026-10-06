import unittest

from tetris_game import Game, HEIGHT, PIECES


class GameTests(unittest.TestCase):
    def test_every_bag_contains_all_seven_pieces(self):
        game = Game(seed=72, now=0)
        pieces = [game.kind] + game.queue
        pieces.extend(game.random_piece() for _ in range(22))
        for start in range(0, 28, 7):
            self.assertEqual(set(pieces[start:start + 7]), set(PIECES))

    def test_handicap_does_not_change_the_seeded_piece_sequence(self):
        regular = Game(seed=13, now=0)
        champion = Game(seed=13, garbage_rows=5, now=0)
        self.assertEqual(regular.kind, champion.kind)
        self.assertEqual(regular.queue, champion.queue)
        self.assertEqual([regular.random_piece() for _ in range(70)],
                         [champion.random_piece() for _ in range(70)])
        self.assertEqual(champion.garbage_remaining, 5)
        for row in champion.board[-5:]:
            self.assertEqual(row.count(None), 1)
            self.assertEqual(row.count("G"), champion.width - 1)
        self.assertTrue(all(all(cell is None for cell in row) for row in champion.board[:-5]))

    def test_hold_is_available_only_once_per_piece(self):
        game = Game(seed=1, now=0)
        first, second = game.kind, game.next_piece
        self.assertTrue(game.action("hold", 1))
        self.assertEqual(game.kind, second)
        self.assertEqual(game.held_piece, first)
        self.assertFalse(game.action("hold", 1.1))
        game.action("drop", 2)
        current = game.kind
        self.assertTrue(game.action("hold", 3))
        self.assertEqual(game.kind, first)
        self.assertEqual(game.held_piece, current)

    def test_hard_drop_scores_locks_and_spawns_exactly_once(self):
        game = Game(seed=3, now=0)
        next_piece = game.next_piece
        distance = game.ghost_y() - game.y
        game.action("drop", 1)
        self.assertEqual(game.score, distance * 2)
        self.assertEqual(sum(bool(cell) for row in game.board for cell in row), 4)
        self.assertEqual(game.kind, next_piece)
        self.assertEqual(game.piece_number, 2)

    def test_rotation_can_kick_away_from_wall(self):
        game = Game(seed=3, now=0)
        game.kind = "I"
        game.rotation = 1
        game.x, game.y = game.width - 1, 3
        self.assertTrue(game.rotate())
        self.assertFalse(game.collides(game.x, game.y, game.rotation))
        self.assertLessEqual(max(x for x, _ in game.cells()), game.width - 1)

    def test_lock_delay_and_hard_drop(self):
        game = Game(seed=1, now=0)
        game.y = game.ghost_y()
        game.tick(0)
        game.tick(0.34)
        self.assertEqual(game.piece_number, 1)
        game.tick(0.36)
        self.assertEqual(game.piece_number, 2)
        game.action("drop", 0.37)
        self.assertEqual(game.piece_number, 3)

    def test_pause_preserves_gravity_and_elapsed_time(self):
        game = Game(seed=1, now=0)
        game.toggle_pause(0.3)
        game.tick(100)
        self.assertEqual(game.y, 0)
        self.assertEqual(game.snapshot(100)["elapsed"], 0.3)
        game.toggle_pause(100.3)
        game.tick(100.4)
        self.assertEqual(game.y, 0)
        game.tick(100.8)
        self.assertEqual(game.y, 1)
        self.assertAlmostEqual(game.snapshot(100.8)["elapsed"], 0.8)

    def prepare_tetris(self, game):
        game.board = [[None] * game.width for _ in range(HEIGHT)]
        for row in range(HEIGHT - 4, HEIGHT):
            game.board[row] = [None if x == 3 else "J" for x in range(game.width)]
        game.kind, game.rotation, game.x, game.y = "I", 1, 3, HEIGHT - 4

    def test_tetris_back_to_back_combo_and_level_scoring(self):
        game = Game(seed=1, now=0)
        self.prepare_tetris(game)
        self.assertEqual(game.lock(1), [16, 17, 18, 19])
        self.assertEqual((game.score, game.lines, game.combo), (800, 4, 0))
        self.prepare_tetris(game)
        game.lock(2)
        self.assertEqual((game.score, game.lines, game.combo), (2050, 8, 1))
        self.prepare_tetris(game)
        game.lock(3)
        self.assertEqual((game.score, game.lines, game.level), (3350, 12, 2))
        self.assertTrue(game.event["level_up"])

    def test_garbage_is_clearable_and_cleanup_time_is_recorded(self):
        game = Game(seed=45, garbage_rows=5, now=10)
        hole = game.board[-1].index(None)
        game.kind, game.rotation, game.x, game.y = "I", 1, hole, HEIGHT - 4
        self.assertEqual(len(game.lock(14)), 4)
        self.assertEqual(game.garbage_remaining, 1)
        self.assertIsNone(game.garbage_cleared_at)
        game.kind, game.rotation, game.x, game.y = "I", 1, hole, 0
        self.assertEqual(len(game.hard_drop(17)), 1)
        self.assertEqual(game.garbage_remaining, 0)
        self.assertEqual(game.garbage_cleared_at, 7)

    def test_eliminated_game_cannot_change_score_or_respawn(self):
        game = Game(seed=9, now=0)
        game.finish(12)
        before = game.snapshot(12)
        for action in ("drop", "hold", "left", "rotate"):
            self.assertFalse(game.action(action, 15))
        game.tick(100)
        self.assertEqual(before, game.snapshot(100))

    def test_game_over_when_spawn_is_obstructed(self):
        game = Game(seed=10, now=0)
        game.board[0] = ["Z"] * game.width
        game.spawn(1)
        self.assertTrue(game.game_over)
        self.assertEqual(game.ended_at, 1)

    def test_snapshots_are_detached_and_can_render_a_view(self):
        game = Game(seed=1, now=0)
        snap = game.snapshot(1)
        view = Game.from_snapshot(snap)
        self.assertEqual(view.cells(), game.cells())
        self.assertEqual(view.ghost_y(), game.ghost_y())
        self.assertEqual(view.next_piece, game.next_piece)
        snap["board"][19][0] = "G"
        self.assertIsNone(game.board[19][0])


if __name__ == "__main__":
    unittest.main()
