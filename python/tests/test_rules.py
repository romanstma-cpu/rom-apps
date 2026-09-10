"""Entry rules: gate evaluation and untrusted-input sanitization.

Rules gate every entry — a disabled field or bad number must fail closed
(not pass). sanitize_rules must reject anything outside the allowlist,
including non-numeric values and unknown operators.
"""
from __future__ import annotations

import pytest

from rules import evaluate_rules, sanitize_rules


ALLOWED = {"confidence", "edge_pts", "price", "liquidity"}


class TestEvaluateRules:
    def test_empty_rules_fail_closed(self):
        ok, why = evaluate_rules({"confidence": 80}, [])
        assert ok is False
        assert "no entry rules" in why

    def test_all_rules_pass(self):
        rules = [
            {"field": "confidence", "op": ">=", "value": 60},
            {"field": "edge_pts", "op": ">=", "value": 5},
        ]
        ok, _ = evaluate_rules({"confidence": 70, "edge_pts": 7}, rules)
        assert ok is True

    def test_failing_rule_reports_why(self):
        rules = [{"field": "confidence", "op": ">=", "value": 60}]
        ok, why = evaluate_rules({"confidence": 40}, rules)
        assert ok is False
        assert "confidence" in why
        assert "40" in why or "60" in why

    def test_missing_field_fails_closed(self):
        rules = [{"field": "liquidity", "op": ">=", "value": 1000}]
        ok, why = evaluate_rules({"confidence": 90}, rules)
        assert ok is False
        assert "unavailable" in why

    def test_non_numeric_value_fails_closed(self):
        rules = [{"field": "confidence", "op": ">=", "value": "high"}]
        ok, why = evaluate_rules({"confidence": 90}, rules)
        assert ok is False
        assert "not numeric" in why

    def test_non_numeric_actual_fails_closed(self):
        rules = [{"field": "confidence", "op": ">=", "value": 60}]
        ok, why = evaluate_rules({"confidence": "abc"}, rules)
        assert ok is False
        assert "not numeric" in why

    def test_unknown_operator_skipped_not_fatal(self):
        # Unknown op is skipped; remaining valid rules still evaluated.
        rules = [
            {"field": "confidence", "op": "=>", "value": 60},  # bad
            {"field": "price", "op": "<", "value": 0.9},        # good
        ]
        ok, _ = evaluate_rules({"confidence": 99, "price": 0.5}, rules)
        assert ok is True

    def test_boundary_operators(self):
        rules = [
            {"field": "confidence", "op": ">", "value": 60},
        ]
        assert evaluate_rules({"confidence": 60}, rules)[0] is False
        assert evaluate_rules({"confidence": 60.001}, rules)[0] is True

    def test_unknown_field_fails_closed(self):
        """A rule on a field the engine never provides cannot silently pass."""
        rules = [{"field": "not_a_real_field", "op": ">=", "value": 1}]
        ok, why = evaluate_rules({"confidence": 90}, rules)
        assert ok is False
        assert "unavailable" in why

    def test_unknown_op_skipped_but_known_field_passes(self):
        rules = [
            {"field": "confidence", "op": "=>", "value": 60},  # unknown op, skipped
            {"field": "confidence", "op": ">=", "value": 10},  # valid
        ]
        assert evaluate_rules({"confidence": 80}, rules)[0] is True

    def test_division_precision_edge(self):
        rules = [{"field": "confidence", "op": ">=", "value": 0.1}]
        assert evaluate_rules({"confidence": 0.10000001}, rules)[0] is True


class TestSanitizeRules:
    def test_non_list_returns_empty(self):
        assert sanitize_rules("nope", ALLOWED) == []
        assert sanitize_rules(None, ALLOWED) == []
        assert sanitize_rules({"field": "confidence"}, ALLOWED) == []

    def test_filters_unknown_fields(self):
        raw = [
            {"field": "confidence", "op": ">=", "value": 60},
            {"field": "hack", "op": ">=", "value": 1},
        ]
        clean = sanitize_rules(raw, ALLOWED)
        assert clean == [{"field": "confidence", "op": ">=", "value": 60.0}]

    def test_filters_unknown_ops(self):
        raw = [{"field": "confidence", "op": "xor", "value": 1}]
        assert sanitize_rules(raw, ALLOWED) == []

    def test_coerces_value_to_float(self):
        clean = sanitize_rules([{"field": "confidence", "op": ">=", "value": "42.5"}], ALLOWED)
        assert clean == [{"field": "confidence", "op": ">=", "value": 42.5}]

    def test_drops_non_numeric_value(self):
        raw = [{"field": "confidence", "op": ">=", "value": "NaN"}]
        assert sanitize_rules(raw, ALLOWED) == []

    def test_drops_non_dict_entries(self):
        raw = [{"field": "confidence", "op": ">=", "value": 1}, "junk", 42, None]
        clean = sanitize_rules(raw, ALLOWED)
        assert clean == [{"field": "confidence", "op": ">=", "value": 1.0}]

    def test_limit_applied(self):
        raw = [{"field": "confidence", "op": ">=", "value": i} for i in range(50)]
        clean = sanitize_rules(raw, ALLOWED)
        assert len(clean) == 30

    def test_deduplication_of_bad_values(self):
        raw = [
            {"field": "confidence", "op": ">=", "value": 60},
            {"field": "confidence", "op": ">=", "value": 60},  # dup allowed
            {"field": "confidence", "op": ">=", "value": ""},
        ]
        clean = sanitize_rules(raw, ALLOWED)
        # No dedup contract; both valid entries kept
        assert len(clean) == 2