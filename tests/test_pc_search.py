import sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from planner import plan, landings
from geometry import advance, fits, orientations, settle, cellset
from recognition import Recognizer
from helpers import C, scene, Game, FakeBackend, synthetic_tick
from controller import AutoController
from input_win import KeyPulse


def two_o():
    return [[0] * 10 for _ in range(18)] + [[1] * 6 + [0] * 4 for _ in range(2)]


class PCSearchTests(unittest.TestCase):
    def test_rotation_required_and_no_rotation_cannot_clear(self):
        b = [[0] * 10 for _ in range(16)] + [[1] * 9 + [0] for _ in range(4)]
        p = plan(b, "I", (3, 0, 0), None, [], False, budget_ms=400)
        self.assertEqual(p["result"]["lines"], 4)
        self.assertIn("up", p["result"]["path"])
        self.assertFalse(any(a["lines"] for a in landings(b, "I", rotation=False)))

    def replay(self, b, current, held, queue, trail):
        for a in trail:
            if a["hold"]:
                current, held = held or queue.pop(0), current
            self.assertEqual(current, a["kind"])
            state = (3, 0, 0)
            # Re-route from the independent simulation state before locking.
            from planner import route_to

            path = route_to(b, current, state, a["cells"])
            self.assertIsNotNone(path)
            for action in path[:-1]:
                state = advance(b, current, state, action)
                self.assertIsNotNone(state)
            x, y, r = state
            while fits(b, orientations(current)[r], x, y + 1):
                y += 1
            self.assertEqual(cellset(current, (x, y, r)), frozenset(map(tuple, a["cells"])))
            b, lines = settle(b, orientations(current)[r], x, y)
            self.assertEqual(lines, a["lines"])
            if queue:
                current = queue.pop(0)
        return b

    def test_filled_hold_needed_for_two_piece_pc(self):
        p = plan(two_o(), "T", (3, 0, 0), "O", ["O"], True, budget_ms=600)
        self.assertEqual(p["pc_status"], "found_confirmed_queue")
        self.assertEqual(p["pc_remaining"], 2)
        self.assertTrue(p["result"]["hold"])
        self.assertFalse(any(map(any, self.replay(two_o(), "T", "O", ["O"], p["pc_path"]))))
        no = plan(two_o(), "T", (3, 0, 0), "O", ["O"], False, budget_ms=600)
        self.assertEqual(no["pc_status"], "exhausted_within_horizon")

    def test_empty_hold_consumes_next_and_preserves_repeats(self):
        p = plan(two_o(), "T", (3, 0, 0), None, ["O", "O"], True, budget_ms=600)
        self.assertEqual(p["visible_next"], ["O", "O"])
        self.assertTrue(p["result"]["hold"])
        self.assertFalse(any(map(any, self.replay(two_o(), "T", None, ["O", "O"], p["pc_path"]))))

    def test_hold_not_available_before_lock(self):
        p = plan(two_o(), "T", (3, 0, 0), "O", ["O"], True, allow_hold=False, budget_ms=400, max_depth=1)
        self.assertFalse(p["result"]["hold"])
        self.assertEqual(p["hold_candidates"], 0)

    def test_impossible_within_horizon_does_not_claim_global_impossible(self):
        p = plan([[0] * 10 for _ in range(20)], "T", (3, 0, 0), None, [], False, budget_ms=200)
        self.assertEqual(p["pc_status"], "exhausted_within_horizon")
        self.assertEqual(p["pc_horizon"], 1)
        self.assertEqual(p["pc_future"], "unknown_beyond_observed_queue")

    def test_unknown_next_stops_confirmed_prefix(self):
        p = plan(two_o(), "T", (3, 0, 0), None, ["O", "?", "O"], True, budget_ms=200)
        self.assertEqual(p["visible_next"], ["O"])
        self.assertNotEqual(p["pc_status"], "found_confirmed_queue")

    def test_time_budget_incumbent_is_reachable(self):
        p = plan([[0] * 10 for _ in range(20)], "T", (3, 0, 0), "I", list("OILSZT"), True, budget_ms=0.01)
        self.assertTrue(p["timed_out"])
        self.assertIsNotNone(p["result"])
        self.assertLess(p["search_ms"], 50)
        self.assertIsNone(p["result"]["expected_points"])

    def test_high_board_policy_has_valid_survival_fallback(self):
        b = [[0] * 10 for _ in range(6)] + [[1] * 8 + [0, 0] for _ in range(14)]
        p = plan(b, "O", (3, 0, 0), "I", ["T", "S", "Z"], True, budget_ms=250)
        self.assertIsNotNone(p["result"])
        self.assertNotEqual(p["pc_status"], "found_confirmed_queue")
        self.assertTrue(p["fallback_reason"])

    def test_all_candidate_routes_include_real_descent_and_cw(self):
        b = two_o()
        for kind in "IJLOSTZ":
            for a in landings(b, kind):
                state = (3, 0, 0)
                self.assertNotIn("z", a["path"])
                for action in a["path"][:-1]:
                    state = advance(b, kind, state, action)
                    self.assertIsNotNone(state)
                x, y, r = state
                while fits(b, orientations(kind)[r], x, y + 1):
                    y += 1
                self.assertEqual(cellset(kind, (x, y, r)), frozenset(a["cells"]))


