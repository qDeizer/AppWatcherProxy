"""Adapt mitmproxy's command-line lifecycle to our long-lived web server."""

import asyncio

from mitmproxy.tools.dump import DumpMaster


class EmbeddedMaster(DumpMaster):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ready = asyncio.Event()

    async def run(self) -> None:
        errorcheck = self.addons.get("errorcheck")
        proxyserver = self.addons.get("proxyserver")
        try:
            # Own startup in this task. DumpMaster.run() spawns setup tasks and
            # changes the host loop's task factory/exception handler globally.
            await errorcheck.shutdown_if_errored()
            if not self.should_exit.is_set() and proxyserver:
                if not await proxyserver.setup_servers():
                    await errorcheck.shutdown_if_errored()
                    raise RuntimeError("Proxy sunucusu başlatılamadı")
            if self.should_exit.is_set():
                return
            await self.running()
            await errorcheck.shutdown_if_errored()
            errorcheck.finish()
            self.ready.set()
            await self.should_exit.wait()
        except SystemExit as exc:
            # Catch inside the task, before asyncio can terminate the host.
            records = errorcheck.logger.has_errored if errorcheck else []
            details = "; ".join(record.getMessage() for record in records)
            raise RuntimeError(details or f"Proxy motoru sonlandı (kod {exc.code})") from exc
        finally:
            try:
                if proxyserver:
                    # Local mode stop calls set_intercept(""). Master.done()
                    # alone does not disable interception in an embedded host.
                    if not await proxyserver.servers.update([]):
                        raise RuntimeError("Yerel trafik yakalama kapatılamadı")
            finally:
                try:
                    await self.done()
                finally:
                    if errorcheck:
                        errorcheck.finish()
                    self._legacy_log_events.uninstall()
