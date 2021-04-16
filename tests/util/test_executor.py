"""Test Home Assistant executor util."""

import concurrent.futures
import time
from unittest.mock import patch

import pytest

from homeassistant.util import executor
from homeassistant.util.executor import InterruptibleThreadPoolExecutor


async def test_executor_shutdown_can_interrupt_threads(caplog):
    """Test that the executor shutdown can interrupt threads."""

    iexecutor = InterruptibleThreadPoolExecutor()

    def _loop_sleep_in_executor():
        while True:
            time.sleep(0.1)

    sleep_futures = []

    for _ in range(100):
        sleep_futures.append(iexecutor.submit(_loop_sleep_in_executor))

    with patch.object(executor, "START_LOG_ATTEMPT", 1):
        iexecutor.logged_shutdown()

    for future in sleep_futures:
        with pytest.raises((concurrent.futures.CancelledError, SystemExit)):
            future.result()

    assert "is still running at shutdown" in caplog.text
    assert "time.sleep(0.1)" in caplog.text


async def test_executor_shutdown_without_interrupt(caplog):
    """Test that the executor shutdown without interrupt."""

    iexecutor = InterruptibleThreadPoolExecutor()

    def _loop_sleep_in_executor():
        time.sleep(0.1)
        return 50

    future = iexecutor.submit(_loop_sleep_in_executor)

    with patch.object(executor, "START_LOG_ATTEMPT", 1):
        iexecutor.logged_shutdown()

    assert future.result() == 50

    assert "is still running at shutdown" not in caplog.text
    assert "time.sleep(0.1)" not in caplog.text
