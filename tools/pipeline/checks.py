"""Small pass/fail checks for kill counts and killers.

Each check passes silently or raises CheckError.
Run the unit cases with: python tools/pipeline/checks.py
"""

import unittest


class CheckError(Exception):
    """Raised when a check fails."""


def kill_count_check(found, total):
    """Pass only if the number of kills found equals the total kills."""
    if found != total:
        raise CheckError(f"kill count mismatch: found {found}, total {total}")


def killer_check(kills, player):
    """Pass only if every kill was made by the player.

    kills: iterable of killer names, one per kill.
    player: the name of the player being checked.
    """
    wrong = [killer for killer in kills if killer != player]
    if wrong:
        raise CheckError(f"kills by other players: {wrong}")


class ChecksTest(unittest.TestCase):
    def test_kill_count_equal_passes(self):
        kill_count_check(4, 4)

    def test_kill_count_zero_passes(self):
        kill_count_check(0, 0)

    def test_kill_count_too_few_raises(self):
        with self.assertRaises(CheckError):
            kill_count_check(3, 4)

    def test_kill_count_too_many_raises(self):
        with self.assertRaises(CheckError):
            kill_count_check(5, 4)

    def test_killer_all_player_passes(self):
        killer_check(["dem0n", "dem0n"], "dem0n")

    def test_killer_no_kills_passes(self):
        killer_check([], "dem0n")

    def test_killer_other_player_raises(self):
        with self.assertRaises(CheckError):
            killer_check(["dem0n", "donk"], "dem0n")


if __name__ == "__main__":
    unittest.main()
