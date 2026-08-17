from __future__ import annotations

import datetime as dt

from .reserve_status import reserve_technical_status_label


def format_reserve_date(value) -> str:
    if isinstance(value, (int, float)):
        try:
            value = dt.datetime.fromtimestamp(float(value))
        except (OSError, OverflowError, ValueError):
            return "-"
    if isinstance(value, dt.datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return "-"


def reserve_date_sort_value(value) -> float:
    if isinstance(value, dt.datetime):
        try:
            return float(value.timestamp())
        except (OSError, OverflowError, ValueError):
            return -1.0
    if isinstance(value, (int, float)):
        return float(value)
    return -1.0


def format_reserve_duration(seconds, *, compact: bool = False) -> str:
    try:
        value = max(0.0, float(seconds or 0.0))
    except (TypeError, ValueError):
        return "-"
    if value < 60.0:
        return f"{value:.1f}s" if compact else f"{value:.1f} s"
    total = int(round(value))
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def format_reserve_clock_duration(seconds) -> str:
    """Format court et stable pour les colonnes de listes (m:ss ou h:mm:ss)."""
    try:
        total = max(0, int(round(float(seconds or 0.0))))
    except (TypeError, ValueError):
        return "-"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_reserve_size(size_bytes) -> str:
    try:
        size = max(0, int(size_bytes))
    except (TypeError, ValueError):
        return "-"
    units = ((1024 ** 3, "Go"), (1024 ** 2, "Mo"), (1024, "Ko"))
    for divisor, label in units:
        if size >= divisor:
            return f"{size / divisor:.1f} {label}"
    return f"{size} o"


def format_reserve_rms(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "-"


def format_reserve_scale(entry_or_label) -> str:
    if isinstance(entry_or_label, str):
        label = entry_or_label
    else:
        label = (
            getattr(entry_or_label, "detected_scale_label", None)
            or getattr(entry_or_label, "dominant_note", None)
            or ""
        )
    return str(label).strip() or "-"


def format_reserve_status(value) -> str:
    return reserve_technical_status_label(value)
