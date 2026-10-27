"""Shared desktop RGB capture for game discovery and region editing."""

import numpy as np


def capture_desktop_rgb():
    import mss

    with mss.mss() as source:
        monitor = source.monitors[0]
        rgb = np.asarray(source.grab(monitor))[:, :, :3][:, :, ::-1].copy()
    return rgb, (monitor["left"], monitor["top"])
