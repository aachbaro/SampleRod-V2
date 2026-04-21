from __future__ import annotations

__all__ = ("Base", "Sample", "SampleBank", "AppContext")


def __getattr__(name: str):
    if name == "Base":
        from backend.db import Base

        return Base
    if name == "Sample":
        from backend.models.sample import Sample

        return Sample
    if name == "SampleBank":
        from backend.models.SampleLibrary import SampleBank

        return SampleBank
    if name == "AppContext":
        from backend.models.AppContext import AppContext

        return AppContext
    raise AttributeError(f"module 'backend.models' has no attribute {name!r}")
