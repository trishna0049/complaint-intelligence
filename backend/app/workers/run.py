"""Run the event pipeline's processes.

    python -m app.workers.run topics [--reset]   create the Kafka topics for EVENTS_PREFIX (reset: delete first)
    python -m app.workers.run relay              outbox -> Kafka
    python -m app.workers.run ai|llm|sla|notification
    python -m app.workers.run all                relay + the four workers in one process (development, e2e)

    --health-port N   serve GET /health (200 while every task runs, 503 otherwise) for Docker / Playwright

Stop with Ctrl+C. Each worker can run as several processes: Kafka balances partitions across a consumer group.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal

from app.ai.classifier import get_classifier
from app.ai.embeddings import get_embedder
from app.ai.sentiment import load_sentiment
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.redis import close_redis
from app.events import kafka
from app.services import sla
from app.workers.registry import BY_NAME

CRLF = chr(13) + chr(10)
SHORT = {"ai": "ai-worker", "llm": "llm-worker", "sla": "sla-worker", "notification": "notification-worker"}


async def serve_health(port: int, tasks: list[asyncio.Task[None]]) -> asyncio.Server:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readline()
        running = [t.get_name() for t in tasks if not t.done()]
        ok = len(running) == len(tasks)
        body = json.dumps({"status": "ok" if ok else "degraded", "running": running}).encode()
        status = "200 OK" if ok else "503 Service Unavailable"
        head = [f"HTTP/1.1 {status}", "Content-Type: application/json", f"Content-Length: {len(body)}"]
        writer.write(CRLF.join([*head, "Connection: close", "", ""]).encode() + body)
        await writer.drain()
        writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


async def main(command: str, reset: bool, health_port: int | None = None) -> None:
    s = get_settings()
    if command == "topics":
        created = await kafka.ensure_topics(reset=reset)
        print(f"topics for prefix '{s.events_prefix}' ready ({len(created)} created) on {s.kafka_bootstrap_servers}")
        return
    if command in ("ai", "all"):  # the AI worker needs the models; load them before consuming
        get_classifier()
        load_sentiment()
        get_embedder()
    await kafka.ensure_topics()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows: Ctrl+C raises KeyboardInterrupt
            loop.add_signal_handler(sig, stop.set)
    tasks = []
    if command in ("relay", "all"):
        tasks.append(asyncio.create_task(kafka.run_relay(stop), name="relay"))
    names = list(SHORT.values()) if command == "all" else [SHORT[command]] if command in SHORT else []
    for name in names:
        tasks.append(asyncio.create_task(kafka.run_consumer(BY_NAME[name], stop), name=name))
    if "sla-worker" in names:  # the SLA worker also scans for warnings (80 %) and breaches (100 %)
        tasks.append(asyncio.create_task(sla.scan_forever(stop), name="sla-scanner"))
    logging.getLogger("app.workers").info("running %s (pid %s)", ", ".join(t.get_name() for t in tasks), os.getpid())
    health = await serve_health(health_port, tasks) if health_port else None
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()  # surface a crash
    finally:
        if health is not None:
            health.close()
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispose_engine()
        await close_redis()


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["topics", "relay", "all", *SHORT])
    parser.add_argument("--reset", action="store_true", help="topics: delete the prefix's topics first")
    parser.add_argument("--health-port", type=int, default=None, help="serve GET /health on this port")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(args.command, args.reset, args.health_port))


if __name__ == "__main__":
    cli()
