import copy, sys, time, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpers import C, scene, Game, FakeBackend, synthetic_tick, synthetic_emit
from recognition import Recognizer
from timing import MotionTracker, route_feasible, search_budget
from controller import AutoController
from input_win import KeyPulse, VK
from planner import urgent_plan
from geometry import settle, orientations, cellset


class HighSpeedTrackingTests(unittest.TestCase):
    def test_low_stationary_shape_is_not_an_auto_ready_piece(self):
        c = copy.deepcopy(C)
        c["allow_stationary_bootstrap"] = False
        r = Recognizer()
        b = [[0] * 10 for _ in range(20)]
        for i in range(3):
            o = r.process(scene(b, state=(3, 12, 0)), (0, 0, 340, 400), c, i, 100 + i * 0.02)
        self.assertFalse(o.valid)
        self.assertIn("BOOTSTRAP", o.reason)
        o = r.process(scene(b, state=(3, 15, 0)), (0, 0, 340, 400), c, 3, 100.06)
        o = r.process(scene(b, state=(3, 16, 0)), (0, 0, 340, 400), c, 4, 100.08)
        self.assertTrue(o.valid, o.reason)

    def test_commanded_soft_drop_is_not_gravity_measurement(self):
        r = Recognizer()
        m = MotionTracker()
        b = [[0] * 10 for _ in range(20)]
        for i, y in enumerate((1, 5, 9)):
            o = m.update(
                r.process(scene(b, state=(3, y, 0)), (0, 0, 340, 400), C, i, 100 + i * 0.05), controlled_action="down"
            )
        self.assertEqual(o.gravity_cps, 0)
        self.assertEqual(o.motion_samples, 0)

    def test_multicell_gravity_is_observed_not_predicted(self):
        r = Recognizer()
        m = MotionTracker()
        b = [[0] * 10 for _ in range(20)]
        for i, y in enumerate((1, 5, 9, 13)):
            o = m.update(r.process(scene(b, state=(3, y, 0)), (0, 0, 340, 400), C, i, 100 + i * 0.05))
            self.assertEqual(o.active.cells, cellset("T", (3, y, 0)))
            self.assertEqual(o.generation, 0)
        self.assertTrue(o.valid)
        self.assertGreaterEqual(o.gravity_cps, 80)

    def test_same_kind_new_piece_below_spawn_after_lock(self):
        b = [[0] * 10 for _ in range(20)]
        r = Recognizer()
        for i in range(2):
            o = r.process(scene(b, "I", (3, 12, 0), nexts=("I", "I", "O")), (0, 0, 340, 400), C, i, 100 + i * 0.02)
        old = o.generation
        b, _ = settle(b, orientations("I")[0], 3, 18)
        for i, y in ((2, 6), (3, 10)):
            o = r.process(scene(b, "I", (3, y, 0), nexts=("I", "O", "T")), (0, 0, 340, 400), C, i, 100 + i * 0.04)
        self.assertTrue(o.valid, o.reason)
        self.assertEqual(o.active.kind, "I")
        self.assertEqual(o.active.state[1], 10)
        self.assertEqual(o.generation, old + 1)
        self.assertEqual(o.transition, "lock")
        self.assertEqual(o.fixed, b)

    def test_hold_ack_does_not_require_top_three_rows(self):
        g = Game()
        g.hold = "I"
        r = Recognizer()
        t = 100
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.02)
        ctl = AutoController(KeyPulse(FakeBackend(g.input)), C)
        ctl.start(99, t)
        synthetic_emit(ctl, "hold", o, t + 0.05)
        g.state = (3, 7, 0)
        for i in range(2, 5):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.05)
            synthetic_tick(ctl, o, t + i * 0.05)
        self.assertIsNone(ctl.wait)
        self.assertTrue(ctl.hold_used)
        ctl.stop()

    def test_movement_ack_accepts_more_than_three_cells_fall(self):
        g = Game()
        g.state = (3, 3, 0)
        r = Recognizer()
        t = 100
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.02)
        ctl = AutoController(KeyPulse(FakeBackend(g.input)), C)
        ctl.start(99, t)
        synthetic_emit(ctl, "right", o, t + 0.05)
        g.state = (4, 9, 0)
        o = r.process(g.image(), (0, 0, 340, 400), C, 2, t + 0.10)
        synthetic_tick(ctl, o, t + 0.10)
        self.assertIsNone(ctl.wait)
        ctl.stop()

    def test_old_pending_key_cancelled_on_same_kind_generation(self):
        g = Game()
        g.kind = "I"
        r = Recognizer()
        t = 100
        for i in range(2):
            o = r.process(g.image(), (0, 0, 340, 400), C, i, t + i * 0.02)
        backend = FakeBackend(g.input)
        ctl = AutoController(KeyPulse(backend), C)
        ctl.start(99, t)
        synthetic_tick(ctl, o, t + 0.04)
        synthetic_emit(ctl, "left", o, t + 0.05)
        g.input(VK["SPACE"])
        g.state = (3, 6, 0)
        o = r.process(g.image(), (0, 0, 340, 400), C, 2, t + 0.10)
        synthetic_tick(ctl, o, t + 0.10)
        self.assertIsNone(ctl.wait)
        self.assertIsNone(ctl.plan)
        self.assertFalse(ctl.pulse.pressed)
        count = len(backend.events)
        synthetic_tick(ctl, o, t + 0.11)
        self.assertEqual(len(backend.events), count)
        ctl.stop()

    def test_animation_gap_does_not_invent_piece(self):
        r = Recognizer()
        b = [[0] * 10 for _ in range(20)]
        for i in range(2):
            r.process(scene(b), (0, 0, 340, 400), C, i, 100 + i * 0.02)
        o = r.process(scene(b, kind=None), (0, 0, 340, 400), C, 2, 100.04)
        self.assertFalse(o.valid)
        self.assertIsNone(o.active)

    def test_gravity_budget_and_grounded_path_rejection(self):
        r = Recognizer()
        m = MotionTracker()
        b = [[0] * 10 for _ in range(20)]
        for i, y in enumerate((4, 8, 12)):
            o = m.update(r.process(scene(b, state=(3, y, 0)), (0, 0, 340, 400), C, i, 100 + i * 0.05))
        budget, profile = search_budget(o, C, 20, 100)
        self.assertLess(budget, 160)
        target = cellset("T", (4, 18, 0))
        safe, why = route_feasible(
            b, "T", (3, 18, 0), ("right", "drop"), target, dict(gravity_cps=30, step_ms=100, age_ms=0)
        )
        self.assertFalse(safe)
        self.assertIn("GROUNDED", why)

    def test_no_safe_plan_does_not_invent_drop(self):
        b = [[0] * 10 for _ in range(20)]
        p = urgent_plan(b, "T", (3, 16, 0), timing=dict(gravity_cps=200, step_ms=100, age_ms=100), budget_ms=5)
        self.assertIsNone(p["result"])


if __name__ == "__main__":
    unittest.main()
