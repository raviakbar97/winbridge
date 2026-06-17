"""Windows master volume helpers for Winbridge.

Uses pycaw when available. Functions raise a clear RuntimeError when the
Windows audio stack/dependency is unavailable.
"""

from __future__ import annotations

from typing import Dict


class _ComContext:
    def __enter__(self):
        try:
            from comtypes import CoInitialize
            CoInitialize()
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            from comtypes import CoUninitialize
            CoUninitialize()
        except Exception:
            pass
        return False


def _endpoint_volume():
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except Exception as exc:  # pragma: no cover - dependency not present on Linux CI
        raise RuntimeError("volume control requires pycaw and comtypes on Windows") from exc

    device = AudioUtilities.GetSpeakers()
    if hasattr(device, "Activate"):
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    endpoint = getattr(device, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint
    raw_device = getattr(device, "_dev", None)
    if raw_device is not None and hasattr(raw_device, "Activate"):
        interface = raw_device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    raise RuntimeError("unsupported pycaw AudioDevice object; cannot access endpoint volume")


def _normalize_level(level) -> float:
    try:
        value = float(level)
    except Exception as exc:
        raise ValueError("level must be a number from 0 to 100") from exc
    if value < 0 or value > 100:
        raise ValueError("level must be between 0 and 100")
    return value


def volume_get() -> Dict[str, object]:
    with _ComContext():
        endpoint = _endpoint_volume()
        scalar = float(endpoint.GetMasterVolumeLevelScalar())
        muted = bool(endpoint.GetMute())
        return {"level": round(scalar * 100), "muted": muted}


def volume_set(level) -> Dict[str, object]:
    value = _normalize_level(level)
    with _ComContext():
        endpoint = _endpoint_volume()
        endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)
    return volume_get()


def volume_mute(muted: bool = True) -> Dict[str, object]:
    with _ComContext():
        endpoint = _endpoint_volume()
        endpoint.SetMute(1 if muted else 0, None)
    return volume_get()


def volume_toggle_mute() -> Dict[str, object]:
    with _ComContext():
        endpoint = _endpoint_volume()
        muted = bool(endpoint.GetMute())
        endpoint.SetMute(0 if muted else 1, None)
    return volume_get()
