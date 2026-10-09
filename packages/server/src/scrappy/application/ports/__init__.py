"""Port interfaces (typing.Protocol) owned by the application layer.

Import from the submodules (``ports.listing_source``, ``ports.repositories``,
``ports.job_queue``, ``ports.unit_of_work``, ``ports.extractor``, ``ports.queries``,
``ports.system``). This package deliberately re-exports nothing, to keep the import graph
between ports and the job model acyclic.
"""
