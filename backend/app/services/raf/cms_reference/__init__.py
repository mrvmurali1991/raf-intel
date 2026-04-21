"""CMS reference tables — independent transcription of CMS-published
CMS-HCC V24 / V28 coefficients and disease hierarchies.

These CSVs are hand-transcribed from CMS's public Rate Announcement PDFs
and serve as the independent audit artefact against which the third-party
``hccinfhir`` library is reconciled.  They are intentionally curated
(anchor HCCs, not exhaustive); a diff in any single anchor indicates the
library's bundled data file has drifted from CMS.

See :mod:`app.services.raf.reconcile` for the reconciliation driver and
:file:`backend/scripts/check_cms_reconciliation.py` for the CI gate.
"""
