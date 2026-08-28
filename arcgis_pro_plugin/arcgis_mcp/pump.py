# -*- coding: utf-8 -*-
"""Run commands on ArcGIS Pro's main thread without holding it.

arcpy.mp.ArcGISProject("CURRENT") -- and so everything that touches the live
session -- only resolves on ArcGIS Pro's main thread, while the socket server
necessarily runs on a background thread. The two are joined up like this:

    socket thread                 ArcGIS Pro's own message loop (main thread)
    ------------                  -------------------------------------------
    read JSON
    submit(job)  ---- queue ---->
    PostMessage(hwnd)  --------->  dispatches to _wndproc
    wait(event)                    _drain(): run the handler  <- "CURRENT" works
                 <--- event -----  set the result and return

The important part is what this does NOT do: it never holds the main thread.
Two earlier designs did, and both froze ArcGIS Pro -- a sleep loop calling
PumpWaitingMessages(), and a full GetMessage/DispatchMessage loop. Neither
worked, because ArcGIS Pro disables the map view for as long as a Python
window command is still executing, no matter how faithfully messages are
pumped. The fix is to stop occupying the Python window at all: create a
message-only window on the main thread, let the cell finish, and let Pro's own
message loop call us back whenever there is work.
"""

import queue
import threading
import time

DEFAULT_JOB_TIMEOUT = 600.0
MAX_JOBS_PER_CYCLE = 50
WINDOW_CLASS = "ArcGISProMCPDispatcher"
TIMER_ID = 1
# ArcGIS Pro only wakes its message loop about every 30s when it is idle,
# so a posted message alone can sit unprocessed for that long. A timer on
# our own window forces the loop to run at this interval instead.
TIMER_INTERVAL_MS = 100
# WM_USER + "MC".
WM_ARCGIS_MCP = 0x0400 + 0x4D43

_QUEUE = queue.Queue()
_STATE = {
    "running": False,
    "mode": None,
    "thread_name": None,
    "hwnd": None,
    "started_at": None,
    "jobs_run": 0,
    "stop_requested": False,
    "last_error": None,
    "timer": None,
}
# The window procedure and class atom must outlive this call or Windows will
# call into freed memory.
_WNDPROC = None
_CLASS_ATOM = None


class Job(object):
    __slots__ = ("handler", "params", "event", "result", "error")

    def __init__(self, handler, params):
        self.handler = handler
        self.params = params
        self.event = threading.Event()
        self.result = None
        self.error = None


class PumpNotRunning(Exception):
    """Raised when a command needs the main thread but no dispatcher is up."""


def is_running():
    return bool(_STATE["running"])


def status():
    data = dict(_STATE)
    data["queued_jobs"] = _QUEUE.qsize()
    if data["started_at"]:
        data["uptime_seconds"] = round(time.time() - data["started_at"], 1)
    return data


# --- job plumbing ------------------------------------------------------------

def _run_job(job):
    try:
        job.result = job.handler(job.params)
    except Exception as exc:  # noqa: BLE001 -- reported back to the caller
        job.error = exc
    finally:
        _STATE["jobs_run"] += 1
        job.event.set()


def _drain():
    handled = 0
    while handled < MAX_JOBS_PER_CYCLE:
        try:
            job = _QUEUE.get_nowait()
        except queue.Empty:
            break
        _run_job(job)
        handled += 1
    return handled


def _drain_pending():
    """Fail queued jobs so their socket threads are not left waiting."""
    while True:
        try:
            job = _QUEUE.get_nowait()
        except queue.Empty:
            return
        job.error = PumpNotRunning(
            "The main-thread dispatcher stopped before this command could run.")
        job.event.set()


def submit(handler, params, timeout=DEFAULT_JOB_TIMEOUT):
    """Run a handler on ArcGIS Pro's main thread and return its result."""
    if not _STATE["running"]:
        raise PumpNotRunning(
            "The ArcGIS Pro main-thread dispatcher is not running, so the open "
            "project cannot be reached. In the ArcGIS Pro Python window run:\n"
            "    import mcp_bridge; mcp_bridge.start_pump()"
        )
    job = Job(handler, params)
    _QUEUE.put(job)
    _wake()
    if not job.event.wait(timeout):
        raise TimeoutError(
            "ArcGIS Pro did not finish this command within {:.0f}s. It may be "
            "busy, or waiting on a dialog.".format(timeout)
        )
    if job.error is not None:
        raise job.error
    return job.result


def _wake():
    hwnd = _STATE.get("hwnd")
    if not hwnd:
        return
    try:
        import win32gui
        win32gui.PostMessage(hwnd, WM_ARCGIS_MCP, 0, 0)
    except Exception as exc:  # noqa: BLE001
        _STATE["last_error"] = "could not notify ArcGIS Pro: {}".format(exc)


# --- the message-only window -------------------------------------------------

