"""Async Queue

Based on Peter Hinch's queue.py:
https://github.com/peterhinch/micropython-async/blob/master/v3/primitives/queue.py
"""
import asyncio


class AsyncQueue:
    """Async queue that supports both awaitable/blocking and non-blocking get and put API's."""
    def __init__(self, maxsize: int = 0) -> None:
        self.maxsize = maxsize
        self._queue = []
        self._event_put = asyncio.Event()
        self._event_get = asyncio.Event()

    def _get(self):
        self._event_get.set()  # Schedule all tasks waiting on this event
        self._event_get.clear()
        return self._queue.pop(0)

    def _put(self, val):
        self._event_put.set()  # Schedule tasks waiting on this event
        self._event_put.clear()
        self._queue.append(val)

    def empty(self) -> bool:
        """Check if queue is empty.

        Returns:
            bool: True if the queue is empty, False otherwise.
        """
        return len(self._queue) == 0

    def full(self) -> bool:
        """Check if queue is full.

        Note: If the Queue was initialized with maxsize=0 (the default) or any negative number,
        then full() is never True.

        Returns:
            bool: True if there are maxsize number of items in the queue, False otherwise.
        """
        return self.maxsize > 0 and self.size() >= self.maxsize

    async def get(self):
        """Blocking: Get next item from queue.

        If queue is empty, will wait/block until next available item is placed into the queue.
        Multiple tasks may be waiting on put event. The first of N gets the item, the rest
        resume waiting for a put event.

        Returns:
            generic: Next item in queue.
        """
        while self.empty():
            # Queue is empty, suspend task until a put occurs
            await self._event_put.wait()
        return self._get()

    def get_nowait(self):
        """Non-blocking: Get next item from queue.

        Returns:
            generic: Next item in queue if not empty, None otherwise.
        """
        if self.empty():
            return None

        return self._get()

    async def put(self, val):
        """Blocking: Put item into queue.

        If the queue is full, will wait/block until an item is removed from the queue.
        Multiple tasks may be waiting on get event. The first of N puts the item, the rest
        resume waiting for next get event, if queue is still full.

        Args:
            val (generic): Item to put in queue.
        """
        while self.full():
            # Queue full, suspend task until a get occurs
            await self._event_get.wait()
        self._put(val)

    def put_nowait(self, val) -> bool:
        """Non-blocking: Put item into queue.

        Args:
            val (generic): Item to put in queue.

        Returns:
            bool: False if successful, True if failed
        """
        failed = False
        if self.full():
            failed = True
        else:
            self._put(val)

        return failed

    def size(self) -> int:
        """Return number of items in the queue"""
        return len(self._queue)
