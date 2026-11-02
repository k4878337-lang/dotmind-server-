import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.task import Task
from app.services.task_service import task_service

logger = logging.getLogger("dotmind.worker")

class TaskWorker:
    def __init__(self, poll_interval: float = 2.0):
        self.poll_interval = poll_interval
        self._running = False
        self._worker_task: asyncio.Task = None

    async def start(self):
        """Starts the background task worker loop."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("TaskWorker background engine started.")

    async def stop(self):
        """Stops the background task worker loop gracefully."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("TaskWorker background engine stopped.")

    async def _worker_loop(self):
        # Crash recovery on worker startup: reset any dangling 'running' tasks back to 'queued'
        await self._recover_dangling_tasks()

        while self._running:
            try:
                processed_any = await self.process_next_batch()
                if not processed_any:
                    await asyncio.sleep(self.poll_interval)
                else:
                    await asyncio.sleep(0.5)  # slight pause between steps
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in task worker loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _recover_dangling_tasks(self):
        """Recovers tasks that were interrupted mid-step by a process restart."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Task).where(Task.status == "running"))
                dangling = result.scalars().all()
                for t in dangling:
                    t.status = "queued"
                if dangling:
                    await db.commit()
                    logger.info(f"TaskWorker recovered {len(dangling)} dangling tasks after restart.")
        except Exception as e:
            logger.error(f"Failed to recover dangling tasks: {e}")

    async def process_next_batch(self) -> bool:
        """Picks up eligible queued tasks and processes their next step."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Task)
                .where(Task.status == "queued")
                .order_by(Task.priority.desc(), Task.created_at.asc())
                .limit(5)
            )
            tasks = result.scalars().all()
            if not tasks:
                return False

            for task in tasks:
                try:
                    await task_service.process_task_step(db, task)
                except Exception as ex:
                    logger.error(f"Error processing task {task.id}: {ex}")

            return True

task_worker = TaskWorker()
