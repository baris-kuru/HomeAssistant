import asyncio
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass(slots=True)
class Waiter:
    user_id: str
    lane: str
    seq: int


class ChatScheduler:
    PRIORITY = {"fast": 0, "search": 1, "deep": 2}

    def __init__(self, max_concurrent: int = 3, max_per_user: int = 1, max_deep: int = 1):
        self.max_concurrent = max_concurrent
        self.max_per_user = max_per_user
        self.max_deep = max_deep
        self._condition = asyncio.Condition()
        self._next_seq = 0
        self._active_total = 0
        self._active_deep = 0
        self._active_by_user = defaultdict(int)
        self._waiters: list[Waiter] = []

    def _ordered_waiters(self) -> list[Waiter]:
        return sorted(self._waiters, key=lambda item: (self.PRIORITY.get(item.lane, 99), item.seq))

    def _can_run(self, waiter: Waiter) -> bool:
        if self._active_total >= self.max_concurrent:
            return False
        if self._active_by_user[waiter.user_id] >= self.max_per_user:
            return False
        if waiter.lane == "deep" and self._active_deep >= self.max_deep:
            return False
        for other in self._ordered_waiters():
            if other.seq == waiter.seq:
                return True
            if self._active_by_user[other.user_id] >= self.max_per_user:
                continue
            if other.lane == "deep" and self._active_deep >= self.max_deep:
                continue
            return False
        return True

    async def snapshot(self, user_id: str, lane: str) -> dict:
        async with self._condition:
            ordered = self._ordered_waiters()
            ahead = 0
            for waiter in ordered:
                if waiter.user_id == user_id and waiter.lane == lane:
                    break
                ahead += 1
            return {
                "active_total": self._active_total,
                "active_deep": self._active_deep,
                "active_for_user": self._active_by_user[user_id],
                "queued": len(self._waiters),
                "ahead": ahead,
                "max_concurrent": self.max_concurrent,
                "max_per_user": self.max_per_user,
                "max_deep": self.max_deep,
            }

    @asynccontextmanager
    async def slot(self, user_id: str, lane: str):
        waiter = None
        async with self._condition:
            waiter = Waiter(user_id=user_id, lane=lane, seq=self._next_seq)
            self._next_seq += 1
            self._waiters.append(waiter)

            while not self._can_run(waiter):
                await self._condition.wait()

            self._waiters = [item for item in self._waiters if item.seq != waiter.seq]
            self._active_total += 1
            self._active_by_user[user_id] += 1
            if lane == "deep":
                self._active_deep += 1
            self._condition.notify_all()

        try:
            yield
        finally:
            try:
                async with asyncio.timeout(5):
                    async with self._condition:
                        self._active_total -= 1
                        self._active_by_user[user_id] -= 1
                        if lane == "deep":
                            self._active_deep -= 1
                        if self._active_by_user[user_id] <= 0:
                            self._active_by_user.pop(user_id, None)
                        self._condition.notify_all()
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass  # Best effort cleanup


chat_scheduler = ChatScheduler(
    max_concurrent=int(os.getenv("CHAT_MAX_CONCURRENT", "3")),
    max_per_user=int(os.getenv("CHAT_MAX_PER_USER", "1")),
    max_deep=int(os.getenv("CHAT_MAX_DEEP", "1")),
)
