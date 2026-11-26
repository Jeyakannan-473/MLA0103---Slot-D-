"""Pure rule-engine tests (no database needed)."""
import unittest

from app.expert_system.engine import (MISSING, NEEDS_INFO, NOT_ELIGIBLE, NOT_SATISFIED, POTENTIALLY_ELIGIBLE,
                                      SATISFIED, evaluate_condition, evaluate_rule, format_inr)

INCOME = {"attribute": "annual_income", "operator": "lte", "value": 120000, "label": "Income limit"}
GENDER = {"attribute": "gender", "operator": "eq", "value": "female", "label": "Gender"}


class EngineTests(unittest.TestCase):
    def test_eligible(self):
        out = evaluate_rule([INCOME, GENDER], {"annual_income": 90000, "gender": "female"}, rule_version=3)
        self.assertEqual(out.result, POTENTIALLY_ELIGIBLE)
        self.assertEqual(out.rule_version, 3)
        self.assertEqual(len(out.satisfied), 2)

    def test_not_eligible_explains_reason(self):
        out = evaluate_rule([INCOME, GENDER], {"annual_income": 250000, "gender": "female"})
        self.assertEqual(out.result, NOT_ELIGIBLE)
        self.assertEqual([c.label for c in out.not_satisfied], ["Income limit"])
        self.assertIn("\u20b92,50,000", out.not_satisfied[0].explanation)

    def test_missing_information(self):
        out = evaluate_rule([INCOME, GENDER], {"gender": "female"})
        self.assertEqual(out.result, NEEDS_INFO)
        self.assertEqual(out.missing[0].attribute, "annual_income")

    def test_unmet_beats_missing(self):
        out = evaluate_rule([INCOME, GENDER], {"gender": "male"})
        self.assertEqual(out.result, NOT_ELIGIBLE)

    def test_unknown_condition_is_never_guessed(self):
        cond = {"attribute": "annual_income", "operator": "unknown", "value": None, "label": "Income"}
        out = evaluate_rule([cond], {"annual_income": 1})
        self.assertEqual(out.result, NEEDS_INFO)
        self.assertEqual(out.conditions[0].status, MISSING)

    def test_no_conditions(self):
        self.assertEqual(evaluate_rule([], {"age": 20}).result, NEEDS_INFO)

    def test_operators(self):
        self.assertEqual(evaluate_condition({"attribute": "age", "operator": "between", "value": [18, 25]}, {"age": 20}).status, SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "age", "operator": "between", "value": [18, 25]}, {"age": 30}).status, NOT_SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "age", "operator": "gte", "value": 18}, {"age": 18}).status, SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "district", "operator": "in", "value": ["Chennai", "Madurai"]}, {"district": "madurai"}).status, SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "district", "operator": "not_in", "value": ["Chennai"]}, {"district": "Chennai"}).status, NOT_SATISFIED)

    def test_boolean_and_ordinal(self):
        self.assertEqual(evaluate_condition({"attribute": "is_student", "operator": "eq", "value": True}, {"is_student": True}).status, SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "is_student", "operator": "eq", "value": True}, {"is_student": False}).status, NOT_SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "education_level", "operator": "gte", "value": "12th"}, {"education_level": "undergraduate"}).status, SATISFIED)
        self.assertEqual(evaluate_condition({"attribute": "education_level", "operator": "gte", "value": "12th"}, {"education_level": "8th"}).status, NOT_SATISFIED)

    def test_false_boolean_is_not_missing(self):
        # "No" is an answer, not missing information
        c = evaluate_condition({"attribute": "has_disability", "operator": "eq", "value": True}, {"has_disability": False})
        self.assertEqual(c.status, NOT_SATISFIED)

    def test_zero_income_is_valid(self):
        self.assertEqual(evaluate_condition(INCOME, {"annual_income": 0}).status, SATISFIED)

    def test_indian_number_format(self):
        self.assertEqual(format_inr(120000), "1,20,000")
        self.assertEqual(format_inr(1234567), "12,34,567")


if __name__ == "__main__":
    unittest.main()
