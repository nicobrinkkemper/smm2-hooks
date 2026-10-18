"""
Screenshot of a native (Linux) Eden window on X11, for eden_screenshot.

The window is the top-level one whose _NET_WM_PID is an Eden process; its
rectangle is cut out of a grab of the root window (Pillow's XCB grabber), so
only Eden's window is returned, never the rest of the desktop. Grabbing the
root rather than the window itself keeps Vulkan-presented content, which a
window-level XGetImage can return black.

libX11 comes from ctypes.util.find_library("X11"), else EDEN_LIBX11 (a path to
libX11.so.6, for a machine without system X libraries).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import io
import os

_ulong = ctypes.c_ulong
Window = _ulong
Atom = _ulong


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
        ("root", Window), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", _ulong),
        ("backing_pixel", _ulong), ("save_under", ctypes.c_int), ("colormap", _ulong),
        ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


IS_VIEWABLE = 2


def _libx11():
    path = ctypes.util.find_library("X11")
    if not path:
        path = os.environ.get("EDEN_LIBX11")
        if not path:
            raise RuntimeError("no libX11 (set EDEN_LIBX11 to a libX11.so.6)")
        # Off the loader's path, its own dependencies are not found either:
        # load the ones that sit beside it first, globally.
        for dep in ("libXau.so.6", "libXdmcp.so.6", "libxcb.so.1"):
            q = os.path.join(os.path.dirname(path), dep)
            if os.path.exists(q):
                ctypes.CDLL(q, mode=ctypes.RTLD_GLOBAL)
    x = ctypes.CDLL(path)
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = Window
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = Atom
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XQueryTree.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(Window), ctypes.POINTER(Window),
                             ctypes.POINTER(ctypes.POINTER(Window)), ctypes.POINTER(ctypes.c_uint)]
    x.XGetWindowProperty.argtypes = [ctypes.c_void_p, Window, Atom, ctypes.c_long, ctypes.c_long, ctypes.c_int,
                                     Atom, ctypes.POINTER(Atom), ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(_ulong), ctypes.POINTER(_ulong),
                                     ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
    x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(XWindowAttributes)]
    x.XTranslateCoordinates.argtypes = [ctypes.c_void_p, Window, Window, ctypes.c_int, ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(Window)]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return x


def _wm_pid(x, dpy, win, atom) -> int | None:
    actual, fmt, n, after = Atom(), ctypes.c_int(), _ulong(), _ulong()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    XA_CARDINAL = 6
    if x.XGetWindowProperty(dpy, win, atom, 0, 1, 0, XA_CARDINAL, ctypes.byref(actual), ctypes.byref(fmt),
                            ctypes.byref(n), ctypes.byref(after), ctypes.byref(data)) != 0 or not data:
        return None
    try:
        # format-32 properties come back as C longs
        return ctypes.cast(data, ctypes.POINTER(ctypes.c_long))[0] if n.value else None
    finally:
        x.XFree(data)


def window_bbox(pids: list[int], display: str | None = None) -> tuple[int, int, int, int]:
    """Root-relative (left, top, right, bottom) of the largest viewable window of `pids`."""
    x = _libx11()
    dpy = x.XOpenDisplay((display or os.environ.get("DISPLAY", "")).encode() or None)
    if not dpy:
        raise RuntimeError(f"cannot open X display {display or os.environ.get('DISPLAY')!r}")
    try:
        root = x.XDefaultRootWindow(dpy)
        atom = x.XInternAtom(dpy, b"_NET_WM_PID", 1)
        best = None
        stack = [root]
        while stack:
            w = stack.pop()
            r, parent = Window(), Window()
            kids = ctypes.POINTER(Window)()
            nk = ctypes.c_uint()
            if x.XQueryTree(dpy, w, ctypes.byref(r), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(nk)):
                stack.extend(kids[i] for i in range(nk.value))
                if kids:
                    x.XFree(kids)
            if w == root or not atom or _wm_pid(x, dpy, w, atom) not in pids:
                continue
            a = XWindowAttributes()
            if not x.XGetWindowAttributes(dpy, w, ctypes.byref(a)) or a.map_state != IS_VIEWABLE:
                continue
            rx, ry, child = ctypes.c_int(), ctypes.c_int(), Window()
            x.XTranslateCoordinates(dpy, w, root, 0, 0, ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(child))
            box = (rx.value, ry.value, rx.value + a.width, ry.value + a.height)
            if best is None or a.width * a.height > (best[2] - best[0]) * (best[3] - best[1]):
                best = box
        if best is None:
            raise RuntimeError(f"no viewable window with _NET_WM_PID in {pids}")
        return best
    finally:
        x.XCloseDisplay(dpy)


def grab_window_png(pids: list[int], display: str | None = None) -> bytes:
    if not pids:
        raise RuntimeError("Eden is not running")
    from PIL import ImageGrab  # noqa: WPS433

    display = display or os.environ.get("DISPLAY")
    if not display:
        raise RuntimeError("DISPLAY is not set")
    img = ImageGrab.grab(bbox=window_bbox(pids, display), xdisplay=display)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
