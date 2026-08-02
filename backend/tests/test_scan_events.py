from pathlib import Path

from app.services.scan_events import ScanEventStore


def test_scan_event_store_supports_incremental_cursor_and_tail(tmp_path: Path):
    store = ScanEventStore(tmp_path / "events")
    run_id = "11111111-1111-1111-1111-111111111111"

    store.append(run_id, "info", "discovery", "Found first movie", count=1)
    first = store.read(run_id, cursor=0, limit=20)
    assert [event["message"] for event in first["events"]] == ["Found first movie"]
    assert first["next_cursor"] > 0

    store.append(run_id, "success", "analyze", "Analyzed second movie")
    second = store.read(run_id, cursor=first["next_cursor"], limit=20)
    assert [event["message"] for event in second["events"]] == ["Analyzed second movie"]

    for index in range(5):
        store.append(run_id, "debug", "cache", f"Cache hit {index}")
    tail = store.read(run_id, cursor=0, limit=3, tail=True)
    assert [event["message"] for event in tail["events"]] == ["Cache hit 2", "Cache hit 3", "Cache hit 4"]
    assert tail["has_more"] is False


def test_scan_event_store_clear_all(tmp_path: Path):
    directory = tmp_path / "events"
    store = ScanEventStore(directory)
    store.append("run-1", "info", "start", "Started")
    store.append("run-2", "info", "start", "Started")

    files, total_bytes = store.clear_all()

    assert files == 2
    assert total_bytes > 0
    assert list(directory.iterdir()) == []
