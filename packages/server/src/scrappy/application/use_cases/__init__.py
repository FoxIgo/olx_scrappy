"""Application use cases: the system's API for every driving adapter (R2).

* ``searches``: AddSavedSearch, SetRelevanceOverride
* ``runs``: StartRun, ResumeRun, RefreshOffer
* ``finalize_run``: FinalizeRun (run completion check, metrics, health)
* ``extractions``: RequeueExtractions
* ``list_offers``: ListOffers (read side)

Pipeline stages are job handlers in :mod:`scrappy.application.jobs.handlers`.
"""
