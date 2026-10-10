import unittest

from router.rules import Task, operational_fallback, route


class RouterTests(unittest.TestCase):
    def test_research_prefers_deepseek_worker(self):
        self.assertEqual(route(Task("research", "medium")).candidates, ("deepseek", "luna", "sol"))

    def test_tool_coding_is_local_first(self):
        self.assertEqual(route(Task("coding", "medium", needs_tools=True)).candidates[0], "local-heavy")

    def test_high_complexity_escalates(self):
        self.assertEqual(route(Task("general", "high")).candidates[0], "sol")

    def test_operational_fallback_skips_unhealthy_or_excluded(self):
        candidates = ("local-small", "deepseek", "sol")
        self.assertEqual(operational_fallback(candidates, {"deepseek", "sol"}, {"deepseek"}), "sol")

    def test_negative_context_rejected(self):
        with self.assertRaises(ValueError):
            route(Task("general", "low", context_tokens=-1))


if __name__ == "__main__":
    unittest.main()
