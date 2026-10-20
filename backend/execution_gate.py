import threading


class ExecutionGate:
    """Parallel jobs, with an exclusive maintenance mode for local rechecks."""
    def __init__(self):
        self.guard = threading.Lock()
        self.jobs = set()
        self.maintenance = False

    def enter(self, job_id, limit):
        with self.guard:
            if self.maintenance or job_id in self.jobs or len(self.jobs) >= limit:
                return False
            self.jobs.add(job_id)
            return True

    def leave(self, job_id):
        with self.guard:
            self.jobs.discard(job_id)

    def locked(self):
        with self.guard:
            return bool(self.jobs) or self.maintenance

    def acquire(self, blocking=False):
        with self.guard:
            if self.jobs or self.maintenance:
                return False
            self.maintenance = True
            return True

    def release(self):
        with self.guard:
            self.maintenance = False
