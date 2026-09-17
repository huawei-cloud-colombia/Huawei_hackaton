"""
Tests del VelocityTracker (sliding window) y TemporalBlocklist.
"""

from datetime import datetime, timedelta, timezone

import pytest

from sentinelpay.persistence.velocity_tracker import VelocityTracker
from sentinelpay.persistence.blocklist import TemporalBlocklist


def _ts(seconds: float) -> datetime:
    """Timestamp UTC base + seconds."""
    return datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


class TestVelocityTracker:
    def test_record_and_count_card(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_card("card_1", _ts(1))
        vt.record_card("card_1", _ts(2))
        window = vt.get_card_window("card_1", _ts(2), 10)
        assert len(window) == 3

    def test_card_window_excludes_old(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_card("card_1", _ts(1))
        vt.record_card("card_1", _ts(15))
        window = vt.get_card_window("card_1", _ts(15), 10)
        assert len(window) == 1

    def test_card_window_boundary(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_card("card_1", _ts(10))
        window = vt.get_card_window("card_1", _ts(10), 10)
        assert len(window) == 2

    def test_card_window_just_outside(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_card("card_1", _ts(10.01))
        window = vt.get_card_window("card_1", _ts(10.01), 10)
        assert len(window) == 1

    def test_independent_cards(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_card("card_2", _ts(0))
        w1 = vt.get_card_window("card_1", _ts(0), 10)
        w2 = vt.get_card_window("card_2", _ts(0), 10)
        assert len(w1) == 1
        assert len(w2) == 1

    def test_device_distinct_cards(self):
        vt = VelocityTracker()
        vt.record_device("dev_1", "card_1", _ts(0))
        vt.record_device("dev_1", "card_2", _ts(1))
        vt.record_device("dev_1", "card_3", _ts(2))
        count = vt.count_distinct_cards("dev_1", _ts(2), 30)
        assert count == 3

    def test_device_same_card_repeated(self):
        vt = VelocityTracker()
        vt.record_device("dev_1", "card_1", _ts(0))
        vt.record_device("dev_1", "card_1", _ts(1))
        vt.record_device("dev_1", "card_1", _ts(2))
        count = vt.count_distinct_cards("dev_1", _ts(2), 30)
        assert count == 1

    def test_device_window_excludes_old(self):
        vt = VelocityTracker()
        vt.record_device("dev_1", "card_1", _ts(0))
        vt.record_device("dev_1", "card_2", _ts(35))
        count = vt.count_distinct_cards("dev_1", _ts(35), 30)
        assert count == 1

    def test_cleanup_removes_old(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_card("card_1", _ts(1))
        vt.record_device("dev_1", "card_1", _ts(0))
        vt.cleanup(_ts(400), max_window_seconds=300)
        assert vt.get_card_count("card_1") == 0
        assert vt.get_device_count("dev_1") == 0

    def test_clear(self):
        vt = VelocityTracker()
        vt.record_card("card_1", _ts(0))
        vt.record_device("dev_1", "card_1", _ts(0))
        vt.clear()
        assert vt.get_card_count("card_1") == 0
        assert vt.get_device_count("dev_1") == 0


class TestTemporalBlocklist:
    def test_block_and_check_card(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_card("card_1", _ts(120))
        assert bl.is_card_blocked("card_1", _ts(50)) is True

    def test_card_block_expired(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_card("card_1", _ts(120))
        assert bl.is_card_blocked("card_1", _ts(120)) is False
        assert bl.is_card_blocked("card_1", _ts(121)) is False

    def test_card_block_boundary(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_card("card_1", _ts(120))
        assert bl.is_card_blocked("card_1", _ts(119.99)) is True

    def test_block_and_check_device(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_device("dev_1", _ts(120))
        assert bl.is_device_blocked("dev_1", _ts(50)) is True

    def test_device_block_expired(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_device("dev_1", _ts(120))
        assert bl.is_device_blocked("dev_1", _ts(121)) is False

    def test_unblock_not_in_list(self):
        bl = TemporalBlocklist()
        assert bl.is_card_blocked("card_unknown", _ts(0)) is False
        assert bl.is_device_blocked("dev_unknown", _ts(0)) is False

    def test_cleanup_removes_expired(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_card("card_1", _ts(100))
        bl.block_device("dev_1", _ts(100))
        bl.cleanup(_ts(150))
        assert len(bl.get_blocked_cards()) == 0
        assert len(bl.get_blocked_devices()) == 0

    def test_clear(self):
        bl = TemporalBlocklist()
        bl.block_card("card_1", _ts(120))
        bl.block_device("dev_1", _ts(120))
        bl.clear()
        assert len(bl.get_blocked_cards()) == 0
        assert len(bl.get_blocked_devices()) == 0

    def test_reblock_extends_expiry(self):
        bl = TemporalBlocklist(default_duration=120)
        bl.block_card("card_1", _ts(100))
        bl.block_card("card_1", _ts(200))
        assert bl.is_card_blocked("card_1", _ts(150)) is True
