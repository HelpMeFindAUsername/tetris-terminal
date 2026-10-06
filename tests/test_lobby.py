import unittest

from tetris_game import Game
from tetris_server import Lobby, Session


def player(name):
    return Session(sock=None, ip="127.0.0.1", nickname=name, hello=True)


class LobbyTests(unittest.TestCase):
    def setUp(self):
        self.owner = player("Ada")
        self.second = player("Linus")
        self.lobby = Lobby("Amici", "segreto", self.owner, countdown=0)
        self.lobby.add(self.second)

    def start(self, now=0):
        for member in self.lobby.members.values():
            member.ready = True
        self.lobby.start(self.owner, now)
        self.lobby.tick(now)
        self.assertEqual(self.lobby.phase, "playing")

    def test_wrong_password_and_case_sensitive_password(self):
        self.assertTrue(self.lobby.verify_password("segreto"))
        self.assertFalse(self.lobby.verify_password("Segreto"))
        self.assertFalse(self.lobby.verify_password("errata"))

    def test_start_requires_owner_and_everyone_ready(self):
        with self.assertRaisesRegex(ValueError, "creatore"):
            self.lobby.start(self.second, 0)
        self.owner.ready = True
        with self.assertRaisesRegex(ValueError, "pronti"):
            self.lobby.start(self.owner, 0)
        self.second.ready = True
        self.lobby.start(self.owner, 0)
        self.assertEqual(self.lobby.phase, "countdown")

    def test_waits_for_every_player_and_never_restarts_automatically(self):
        third = player("Grace")
        self.lobby.add(third)
        self.start()
        self.owner.game.score = 999
        self.owner.game.finish(1)
        self.lobby.tick(1)
        self.assertEqual(self.lobby.phase, "playing")
        self.second.game.finish(2)
        self.lobby.tick(2)
        self.assertEqual(self.lobby.phase, "playing")
        third.game.score = 300
        third.game.finish(3)
        self.lobby.tick(3)
        self.assertEqual(self.lobby.phase, "results")
        self.assertEqual(self.lobby.results[0]["id"], self.owner.player_id)
        self.assertEqual(self.owner.wins, 1)
        old_games = [p.game for p in self.lobby.members.values()]
        self.lobby.tick(1000)
        self.assertEqual(self.lobby.phase, "results")
        self.assertEqual(old_games, [p.game for p in self.lobby.members.values()])
        with self.assertRaisesRegex(ValueError, "pronti"):
            self.lobby.start(self.owner, 1000)

    def test_only_previous_winner_gets_five_incomplete_rows(self):
        self.start()
        self.owner.game.score, self.second.game.score = 200, 10
        self.owner.game.finish(1)
        self.second.game.finish(2)
        self.lobby.tick(2)
        self.start(3)
        self.assertEqual(self.lobby.round, 2)
        self.assertEqual(self.owner.game.garbage_remaining, 5)
        self.assertEqual(self.second.game.garbage_remaining, 0)
        self.assertEqual(self.owner.game.kind, self.second.game.kind)
        self.assertEqual(self.owner.game.queue, self.second.game.queue)
        # Handicap expires when a different player wins the following round.
        self.owner.game.score, self.second.game.score = 10, 200
        self.owner.game.finish(4)
        self.second.game.finish(4)
        self.lobby.tick(4)
        self.start(5)
        self.assertEqual(self.owner.game.garbage_remaining, 0)
        self.assertEqual(self.second.game.garbage_remaining, 5)

    def test_equal_scores_share_victory_and_handicap(self):
        self.start()
        self.owner.game.score = self.second.game.score = 50
        self.owner.game.finish(1)
        self.second.game.finish(2)
        self.lobby.tick(2)
        self.assertEqual([row["rank"] for row in self.lobby.results], [1, 1])
        self.assertTrue(all(row["winner"] for row in self.lobby.results))
        self.start(3)
        self.assertEqual(self.owner.game.garbage_remaining, 5)
        self.assertEqual(self.second.game.garbage_remaining, 5)

    def test_join_in_progress_is_spectator_until_next_round(self):
        self.start()
        spectator = player("Grace")
        self.lobby.add(spectator)
        self.assertIsNone(spectator.game)
        self.assertNotIn(spectator.player_id, self.lobby.participants)
        self.owner.game.finish(1)
        self.second.game.finish(1)
        self.lobby.tick(1)
        self.assertEqual(self.lobby.phase, "results")
        self.start(2)
        self.assertIsNotNone(spectator.game)
        self.assertIn(spectator.player_id, self.lobby.participants)

    def test_disconnection_eliminates_player_and_transfers_owner(self):
        self.start()
        self.owner.game.score = 999
        self.lobby.remove(self.owner, 1)
        self.assertTrue(self.owner.game.game_over)
        self.assertEqual(self.lobby.owner_id, self.second.player_id)
        self.assertEqual(self.lobby.phase, "playing")
        self.second.game.finish(2)
        self.lobby.tick(2)
        self.assertEqual(self.lobby.phase, "results")
        self.assertEqual(self.lobby.results[0]["score"], 999)
        self.assertFalse(self.lobby.results[0]["connected"])

    def test_moving_to_another_lobby_preserves_old_round(self):
        self.start()
        old_game = self.owner.game
        old_game.score = 999
        self.lobby.remove(self.owner, 1)
        other = Lobby("Altra", "pw", self.owner)
        self.owner.game = Game(seed=4, now=2)
        self.second.game.finish(3)
        self.lobby.tick(3)
        self.assertEqual(self.lobby.phase, "results")
        self.assertEqual(self.lobby.results[0]["score"], 999)
        self.assertIs(self.lobby.participants[self.owner.player_id].game, old_game)
        self.assertIs(self.owner.lobby, other)

    def test_departure_cancels_countdown(self):
        self.owner.ready = self.second.ready = True
        self.lobby.start(self.owner, 0)
        self.lobby.remove(self.second, 0.1)
        self.assertEqual(self.lobby.phase, "waiting")
        self.assertFalse(self.owner.ready)
        self.lobby.tick(100)
        self.assertIsNone(self.owner.game)

    def test_passwords_and_digests_are_never_broadcast(self):
        import json
        encoded = json.dumps(self.lobby.snapshot(0)) + json.dumps(self.lobby.listing())
        self.assertNotIn("segreto", encoded)
        self.assertNotIn("password", encoded)
        self.assertNotIn("salt", encoded)

    def test_lobby_capacity_and_duplicate_nicknames(self):
        lobby = Lobby("Piccola", "pw", player("Ada"), capacity=2)
        with self.assertRaisesRegex(ValueError, "Nickname"):
            lobby.add(player("ada"))
        lobby.add(player("Linus"))
        with self.assertRaisesRegex(ValueError, "piena"):
            lobby.add(player("Grace"))


if __name__ == "__main__":
    unittest.main()
