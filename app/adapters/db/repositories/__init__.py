"""SQL implementations of the domain repository ports, one module per repository.

Import from here: `from app.adapters.db.repositories import SqlJobRepository`.
"""

from app.adapters.db.repositories.job import SqlJobRepository

__all__ = ["SqlJobRepository"]
