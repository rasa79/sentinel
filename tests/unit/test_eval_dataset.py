"""Schema-validation test for the eval dataset (PLAN.md Task 7.1)."""

from __future__ import annotations

from sentinel.evals.dataset import load_dataset

_ALL_CATEGORIES = {"error_burst", "latency_spike", "memory_leak", "bad_deploy"}
_ALL_ACTIONS = {"restart_service", "rollback_deploy", "scale_replicas", "no_action"}
_ALL_SERVICES = {"orders", "payments", "inventory"}


def test_dataset_has_at_least_8_valid_entries() -> None:
    entries = load_dataset()
    assert len(entries) >= 8


def test_dataset_uses_unique_ids() -> None:
    entries = load_dataset()
    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids))


def test_dataset_covers_all_chaos_types() -> None:
    categories = {e.known_cause.category for e in load_dataset()}
    assert _ALL_CATEGORIES <= categories


def test_dataset_action_and_service_are_known() -> None:
    for e in load_dataset():
        assert e.expected_action in _ALL_ACTIONS, f"{e.id}: bad action {e.expected_action!r}"
        assert e.alert.service in _ALL_SERVICES, f"{e.id}: bad service {e.alert.service!r}"
        assert e.known_cause.affected_service == e.alert.service, f"{e.id}: service mismatch"


def test_dataset_rollback_entries_have_previous_good_version() -> None:
    # rollback_deploy needs a previous good deploy in the canned deploys (the remediate guard).
    for e in load_dataset():
        if e.expected_action == "rollback_deploy":
            good = [
                d
                for d in e.tools.deploys
                if d.event != "bad_deploy" and d.service == e.alert.service
            ]
            assert good, f"{e.id}: rollback_deploy needs a previous good deploy"