def _wndproc(hwnd, message, wparam, lparam):
    """Called by ArcGIS Pro's own message loop, on the main thread.

    It must be quick and must never raise: an exception here would propagate
    into Pro's message loop.
    """
    import win32con
    import win32gui
    try:
        if message in (WM_ARCGIS_MCP, win32con.WM_TIMER):
            _drain()
            return 0
        if message == win32con.WM_DESTROY:
            _kill_timer(hwnd)
            _STATE["running"] = False
            _STATE["hwnd"] = None
            _drain_pending()
            return 0
    except Exception as exc:  # noqa: BLE001
        _STATE["last_error"] = "{}: {}".format(type(exc).__name__, exc)
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


def _kill_timer(hwnd):
    try:
        import win32gui
        win32gui.KillTimer(hwnd, TIMER_ID)
    except Exception:
        pass


def _set_timer(hwnd):
    """Windows has no KillTimer/SetTimer in win32gui on every build, so fall
    back to user32 through ctypes."""
    try:
        import win32gui
        win32gui.SetTimer(hwnd, TIMER_ID, TIMER_INTERVAL_MS, None)
        return "win32gui"
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetTimer(
            ctypes.c_void_p(hwnd), TIMER_ID, TIMER_INTERVAL_MS, None)
        return "ctypes"
    except Exception as exc:
        _STATE["last_error"] = "could not start the timer: {}".format(exc)
        return None


def start():
    """Install the dispatcher and return immediately.

    Must be called from ArcGIS Pro's main thread (the Python window). The cell
    finishes straight away -- ArcGIS Pro is never blocked.
    """
    global _WNDPROC, _CLASS_ATOM

    if _STATE["running"]:
        return "The ArcGIS Pro MCP dispatcher is already running (hwnd {}).".format(
            _STATE["hwnd"])
    current = threading.current_thread()
    if current is not threading.main_thread():
        return (
            "start_pump() must be called from ArcGIS Pro's main thread (the "
            "Python window). It was called from {!r}, where "
            'ArcGISProject("CURRENT") does not resolve.'.format(current.name)
        )

    import win32con
    import win32gui

    _WNDPROC = _wndproc
    if _CLASS_ATOM is None:
        window_class = win32gui.WNDCLASS()
        window_class.lpszClassName = WINDOW_CLASS
        window_class.lpfnWndProc = _WNDPROC
        try:
            _CLASS_ATOM = win32gui.RegisterClass(window_class)
        except Exception as exc:  # already registered by an earlier session
            _STATE["last_error"] = "RegisterClass: {}".format(exc)
            _CLASS_ATOM = WINDOW_CLASS

    hwnd = win32gui.CreateWindowEx(
        0, WINDOW_CLASS, "ArcGIS Pro MCP", 0, 0, 0, 0, 0,
        win32con.HWND_MESSAGE, 0, 0, None,
    )
    timer = _set_timer(hwnd)
    _STATE.update({
        "running": True, "stop_requested": False, "mode": "message-window",
        "thread_name": current.name, "hwnd": hwnd, "started_at": time.time(),
        "jobs_run": 0, "timer": timer,
    })
    _drain()  # anything that queued up while we were starting
    return ("ArcGIS Pro MCP dispatcher installed (hwnd {}, timer via {}). "
            "ArcGIS Pro is not blocked -- this cell is finished. Stop it with "
            "the stop_pump tool or 'python -m arcgis_pro_mcp stop-pump'."
            .format(hwnd, timer or "none -- commands may be slow"))


def stop():
    """Tear the dispatcher down. Safe to call from any thread."""
    if not _STATE["running"]:
        return False
    if _STATE.get("mode") == "blocking":
        _STATE["stop_requested"] = True
        return True
    hwnd = _STATE.get("hwnd")
    _STATE["stop_requested"] = True
    if hwnd:
        try:
            import win32con
            import win32gui
            # WM_CLOSE is handled by DefWindowProc, which destroys the window
            # on its owning thread -- the only thread allowed to do that.
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception as exc:  # noqa: BLE001
            _STATE["last_error"] = "could not close the dispatcher: {}".format(exc)
    # Mark it down immediately rather than waiting for WM_DESTROY: if the
    # window is unreachable the caller would otherwise be stuck with a
    # dispatcher it can never remove.
    _STATE["running"] = False
    _STATE["hwnd"] = None
    _drain_pending()
    return True


# --- blocking fallback, used by the tests ------------------------------------

def run_blocking(interval=0.02, max_seconds=None, verbose=True):
    """Drain jobs from a loop on the calling thread until stopped.

    This holds the thread, so it must NOT be used inside ArcGIS Pro -- it is
    here for the unit tests and for hosts with no Windows message loop.
    """
    if _STATE["running"]:
        return "A dispatcher is already running"
    _STATE.update({
        "running": True, "stop_requested": False, "mode": "blocking",
        "thread_name": threading.current_thread().name,
        "started_at": time.time(), "jobs_run": 0, "hwnd": None,
        "last_error": None,
    })
    deadline = time.time() + max_seconds if max_seconds else None
    try:
        while not _STATE["stop_requested"]:
            handled = _drain()
            if deadline and time.time() > deadline:
                break
            if handled == 0:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        _STATE["running"] = False
        _STATE["stop_requested"] = False
        _drain_pending()
    message = "Dispatcher stopped after {} commands.".format(_STATE["jobs_run"])
    if verbose:
        print(message)
    return message


