import threading
import uuid


class OCRJobStore:
    """Tracks background OCR jobs so an HTTP request can return immediately
    while the slow OCR work continues on a separate thread."""

    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def start(self, work) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {"status": "processing"}
        threading.Thread(target=self._run, args=(job_id, work), daemon=True).start()
        return job_id

    def consume(self, job_id: str) -> dict:
        """Returns the job's current state, removing it once it has finished."""
        with self._lock:
            job = self._jobs.get(job_id, {"status": "not_found"})
            if job.get("status") in ("done", "error"):
                del self._jobs[job_id]
            return job

    def _run(self, job_id: str, work) -> None:
        try:
            result = work()
            result["status"] = "done"
        except Exception as exc:
            result = {"status": "error", "errors": [f"فشلت معالجة الصور: {exc}"]}

        with self._lock:
            self._jobs[job_id] = result
