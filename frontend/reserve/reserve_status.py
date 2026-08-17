from __future__ import annotations

from enum import StrEnum


class ReserveTechnicalStatus(StrEnum):
    """État technique d'une entrée de Réserve, distinct de MaterialStatus."""

    NORMAL = "normal"
    NON_INDEXED = "non_indexed"
    NEEDS_ANALYSIS = "needs_analysis"
    MISSING = "missing"


STATUS_LABELS = {
    ReserveTechnicalStatus.NORMAL: "Normal",
    ReserveTechnicalStatus.NON_INDEXED: "Non indexe",
    ReserveTechnicalStatus.NEEDS_ANALYSIS: "A analyser",
    ReserveTechnicalStatus.MISSING: "Fichier manquant",
}

STATUS_TONES = {
    ReserveTechnicalStatus.NORMAL: "neutral",
    ReserveTechnicalStatus.NON_INDEXED: "info",
    ReserveTechnicalStatus.NEEDS_ANALYSIS: "warning",
    ReserveTechnicalStatus.MISSING: "error",
}


def coerce_reserve_technical_status(value) -> ReserveTechnicalStatus:
    try:
        return ReserveTechnicalStatus(str(value or ReserveTechnicalStatus.NORMAL))
    except ValueError:
        return ReserveTechnicalStatus.NORMAL


def reserve_technical_status_label(value) -> str:
    return STATUS_LABELS[coerce_reserve_technical_status(value)]


def reserve_technical_status_tone(value) -> str:
    return STATUS_TONES[coerce_reserve_technical_status(value)]
