"""Unit-test the main-thread pump without ArcGIS Pro.

pump.py deliberately imports nothing from arcpy, so the queue/handoff logic
can be exercised anywhere. The test mirrors the real arrangement: the pump
loop owns the main thread while worker threads submit jobs to it.
"""

import importlib.util
import pathlib
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUMP_PATH = ROOT / "arcgis_pro_plugin" / "arcgis_mcp" / "pump.py"

spec = importlib.util.spec_from_file_location("_pump_under_test", PUMP_PATH)
pump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pump)


def test_submit_without_pump_is_refused():
    try:
        pump.submit(lambda params: "nope", {})
    except pump.PumpNotRunning as exc:
        assert "start_pump" in str(exc), exc
        return
    raise AssertionError("submit() must refuse when no pump is running")


def test_jobs_run_on_the_pump_thread():
    results = {}
    errors = []
    pump_thread_name = threading.current_thread().name

    def handler(params):
        # The handler must execute on the thread running the pump loop --
        # that is the whole point of the mechanism.
        assert threading.current_thread().name == pump_thread_name
        return {"echo": params["value"] * 2}

    def failing(params):
        raise ValueError("handler blew up")

    def worker():
        # Give run() a moment to mark itself running.
        for _ in range(200):
            if pump.is_running():
                break
            time.sleep(0.01)
        try:
            results["ok"] = pump.submit(handler, {"value": 21})
            try:
                pump.submit(failing, {})
                errors.append("failing handler did not propagate")
            except ValueError as exc:
                results["error"] = str(exc)
            results["status"] = pump.status()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
        finally:
            pump.stop()

    threading.Thread(target=worker, name="fake-socket-thread", daemon=True).start()
    # pump_messages=False: there is no ArcGIS Pro message loop to pump here.
    pump.run_blocking(max_seconds=15, verbose=False)

    assert not errors, errors
    assert results["ok"] == {"echo": 42}, results
    assert results["error"] == "handler blew up", results
    assert results["status"]["running"] is True, results["status"]
    assert results["status"]["mode"] == "blocking", results["status"]
    assert results["status"]["jobs_run"] >= 1, results["status"]
    assert not pump.is_running(), "pump should have stopped"


def test_stop_still_finishes_queued_work():
    """Asking the pump to stop drains what is already queued rather than
    dropping it, so a burst of commands is not half-answered."""
    started = threading.Event()
    outcome = {}

    def worker(value):
        try:
            outcome[value] = ("ok", pump.submit(lambda p: value, {}, timeout=10))
        except Exception as exc:  # noqa: BLE001
            outcome[value] = ("error", str(exc))

    def driver():
        for _ in range(200):
            if pump.is_running():
                break
            time.sleep(0.01)
        for value in ("a", "b", "c"):
            threading.Thread(target=worker, args=(value,), daemon=True).start()
        started.set()
        time.sleep(0.15)
        pump.stop()

    threading.Thread(target=driver, daemon=True).start()
    pump.run_blocking(max_seconds=15, verbose=False)
    started.wait(5)
    time.sleep(0.3)

    assert outcome == {"a": ("ok", "a"), "b": ("ok", "b"), "c": ("ok", "c")}, outcome


def test_orphaned_jobs_are_failed_not_left_hanging():
    """A job that reaches the queue just as the pump exits must be failed, or
    its socket thread would block until the client timeout."""
    assert not pump.is_running()
    job = pump.Job(lambda params: "never runs", {})
    pump._QUEUE.put(job)

    pump._drain_pending()

    assert job.event.is_set(), "orphaned job was left waiting"
    assert isinstance(job.error, pump.PumpNotRunning), job.error
    assert "stopped" in str(job.error), job.error


def test_start_refuses_a_non_main_thread():
    """The dispatcher window has to live on the thread that owns the project."""
    result = {}

    def off_main():
        result["message"] = pump.start()

    thread = threading.Thread(target=off_main, name="not-main")
    thread.start()
    thread.join(5)
    assert "main thread" in result["message"], result
    assert not pump.is_running()


if __name__ == "__main__":
    test_submit_without_pump_is_refused()
    print("[ok] submit without a pump is refused")
    test_jobs_run_on_the_pump_thread()
    print("[ok] jobs run on the pump thread, results and errors both return")
    test_stop_still_finishes_queued_work()
    print("[ok] stopping drains queued work instead of dropping it")
    test_orphaned_jobs_are_failed_not_left_hanging()
    print("[ok] orphaned jobs are failed, never left hanging")
    test_start_refuses_a_non_main_thread()
    print("[ok] start() refuses to install off the main thread")
    print("\nAll pump checks passed.")
