"""Application use cases: the system's API for every driving adapter (R2).

* ``searches``: AddSavedSearch, SetRelevanceOverride
* ``runs``: StartRun, ResumeRun, RefreshOffer, FinalizeIdleRuns
* ``finalize_run``: FinalizeRun (run completion check, metrics, health)
* ``extraction``: the reconciling extractor (ADR 0010)
* ``list_offers``: ListOffers (read side)

Pipeline stages are job handlers in :mod:`scrappy.application.jobs.handlers`.
"""
