from pathlib import Path

from app.services.deep_queue import DeepQueueStore


def test_deep_queue_persists_progress_and_resumability(tmp_path: Path):
    store = DeepQueueStore(tmp_path)
    payload = store.create(
        run_id="run-1",
        source_id="source-1",
        record_ids=["a", "b", "c"],
        scope="incomplete",
        total_files=10,
    )
    assert payload["total"] == 3
    assert store.info("run-1")["queue_remaining"] == 3

    store.mark_complete("run-1", "a", "succeeded")
    store.mark_complete("run-1", "b", "deferred")
    loaded = store.load("run-1")
    assert loaded is not None
    assert loaded["pending"] == ["c"]
    assert loaded["completed"] == 2
    assert loaded["succeeded"] == 1
    assert loaded["deferred"] == 1
    assert store.info("run-1")["resumable"] is True

    store.mark_complete("run-1", "c", "failed")
    assert store.info("run-1")["resumable"] is False
    store.remove("run-1")
    assert store.load("run-1") is None


def test_deep_queue_keep_only_removes_deleted_records(tmp_path: Path):
    store = DeepQueueStore(tmp_path)
    store.create(
        run_id="run-2",
        source_id="source-1",
        record_ids=["a", "b", "c"],
        scope="all",
        total_files=3,
    )
    store.keep_only("run-2", ["b"])
    assert store.load("run-2")["pending"] == ["b"]


def test_deferred_attempt_can_remain_resumable(tmp_path: Path):
    store = DeepQueueStore(tmp_path)
    store.create(
        run_id="run-3",
        source_id="source-1",
        record_ids=["a", "b"],
        scope="incomplete",
        total_files=2,
    )
    payload = store.mark_complete("run-3", "a", "deferred", keep_pending=True)
    assert payload is not None
    assert payload["pending"] == ["a", "b"]
    assert payload["deferred"] == 1
    assert store.info("run-3")["queue_remaining"] == 2
