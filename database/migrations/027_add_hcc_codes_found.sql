-- 027_add_hcc_codes_found.sql
-- Adds hcc_codes_found column to claims_batches so the demo seeder
-- (backend/app/seed_claims_cohorts_demo.py) and the claims UI
-- (frontend/src/app/claims/page.tsx) can persist / display the
-- number of HCC codes identified in a claims batch.

ALTER TABLE claims_batches
    ADD COLUMN IF NOT EXISTS hcc_codes_found INT NOT NULL DEFAULT 0;
