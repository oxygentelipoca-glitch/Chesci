import unittest
from app.chemistry.constraints import evaluate_constraints


class ConstraintTests(unittest.TestCase):
    def statuses(self, item, **filters):
        return {c["key"]: c["status"] for c in evaluate_constraints(item, filters)["checks"]}

    def test_defaults_are_not_evidence(self):
        self.assertEqual(set(self.statuses({}, min_yield=0, max_steps=1, solvent="without",
                                          workup="without", catalyst_name="Cu").values()), {"unknown"})

    def test_ranges_and_partial_conditions(self):
        item = {"yield_": "60–80%", "steps": 2, "conditions_summary": [
            {"temperature": "-20 to -5 °C", "time": "20–30 min"}, {"temperature": "reflux"}]}
        self.assertEqual(self.statuses(item, min_yield=70, max_temperature=0, max_time_hours=1),
                         {"min_yield":"unknown", "max_temperature":"unknown", "max_time_hours":"unknown"})
        self.assertEqual(self.statuses(item, max_temperature=-10, max_time_hours=0.25),
                         {"max_temperature":"conflict", "max_time_hours":"conflict"})
        item["conditions_summary"][1] = {"temperature": "-8 °C", "time": "15 min"}
        self.assertEqual(set(self.statuses(item, min_yield=60, max_temperature=-5, max_time_hours=.5).values()), {"met"})

    def test_recorded_absence_differs_from_silence(self):
        item = {"conditions_summary":[{"solvents":"solvent-free", "other":"atmosphere: air; pH: 7"}]}
        self.assertEqual(self.statuses(item, solvent="without", solvent_name="water", workup="with"),
                         {"solvent":"met", "solvent_name":"conflict", "workup":"unknown"})

    def test_unrecorded_step_cannot_confirm_route_limit(self):
        item = {"steps":2, "conditions_summary":[{"step":"1", "temperature":"40 °C", "solvents":"无"}]}
        self.assertEqual(set(self.statuses(item, max_temperature=50, solvent="without").values()), {"unknown"})

    def test_non_numeric_text_and_wrong_units(self):
        item = {"conditions_summary":[{"temperature":"70 °F", "time":"overnight"}], "yield_":"trace"}
        self.assertEqual(set(self.statuses(item, min_yield=5, max_temperature=80, max_time_hours=48).values()), {"unknown"})