class ObservationRegressions(unittest.TestCase):
    def test_wrong_prediction_never_overwrites_pixels(self):
        r = Recognizer()
        b = two_o()
        rgb = scene(b)
        wrong = [[0] * 10 for _ in range(20)]
        for i in range(2):
            o = r.process(rgb, (0, 0, 340, 400), C, i, time.monotonic(), expected_fixed=wrong)
        self.assertEqual(o.fixed, b)
        self.assertFalse(o.prediction_match)

    def test_out_of_order_frames_rejected(self):
        r = Recognizer()
        rgb = scene(two_o())
        r.process(rgb, (0, 0, 340, 400), C, 2, time.monotonic())
        with self.assertRaises(ValueError):
            r.process(rgb, (0, 0, 340, 400), C, 1, time.monotonic())

    def test_fixed_change_mid_movement_requires_recheck(self):
        r = Recognizer()
        b = [[0] * 10 for _ in range(20)]
        for i in range(2):
            r.process(scene(b, state=(3, 5, 0)), (0, 0, 340, 400), C, i, time.monotonic())
        b[19][0] = 1
        o = r.process(scene(b, state=(3, 6, 0)), (0, 0, 340, 400), C, 2, time.monotonic())
        self.assertFalse(o.valid)
        self.assertTrue(o.reason)

    def test_line_clear_same_kind_recovery(self):
        g = Game()
        g.board = [[0] * 10 for _ in range(16)] + [[1] * 9 + [0] for _ in range(4)]
        g.kind = "I"
        g.queue = ["I", "I", "I", "I", "O"]
        r = Recognizer()
        ctl = AutoController(KeyPulse(FakeBackend(g.input)), C)
        now = time.monotonic()
        ctl.start(99, now)
        for i in range(300):
            t = now + i * 0.02
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t)
            if o.valid and not ctl.plan and not ctl.wait:
                p = plan(o.fixed, o.active.kind, o.active.state, None, [], False, budget_ms=200)
                p["key"] = (o.board_key, o.active.kind, False)
                ctl.accept_plan(p, o)
            synthetic_tick(ctl, o, t)
            if ctl.blocks:
                break
        self.assertEqual(ctl.blocks, 1, ctl.reason)
        self.assertFalse(any(map(any, g.board)))
        self.assertEqual(g.kind, "I")
        self.assertTrue(ctl.running)
        ctl.stop()


if __name__ == "__main__":
    unittest.main()
