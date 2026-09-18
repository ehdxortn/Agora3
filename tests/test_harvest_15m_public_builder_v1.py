from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research"
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


public = load_module("harvest_public_builder", RESEARCH / "harvest_15m_public_builder_v1.py")


def test_archive_timestamp_supports_ms_and_us():
    ms = 1735689600000
    us = 1735689600000000
    expected = pd.Timestamp("2025-01-01T00:00:00Z")
    assert public.archive_timestamp_to_utc(ms) == expected
    assert public.archive_timestamp_to_utc(us) == expected


def test_canonical_line_matches_frozen_supabase_format():
    line = public.canonical_btc_line(
        pd.Timestamp("2025-01-01T00:00:00Z"),
        "93576",
        "94509.42",
        "93489.03",
        "93838.04",
        "1840.29813",
    )
    assert line == (
        "1735689600000,93576.00000000,94509.42000000,93489.03000000,"
        "93838.04000000,1840.29813000"
    )


def test_month_range_covers_parity_window_exactly():
    months = public.month_range(public.PARITY_START, public.PARITY_END)
    assert months[0] == "2024-12"
    assert months[-1] == "2026-06"
    assert len(months) == 19
