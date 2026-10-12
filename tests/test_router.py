import unittest

from router.rules import LocalDestination, Task, operational_fallback, route, route_local


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

    @staticmethod
    def destination(name, **overrides):
        values = {
            "healthy": True,
            "supports_tools": True,
            "supported_templates": frozenset({"chatml"}),
            "max_context_tokens": 8192,
            "estimated_seconds": 5.0,
            "is_local": True,
        }
        values.update(overrides)
        return LocalDestination(name=name, **values)

    def test_local_route_uses_capabilities_and_preserves_candidate_order(self):
        destinations = (
            self.destination("first", max_context_tokens=1024),
            self.destination("second"),
            self.destination("third"),
        )
        result = route_local(
            Task("coding", "medium", needs_tools=True, context_tokens=2048),
            destinations,
            required_template="chatml",
            remaining_deadline_seconds=10,
        )
        self.assertEqual(result.destination, "second")
        self.assertEqual(result.rejected, (("first", "excessive_context"),))
        self.assertEqual(result.routing_layer, "operational_local")

    def test_local_route_rejects_health_tool_template_context_and_deadline(self):
        destinations = (
            self.destination("unhealthy", healthy=False),
            self.destination("no-tools", supports_tools=False),
            self.destination("wrong-template", supported_templates=frozenset({"other"})),
            self.destination("short-context", max_context_tokens=512),
            self.destination("too-slow", estimated_seconds=11),
        )
        result = route_local(
            Task("coding", "medium", needs_tools=True, context_tokens=1024),
            destinations,
            required_template="chatml",
            remaining_deadline_seconds=10,
        )
        self.assertIsNone(result.destination)
        self.assertEqual(result.reason, "no_eligible_destination")
        self.assertEqual(
            result.rejected,
            (
                ("unhealthy", "health_failure"),
                ("no-tools", "unsupported_tools"),
                ("wrong-template", "unsupported_template"),
                ("short-context", "excessive_context"),
                ("too-slow", "deadline_exhaustion"),
            ),
        )

    def test_local_route_rejects_cloud_even_when_other_capabilities_match(self):
        result = route_local(
            Task("general", "low"),
            (self.destination("remote", is_local=False),),
            remaining_deadline_seconds=10,
        )
        self.assertIsNone(result.destination)
        self.assertEqual(result.rejected, (("remote", "cloud_disabled"),))

    def test_local_route_rejects_web_requests_without_cloud_fallback(self):
        result = route_local(
            Task("research", "medium", needs_web=True),
            (self.destination("local"),),
            remaining_deadline_seconds=10,
        )
        self.assertIsNone(result.destination)
        self.assertEqual(result.rejected, (("local", "web_disabled"),))

    def test_local_route_reports_empty_candidate_set(self):
        result = route_local(Task("general", "low"), (), remaining_deadline_seconds=10)
        self.assertIsNone(result.destination)
        self.assertEqual(result.reason, "no_eligible_destination")
        self.assertEqual(result.rejected, ())

    def test_local_route_rejects_negative_deadline(self):
        with self.assertRaises(ValueError):
            route_local(Task("general", "low"), (), remaining_deadline_seconds=-1)

    def test_local_route_rejects_nonfinite_deadline(self):
        for deadline in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                route_local(Task("general", "low"), (), remaining_deadline_seconds=deadline)

    def test_local_route_rejects_negative_or_nonfinite_estimate(self):
        for estimate in (-1.0, float("nan"), float("inf"), float("-inf")):
            with self.subTest(estimate=estimate), self.assertRaises(ValueError):
                route_local(
                    Task("general", "low"),
                    (self.destination("local", estimated_seconds=estimate),),
                    remaining_deadline_seconds=10,
                )

    def test_zero_deadline_is_exhausted_even_for_zero_estimate(self):
        result = route_local(
            Task("general", "low"),
            (self.destination("local", estimated_seconds=0),),
            remaining_deadline_seconds=0,
        )
        self.assertIsNone(result.destination)
        self.assertEqual(result.rejected, (("local", "deadline_exhaustion"),))


if __name__ == "__main__":
    unittest.main()
