"""Single-process bounded inference admission; no unbounded worker queue."""
from threading import BoundedSemaphore
admission=BoundedSemaphore(2)
