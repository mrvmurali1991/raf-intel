"""Accuracy / correctness harness for the RAF calculator.

This package is intentionally isolated from the main application. It
generates synthetic Medicare patient FHIR bundles, extracts ICD-10 and
demographics, and triple-scores them against the hccinfhir library
(the de-facto oracle, since CMS SAS is licensed and unavailable).
"""
