import asyncio
import logging

import pytest
from mitmproxy import options

from backend.capture.engine import CaptureEngine, CaptureState
from backend.capture.master import EmbeddedMaster


async def test_startup_exit_is_contained_and_stop_allows_restart():
    master = EmbeddedMaster(options.Options(mode=[]), with_termlog=False, with_dumper=False)
    checker = master.addons.get("errorcheck")
    checker.logger.has_errored.append(
        logging.LogRecord("test", logging.ERROR, "", 0, "startup failure", (), None)
    )
    # This must be a separate asyncio task: uncaught SystemExit would kill
    # the host loop even if the caller caught it while awaiting the task.
    task = asyncio.create_task(master.run())
    with pytest.raises(RuntimeError, match="startup failure"):
        await task
    assert checker.logger not in logging.getLogger().handlers
    engine = CaptureEngine(lambda session: asyncio.sleep(0), 1024)
    engine._master = master
    engine._task = task
    engine.state = CaptureState.ERROR
    await engine.stop()
    assert engine.state == CaptureState.STOPPED
    assert engine._task is None
    await engine.stop()


async def test_normal_stop_releases_servers_and_can_start_again():
    for _ in range(2):
        master = EmbeddedMaster(
            options.Options(mode=["regular"], listen_host="127.0.0.1", listen_port=0),
            with_termlog=False, with_dumper=False,
        )
        task = asyncio.create_task(master.run())
        server = master.addons.get("proxyserver")
        async with asyncio.timeout(5):
            while not server.listen_addrs():
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        master.shutdown()
        await asyncio.wait_for(task, 5)
        assert len(server.servers) == 0
        assert not server.listen_addrs()


async def test_stop_before_run_never_starts_servers(monkeypatch):
    master = EmbeddedMaster(options.Options(mode=[]), with_termlog=False, with_dumper=False)
    async def unexpected_setup():
        pytest.fail("setup ran after shutdown")
    monkeypatch.setattr(master.addons.get("proxyserver"), "setup_servers", unexpected_setup)
    master.shutdown()
    await asyncio.sleep(0)
    await master.run()
    assert not master.ready.is_set()


async def test_cancel_during_startup_finishes_cleanup(monkeypatch):
    master = EmbeddedMaster(options.Options(mode=[]), with_termlog=False, with_dumper=False)
    entered = asyncio.Event()
    finalized = asyncio.Event()
    async def slow_setup():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()
    monkeypatch.setattr(master.addons.get("proxyserver"), "setup_servers", slow_setup)
    task = asyncio.create_task(master.run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finalized.is_set()
    assert master.addons.get("errorcheck").logger not in logging.getLogger().handlers
