from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncGenerator,
    Deque,
    Dict,
    Optional,
    Set,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight connection stub — replace with real DB driver (e.g. asyncpg)
# ---------------------------------------------------------------------------

class _Connection:
    """Minimal stand-in for a real async database connection.

    In production replace this with ``asyncpg.Connection``,
    ``aiomysql.Connection``, ``aiosqlite.Connection``, etc.
    """

    _counter: int = 0

    def __init__(self) -> None:
        _Connection._counter += 1
        self._id: int = _Connection._counter
        self._closed: bool = False
        self._created_at: float = time.monotonic()
        logger.debug("Connection #%d created", self._id)

    @property
    def id(self) -> int:
        return self._id

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def ping(self) -> bool:
        """Return ``True`` if the connection is healthy."""
        await asyncio.sleep(0)  # yield control
        return not self._closed

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            logger.debug("Connection #%d closed", self._id)

    async def execute(self, query: str, *args: Any) -> Any:
        if self._closed:
            raise ConnectionError(f"Connection #{self._id} is closed")
        await asyncio.sleep(0)
        return f"Result of: {query}"

    def __repr__(self) -> str:
        return f"<_Connection #{self._id} closed={self._closed}>"


# ---------------------------------------------------------------------------
# Pool configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoolConfig:
    """Immutable pool configuration."""

    min_size: int = 2
    """Minimum number of connections kept open."""

    max_size: int = 10
    """Maximum number of connections allowed."""

    max_idle_time: float = 300.0
    """Seconds before an idle connection is recycled."""

    max_lifetime: float = 3600.0
    """Maximum lifetime of a connection in seconds."""

    acquire_timeout: float = 30.0
    """Seconds to wait for a connection before raising TimeoutError."""

    health_check_interval: float = 30.0
    """Interval (seconds) between background health checks."""

    retry_attempts: int = 3
    """Number of retries when creating a new connection."""

    retry_delay: float = 1.0
    """Delay in seconds between connection creation retries."""


# ---------------------------------------------------------------------------
# Pooled connection wrapper
# ---------------------------------------------------------------------------

