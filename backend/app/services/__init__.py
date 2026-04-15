"""
Services package for RAF Intelligence.

Domain sub-packages:
  raf/        — RAF score calculation, HCC mapping, multi-model support
  pipeline/   — Pipeline orchestration, event emission, skill routing
  auth/       — JWT tokens, password hashing, session management
  emr/        — EMR connection management and vendor adapters
  clinical/   — Patient, encounter, diagnosis, MEAT evidence services
  compliance/ — HIPAA audit logging, data retention, PHI de-identification

All domain packages re-export their public symbols so existing flat imports
(e.g. ``from app.services.auth_service import decode_token``) continue to
work without modification.
"""
