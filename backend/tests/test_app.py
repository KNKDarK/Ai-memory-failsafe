import pytest

from backend.app import lesson_for, record_failure


def test_record_failure_stores_task_and_cause():
    record = record_failure("deploy", "missing env var")
    assert record["task"] == "deploy"
    assert record["cause"] == "missing env var"
    assert record["lesson"] is None


def test_record_failure_rejects_blank_input():
    with pytest.raises(ValueError):
        record_failure("  ", "cause")
    with pytest.raises(ValueError):
        record_failure("task", "")


def test_lesson_for_attaches_lesson():
    record = record_failure("deploy", "missing env var")
    updated = lesson_for(record, "validate env before deploy")
    assert updated["lesson"] == "validate env before deploy"
    assert record["lesson"] is None
