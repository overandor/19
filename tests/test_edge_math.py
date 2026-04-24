"""Tests for scripts/edge_math.py"""
import pytest
from scripts.edge_math import edge_bps


def test_positive_edge():
    result = edge_bps(bid=100, ask=99, fees_bps=0, slip_bps=0, buffer_bps=0)
    assert result > 0


def test_zero_prices_returns_sentinel():
    assert edge_bps(bid=0, ask=100) < -1e8
    assert edge_bps(bid=100, ask=0) < -1e8


def test_fees_reduce_edge():
    gross = edge_bps(bid=100, ask=99, fees_bps=0, slip_bps=0, buffer_bps=0)
    net   = edge_bps(bid=100, ask=99, fees_bps=30, slip_bps=0, buffer_bps=0)
    assert net < gross


def test_equal_prices_zero_gross():
    result = edge_bps(bid=100, ask=100, fees_bps=0, slip_bps=0, buffer_bps=0)
    assert abs(result) < 1e-6


def test_negative_edge_when_costs_exceed_spread():
    result = edge_bps(bid=100, ask=99.9, fees_bps=100, slip_bps=10, buffer_bps=5)
    assert result < 0