@dataclass
class _PooledConnection:
    """Wraps a raw connection with pool bookkeeping."""

    conn: _Connection
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)

    @property
    def age(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def idle_time(self) -> float:
        return time.monotonic() - self.last_used_at

    def mark_used(self) -> None:
        self.last_used_at = time.monotonic()


# ---------------------------------------------------------------------------
# Singleton pool
# ---------------------------------------------------------------------------

class AsyncConnectionPool:
    """High-performance singleton async connection pool.

    Usage::

        pool = AsyncConnectionPool.get_instance(
            config=PoolConfig(min_size=5, max_size=20),
        )
        await pool.initialize()

        async with pool.acquire() as conn:
            result = await conn.execute("SELECT 1")

        await pool.close()
    """

    _instance: Optional["AsyncConnectionPool"] = None
    _instance_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    async def get_instance(
        cls,
        config: Optional[PoolConfig] = None,
    ) -> "AsyncConnectionPool":
        """Return the singleton instance, creating it if necessary.

        This method is async-safe and guarantees that only one pool
        exists per process.
        """
        if cls._instance is not None:
            return cls._instance

        async with cls._instance_lock:
            # Double-check after acquiring the lock
            if cls._instance is not None:
                return cls._instance

            cfg = config or PoolConfig()
            instance = cls._new(cfg)
            cls._instance = instance
            return instance

    @classmethod
    def _new(cls, config: PoolConfig) -> "AsyncConnectionPool":
        """Bypass singleton check — for internal use only."""
        obj = object.__new__(cls)
        obj._config = config
        obj._pool: Deque[_PooledConnection] = deque()
        obj._in_use: Set[_PooledConnection] = set()
        obj._semaphore: Optional[asyncio.Semaphore] = None
        obj._lock = asyncio.Lock()
        obj._initialized = False
        obj._closed = False
        obj._waiters: int = 0
        obj._total_created: int = 0
        obj._total_destroyed: int = 0
        obj._health_check_task: Optional[asyncio.Task[None]] = None
        return obj

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the minimum number of connections and start background tasks."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            self._semaphore = asyncio.Semaphore(self._config.max_size)

            for _ in range(self._config.min_size):
                pc = await self._create_connection()
                self._pool.append(pc)

            self._health_check_task = asyncio.create_task(
                self._health_check_loop(),
                name="pool-health-check",
            )

            self._initialized = True
            logger.info(
                "Pool initialized with %d/%d connections",
                len(self._pool),
                self._config.max_size,
            )

    async def close(self) -> None:
        """Close all connections and stop background tasks."""
        if self._closed:
            return

        async with self._lock:
            if self._closed:
                return

            self._closed = True

            if self._health_check_task is not None:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            # Close all idle connections
            while self._pool:
                pc = self._pool.popleft()
                await pc.conn.close()
                self._total_destroyed += 1

            # Close all in-use connections
            for pc in list(self._in_use):
                await pc.conn.close()
                self._total_destroyed += 1
            self._in_use.clear()

            self._initialized = False
            logger.info("Pool closed. Total created: %d, destroyed: %d",
                        self._total_created, self._total_destroyed)

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[_Connection, None]:
        """Acquire a connection from the pool.

        Usage::

            async with pool.acquire() as conn:
                await conn.execute("...")
        """
        if not self._initialized:
            raise RuntimeError("Pool is not initialized. Call initialize() first.")
        if self._closed:
            raise RuntimeError("Pool is closed.")

        pc = await self._acquire()
        try:
            yield pc.conn
        finally:
            await self._release(pc)

    async def _acquire(self) -> _PooledConnection:
        """Internal: get a connection, creating one if necessary."""
        self._waiters += 1
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._config.acquire_timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Timed out waiting for a connection "
                f"(timeout={self._config.acquire_timeout}s, "
                f"max_size={self._config.max_size})"
            )
        finally:
            self._waiters -= 1

        async with self._lock:
            # Try to reuse an idle connection
            while self._pool:
                pc = self._pool.popleft()

                # Evict stale connections
                if pc.age > self._config.max_lifetime:
                    await self._destroy(pc)
                    self._semaphore.release()
                    break  # fall through to create a new one

                if pc.idle_time > self._config.max_idle_time:
                    await self._destroy(pc)
                    self._semaphore.release()
                    break

                # Health check
                if await pc.conn.ping():
                    pc.mark_used()
                    self._in_use.add(pc)
                    return pc
                else:
                    await self._destroy(pc)
                    self._semaphore.release()
                    break
            else:
                # Pool is empty — create a new connection below
                pass

            # Create a new connection (we hold the semaphore slot)
            pc = await self._create_connection()
            self._in_use.add(pc)
            return pc

    async def _release(self, pc: _PooledConnection) -> None:
        """Return a connection to the pool."""
        async with self._lock:
            self._in_use.discard(pc)

            if self._closed or pc.conn.is_closed:
                await self._destroy(pc)
            elif pc.age > self._config.max_lifetime:
                await self._destroy(pc)
            else:
                pc.mark_used()
                self._pool.append(pc)

        self._semaphore.release()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _create_connection(self) -> _PooledConnection:
        """Create a new connection with retry logic."""
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._config.retry_attempts + 1):
            try:
                raw = _Connection()
                self._total_created += 1
                return _PooledConnection(conn=raw)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Connection creation attempt %d/%d failed: %s",
                    attempt,
                    self._config.retry_attempts,
                    exc,
                )
                if attempt < self._config.retry_attempts:
                    await asyncio.sleep(self._config.retry_delay * attempt)

        raise ConnectionError(
            f"Failed to create connection after "
            f"{self._config.retry_attempts} attempts"
        ) from last_exc

    async def _destroy(self, pc: _PooledConnection) -> None:
        """Close a connection and update counters."""
        await pc.conn.close()
        self._total_destroyed += 1

    # ------------------------------------------------------------------
    # Background health check
    # ------------------------------------------------------------------

    async def _health_check_loop(self) -> None:
        """Periodically check and prune idle connections."""
        try:
            while True:
                await asyncio.sleep(self._config.health_check_interval)
                await self._prune_idle()
        except asyncio.CancelledError:
            logger.debug("Health check loop cancelled")
            raise

    async def _prune_idle(self) -> None:
        """Remove unhealthy or excess idle connections."""
        async with self._lock:
            healthy: Deque[_PooledConnection] = deque()

            while self._pool:
                pc = self._pool.popleft()

                if pc.age > self._config.max_lifetime:
                    await self._destroy(pc)
                    self._semaphore.release()
                    continue

                if await pc.conn.ping():
                    healthy.append(pc)
                else:
                    await self._destroy(pc)
                    self._semaphore.release()

            # Trim down to min_size if we have too many
            while len(healthy) > self._config.min_size:
                pc = healthy.pop()  # remove newest
                await self._destroy(pc)
                self._semaphore.release()

            self._pool = healthy

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Return current pool statistics."""
        return {
            "idle": len(self._pool),
            "in_use": len(self._in_use),
            "waiters": self._waiters,
            "total_created": self._total_created,
            "total_destroyed": self._total_destroyed,
            "max_size": self._config.max_size,
            "min_size": self._config.min_size,
        }

    def __repr__(self) -> str:
        s = self.stats
        return (
            f"<AsyncConnectionPool "
            f"idle={s['idle']} in_use={s['in_use']} "
            f"waiters={s['waiters']} "
            f"created={s['total_created']} destroyed={s['total_destroyed']}>"
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

async def get_pool(
    config: Optional[PoolConfig] = None,
) -> AsyncConnectionPool:
    """Shortcut to get (and initialize) the singleton pool."""
    pool = await AsyncConnectionPool.get_instance(config)
    await pool.initialize()
    return pool


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------

async def _demo() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = PoolConfig(
        min_size=3,
        max_size=5,
        acquire_timeout=5.0,
        health_check_interval=10.0,
    )

    pool = await get_pool(config)
    print(f"Pool: {pool}")
    print(f"Stats: {pool.stats}")

    async def worker(worker_id: int) -> None:
        async with pool.acquire() as conn:
            result = await conn.execute(f"SELECT {worker_id}")
            print(f"Worker {worker_id}: {result} (conn #{conn.id})")
            await asyncio.sleep(0.5)

    # Launch concurrent workers
    await asyncio.gather(*(worker(i) for i in range(10)))

    print(f"\nStats after workers: {pool.stats}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(_demo())