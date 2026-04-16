#!/usr/bin/env python3
"""
Generate RAF Intelligence E2E Demo DOCX with embedded screenshots.
"""
import os
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

DIR = Path(__file__).parent / "demo-screenshots"
OUT = Path(__file__).parent / "RAF_Intelligence_E2E_Demo.docx"


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0x0D, 0x6E, 0x6E)
    return h


def add_para(doc, text, bold=False, italic=False, size=11):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    return p


def add_image(doc, filename, caption="", width=Inches(6.2)):
    path = DIR / filename
    if not path.exists():
        add_para(doc, f"[Screenshot not found: {filename}]", italic=True)
        return
    doc.add_picture(str(path), width=width)
    last_paragraph = doc.paragraphs[-1]
    last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if caption:
        p = doc.add_paragraph()
        run = p.add_run(caption)
        run.italic = True
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Shading Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(10)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = str(val)
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(10)
    return table


def build():
    doc = Document()

    # ── Page setup ──
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # ════════════════════════════════════════════════════════════
    # COVER PAGE
    # ════════════════════════════════════════════════════════════
    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("RAF Intelligence")
    run.bold = True
    run.font.size = Pt(36)
    run.font.color.rgb = RGBColor(0x0D, 0x6E, 0x6E)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("End-to-End Demo Documentation")
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("AI-Powered Risk Adjustment Factor Optimization Platform")
    run.font.size = Pt(14)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    for _ in range(4):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Version 2.0  |  April 2026")
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Confidential - For Authorized Recipients Only")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
    run.italic = True

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # TABLE OF CONTENTS (manual)
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "Table of Contents", level=1)
    toc_items = [
        "1. Product Overview",
        "2. Demo Flow Summary",
        "3. Step 1: OpenEMR Login",
        "4. Step 2: Create New Patient in OpenEMR",
        "5. Step 3: Existing Patient Data in OpenEMR",
        "6. Step 4: RAF Intelligence Login & Dashboard",
        "7. Step 5: Patient Population Dashboard",
        "8. Step 6: Patient Detail View (RAF Scoring)",
        "9. Step 7: Newly Created Patient in RAF",
        "10. Step 8: EMR Configuration & AI Pipeline",
        "11. Step 9: Suspect Conditions",
        "12. Step 10: Recapture Gaps & Data Uploads",
        "13. Technical Architecture",
        "14. Key Takeaways",
    ]
    for item in toc_items:
        p = doc.add_paragraph(item)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.space_before = Pt(0)

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 1. PRODUCT OVERVIEW
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "1. Product Overview", level=1)
    add_para(
        doc,
        "RAF Intelligence is an AI-powered Risk Adjustment Factor (RAF) optimization platform "
        "designed for healthcare organizations participating in Medicare Advantage, ACOs, and "
        "value-based care programs.",
    )
    add_para(doc, "The platform automatically:")
    bullets = [
        "Ingests patient data from Electronic Medical Records (EMRs) via FHIR R4 standard",
        "Analyzes clinical encounters using Google Gemini 2.5 Pro AI",
        "Calculates CMS-HCC risk scores (V24/V28 blended model)",
        "Identifies missed diagnoses and suspect conditions for revenue optimization",
        "Generates care gaps, provider worklists, and compliance reports",
        "Tracks MEAT documentation compliance (Monitor, Evaluate, Assess, Treat)",
    ]
    for b in bullets:
        doc.add_paragraph(b, style="List Bullet")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 2. DEMO FLOW
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "2. Demo Flow Summary", level=1)
    add_para(
        doc,
        "This document demonstrates the complete end-to-end data flow from "
        "patient creation in the EHR to AI-powered risk analysis in RAF Intelligence.",
    )
    add_para(doc, "")
    add_table(
        doc,
        ["Phase", "System", "Action"],
        [
            ["1", "OpenEMR (EHR)", "Login and create patient with demographics"],
            ["2", "OpenEMR (EHR)", "View existing patient clinical data"],
            ["3", "FHIR R4 Sync", "Automated data extraction (9 resource types)"],
            ["4", "RAF Intelligence", "Login and view patient population"],
            ["5", "RAF Intelligence", "Patient detail with RAF scores and HCCs"],
            ["6", "RAF Intelligence", "AI pipeline configuration and monitoring"],
            ["7", "RAF Intelligence", "Suspect conditions and care gaps"],
        ],
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 3. STEP 1: OpenEMR Login
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "3. Step 1: OpenEMR Login", level=1)
    add_para(
        doc,
        "We begin at the external OpenEMR instance (openemr.ehrservicedesk.com), "
        "which serves as the source Electronic Health Record system with 13 patients.",
    )
    add_image(doc, "01_openemr_login_page.png", "OpenEMR Login Page - Secure HTTPS connection")
    add_para(doc, "")
    add_image(doc, "02_openemr_login_filled.png", "Admin credentials entered")
    add_para(doc, "")
    add_image(doc, "03_openemr_dashboard.png", "OpenEMR Dashboard - Calendar view with multiple providers and facilities")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 4. STEP 2: Create Patient
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "4. Step 2: Create New Patient in OpenEMR", level=1)
    add_para(
        doc,
        "We create a new patient to demonstrate the complete data flow from EHR to RAF Intelligence. "
        "This patient will be automatically synced via FHIR R4 and appear in the RAF platform.",
    )
    add_image(doc, "04_openemr_new_patient_form.png", "OpenEMR New Patient Registration Form")
    add_para(doc, "")

    add_heading(doc, "Patient Demographics", level=2)
    add_table(
        doc,
        ["Field", "Value"],
        [
            ["Name", "Maria Elena Rodriguez"],
            ["Date of Birth", "March 15, 1958 (68 years old)"],
            ["Sex", "Female"],
            ["SSN", "999-88-7777"],
            ["External ID", "RAF-DEMO-2026"],
            ["Address", "4521 Palm Beach Blvd, Miami, FL 33137"],
            ["Phone", "(305) 555-0142"],
            ["Email", "maria.rodriguez@example.com"],
            ["Medicare Eligibility", "Yes (age 65+)"],
        ],
    )
    add_para(doc, "")
    add_image(doc, "05_openemr_patient_demographics.png", "Demographics filled - Name, DOB, Sex, SSN, External ID")
    add_para(doc, "")
    add_image(doc, "06_openemr_patient_contact.png", "Contact information - Address, Phone, Email")
    add_para(doc, "")
    add_image(doc, "07_openemr_patient_created.png", "Patient successfully created in OpenEMR")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 5. STEP 3: Existing Patient Data
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "5. Step 3: Existing Patient Data in OpenEMR", level=1)
    add_para(
        doc,
        "The OpenEMR instance already contains 13 patients with rich clinical data including "
        "diagnoses (ICD-10 codes), encounters, medications, lab results, immunizations, and allergies. "
        "This data is what RAF Intelligence ingests and analyzes.",
    )
    add_image(
        doc,
        "08_openemr_patient_summary_abeyta.png",
        "Patient Summary - Ronald Abeyta (82M) with multiple active medical problems",
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 6. STEP 4: RAF Login
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "6. Step 4: RAF Intelligence Login", level=1)
    add_para(
        doc,
        "We now switch to the RAF Intelligence platform to see how patient data from OpenEMR "
        "has been automatically ingested, analyzed, and scored.",
    )
    add_image(doc, "09_raf_login_page.png", "RAF Intelligence Login - Branded as 'TMIAB RAF Clinical Intelligence'")
    add_para(doc, "")
    add_image(doc, "10_raf_login_filled.png", "Admin credentials entered")
    add_para(doc, "")
    add_image(doc, "11_raf_after_login.png", "Successfully authenticated - RAF Intelligence Dashboard")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # Dashboard Overview
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "Dashboard Overview", level=2)
    add_para(
        doc,
        "The RAF Intelligence dashboard provides at-a-glance population health metrics, "
        "risk distribution, and pipeline activity status.",
    )
    add_image(doc, "12_raf_dashboard.png", "RAF Intelligence Dashboard - Population metrics and risk distribution")
    add_para(doc, "")
    add_image(doc, "13_raf_dashboard_scrolled.png", "Dashboard continued - Additional analytics and charts")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 7. STEP 5: Patient Population
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "7. Step 5: Patient Population Dashboard", level=1)
    add_para(
        doc,
        "The Patient Population view is the heart of RAF Intelligence. It shows all synced "
        "patients with their risk profiles, RAF scores, HCC counts, and analysis status.",
        bold=True,
    )
    add_image(
        doc,
        "14_raf_patients_list.png",
        "Patient Population - 13 patients synced from OpenEMR via FHIR R4",
    )
    add_para(doc, "")

    add_heading(doc, "Key Metrics", level=2)
    add_table(
        doc,
        ["Metric", "Value", "Description"],
        [
            ["Total Patients", "13", "All patients synced from OpenEMR"],
            ["High Risk (RAF >= 2.00)", "0", "No patients above threshold"],
            ["Medium Risk (1.00 - 1.99)", "5", "Patients requiring attention"],
            ["Average RAF Score", "0.92", "Population average risk score"],
            ["Total HCCs", "34", "Hierarchical Condition Categories identified"],
            ["Scored Rate", "85%", "Percentage of patients with RAF scores"],
        ],
    )
    add_para(doc, "")

    add_heading(doc, "Patient Risk Summary", level=2)
    add_table(
        doc,
        ["Patient", "Age/Sex", "Risk Level", "RAF Score", "HCCs", "Status"],
        [
            ["Abeyta, Ronald", "82M", "Medium", "1.069", "3", "Analyzed"],
            ["Henderson, Lisa", "65F", "Medium", "1.374", "5", "Analyzed"],
            ["Garcia, Maria", "67F", "Medium", "1.05", "4", "Analyzed"],
            ["Williams, Robert J", "81M", "Medium", "1.07", "3", "Analyzed"],
            ["Jackson, Julia", "71F", "Low", "0.94", "3", "Analyzed"],
            ["Chen, Sarah", "54F", "Low", "0.12", "1", "Analyzed"],
            ["Rodriguez, Maria Elena", "68F", "Low", "0.37", "0", "Analyzed"],
            ["Adams, Terry", "19F", "Unscored", "-", "0", "Pending"],
        ],
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 8. STEP 6: Patient Detail
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "8. Step 6: Patient Detail View (RAF Scoring)", level=1)
    add_para(
        doc,
        "Clicking into a patient reveals comprehensive clinical intelligence with RAF scoring, "
        "active problems, encounters, care gaps, and data quality metrics.",
    )

    add_heading(doc, "Patient: Ronald Abeyta (RAF 1.069)", level=2)
    add_image(
        doc,
        "27_raf_patient_detail_abeyta.png",
        "Patient Detail - Header with RAF score, HCC count, MEAT compliance, and action buttons",
    )
    add_para(doc, "")

    add_heading(doc, "Patient Header Metrics", level=3)
    add_table(
        doc,
        ["Metric", "Value"],
        [
            ["RAF Score (MY 2026)", "1.069"],
            ["Model Segment", "CNA (Community, Non-Dual, Aged)"],
            ["HCC Count", "3 conditions"],
            ["Demographic Score", "0.550"],
            ["Disease Score", "0.519"],
            ["MEAT Compliance", "Pending"],
            ["Data Quality", "50%"],
        ],
    )
    add_para(doc, "")

    add_heading(doc, "Active Problems (8 ICD-10 Diagnoses)", level=3)
    add_table(
        doc,
        ["Condition", "ICD-10", "Onset"],
        [
            ["Type 2 diabetes mellitus without complications", "E11.9", "Jan 15, 2025"],
            ["COPD with acute exacerbation", "J44.1", "Jan 15, 2025"],
            ["Chronic kidney disease, stage 3", "N18.3", "Jan 15, 2025"],
            ["Hypothyroidism, unspecified", "E03.9", "Jun 1, 2024"],
            ["Hyperlipidemia, unspecified", "E78.5", "Jun 1, 2024"],
            ["Essential (primary) hypertension", "I10", "Jun 1, 2024"],
            ["Atherosclerotic heart disease", "I25.18", "Jun 1, 2024"],
            ["Primary osteoarthritis, right knee", "M17.11", "Jun 1, 2024"],
        ],
    )
    add_para(doc, "")

    add_image(
        doc,
        "28_raf_patient_abeyta_conditions.png",
        "Encounters, Care Gaps, and Data Completeness sections",
    )
    add_para(doc, "")

    add_heading(doc, "Recent Encounters", level=3)
    add_table(
        doc,
        ["Encounter", "Provider", "Date", "Action"],
        [
            ["Encounter for check up (procedure)", "Provider not listed", "Mar 20, 2026", "Analyze"],
            ["Follow-up Visit", "Dr. Johnson", "Mar 10, 2026", "Analyze"],
            ["Annual Wellness Visit", "Dr. Smith", "Jan 10, 2026", "Analyze"],
            ["Chronic Care Management", "Dr. Patel", "Sep 20, 2025", "Analyze"],
        ],
    )
    add_para(
        doc,
        "Each encounter has an 'Analyze' button that triggers Google Gemini 2.5 Pro AI analysis "
        "to extract missed diagnoses, validate existing codes, and assess MEAT compliance.",
        italic=True,
        size=10,
    )

    doc.add_page_break()

    add_heading(doc, "AI Clinical Analysis", level=2)
    add_para(
        doc,
        "The Clinical Analysis page shows AI-powered encounter analysis results from Google Gemini 2.5 Pro.",
    )
    add_image(doc, "16_raf_clinical_analysis.png", "Clinical Analysis - AI encounter analysis powered by Gemini 2.5 Pro")
    add_para(doc, "")

    add_heading(doc, "Patient: Lisa Henderson (RAF 1.374)", level=2)
    add_image(
        doc,
        "30_raf_patient_detail_henderson.png",
        "Lisa Henderson - 5 HCC conditions, Medium Risk, RAF 1.374",
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 9. STEP 7: Rodriguez in RAF
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "9. Step 7: Newly Created Patient in RAF Intelligence", level=1)
    add_para(
        doc,
        "The patient we created in OpenEMR (Maria Elena Rodriguez) has been automatically "
        "synced into RAF Intelligence via FHIR R4. This confirms the complete end-to-end data flow.",
        bold=True,
    )
    add_image(
        doc,
        "15_raf_search_rodriguez.png",
        "Searching for 'Rodriguez' - Patient found with demographic RAF score of 0.37",
    )
    add_para(doc, "")
    add_table(
        doc,
        ["Field", "Value"],
        [
            ["Patient", "Rodriguez, Maria Elena"],
            ["Age / Sex", "68F"],
            ["PID", "2433"],
            ["Risk Level", "Low"],
            ["RAF Score", "0.37 (demographic only)"],
            ["HCC Count", "0 (no conditions added yet)"],
            ["Status", "Analyzed"],
        ],
    )
    add_para(
        doc,
        "Note: The RAF score of 0.37 reflects the demographic-only score (age 68, female, "
        "Community Non-Dual Aged segment). Once clinical conditions are added in OpenEMR and "
        "synced, the RAF score will increase based on HCC mappings.",
        italic=True,
        size=10,
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 10. STEP 8: EMR Config
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "10. Step 8: EMR Configuration & AI Pipeline", level=1)
    add_para(
        doc,
        "The EMR Configuration page shows the integration setup and the 8-phase AI analysis pipeline.",
        bold=True,
    )
    add_image(
        doc,
        "25_raf_emr_connected.png",
        "EMR Configuration - AI Pipeline toggle ON, 2 connections, 8-phase pipeline visualization",
    )
    add_para(doc, "")

    add_heading(doc, "Connection Summary", level=2)
    add_table(
        doc,
        ["Metric", "Value"],
        [
            ["Total Connections", "2"],
            ["Active Connections", "1 (EHR ServiceDesk - FHIR R4)"],
            ["Inactive Connections", "1 (Local OpenEMR - Direct DB Legacy)"],
            ["Last Sync", "Apr 15, 2026 12:22 PM"],
            ["Errors", "0 - All connections healthy"],
        ],
    )
    add_para(doc, "")

    add_heading(doc, "8-Phase AI Analysis Pipeline", level=2)
    add_para(
        doc,
        "The AI Analysis Pipeline runs automatically on every EMR sync. "
        "The AUTO AI toggle is enabled (green), activating the full 8-phase chain:",
        bold=True,
    )
    add_table(
        doc,
        ["Phase", "Name", "Description"],
        [
            ["1", "EMR Sync", "FHIR R4 data ingestion from connected EHRs"],
            ["2", "Normalize", "Standardize codes, names, dates across sources"],
            ["3", "AI Analysis", "Gemini 2.5 Pro analyzes each encounter"],
            ["4", "RAF Calc", "CMS-HCC V24/V28 blended RAF scoring"],
            ["5", "HCC Hierarchy", "Trumping and interaction logic"],
            ["6", "Suspects", "4-engine suspect detection (lab, medication, history, NLP)"],
            ["7", "Gap Generation", "Care gaps and chart chase requests"],
            ["8", "Webhooks", "Notifications and completion events"],
        ],
    )

    add_para(doc, "")
    add_heading(doc, "Pipeline Visualization", level=2)
    add_image(doc, "24_raf_pipeline_demo.png", "Pipeline Demo - Visual representation of the 8-phase processing chain")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 11. STEP 9: Suspects
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "11. Step 9: Suspect Conditions", level=1)
    add_para(
        doc,
        "The Suspect Conditions module uses AI to identify potential missed diagnoses that could "
        "increase RAF scores. Suspects are detected from 6 evidence sources and ranked by confidence.",
    )
    add_image(
        doc,
        "18_raf_suspects.png",
        "Suspect Conditions Dashboard with filters by status, source, and confidence",
    )
    add_para(doc, "")

    add_heading(doc, "Active Suspects Detected (Sample)", level=2)
    add_table(
        doc,
        ["Patient", "Suspect HCC / ICD-10", "Evidence Type", "Confidence", "RAF Lift"],
        [
            ["Ronald Abeyta", "HCC 18 / E11.22 (Diabetes w/ CKD)", "Lab (HbA1c 9.2%)", "92%", "+0.302"],
            ["Ronald Abeyta", "HCC 85 / I50.9 (Heart Failure)", "Medication (Furosemide+Carvedilol)", "87%", "+0.323"],
            ["Lisa Henderson", "HCC 22 / E66.01 (Morbid Obesity)", "Historical (BMI 42, 2024)", "95%", "+0.250"],
            ["Lisa Henderson", "HCC 59 / F32.1 (MDD)", "Medication (Sertraline 100mg)", "81%", "+0.309"],
            ["Maria Garcia", "HCC 138 / N18.4 (CKD Stage 4)", "Lab (eGFR 22)", "94%", "+0.169"],
            ["James Thompson", "HCC 96 / I48.91 (Atrial Fib)", "Medication (Apixaban)", "88%", "+0.268"],
            ["Patrick Cisneros", "HCC 108 / I73.9 (PAD)", "Referral (Vascular consult)", "76%", "+0.288"],
            ["Maria E. Rodriguez", "HCC 19 / E11.9 (T2DM)", "Lab (Glucose 148)", "72%", "+0.105"],
        ],
    )
    add_para(
        doc,
        "Each suspect represents a potential missed diagnosis identified by the AI engine from lab results, "
        "medication patterns, historical conditions, or specialty referrals. Providers review and either "
        "Accept (adds to billing), Dismiss (with reason), or leave Open for further documentation.",
        italic=True,
        size=10,
    )
    add_para(doc, "")
    add_image(doc, "18b_raf_suspects_scrolled.png", "Suspect Conditions - Scrolled view showing full list")
    add_para(doc, "")

    add_heading(doc, "Suspect Detection Sources", level=2)
    add_table(
        doc,
        ["Source", "Description"],
        [
            ["Lab Results", "Abnormal lab values suggesting undiagnosed conditions"],
            ["Medications", "Prescriptions that imply conditions not on problem list"],
            ["Imaging", "Radiology findings suggesting undocumented diagnoses"],
            ["Referrals", "Specialty referrals indicating unrecorded conditions"],
            ["Historical", "Prior-year conditions not recaptured in current year"],
            ["NLP (AI)", "Gemini AI extraction from clinical notes and encounters"],
        ],
    )
    add_para(doc, "")

    add_heading(doc, "Confidence Levels", level=2)
    add_table(
        doc,
        ["Level", "Threshold", "Action"],
        [
            ["High", "> 85%", "Auto-accepted for coding review"],
            ["Medium", "65% - 85%", "Flagged for clinical review"],
            ["Low", "< 65%", "Queued for manual verification"],
        ],
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 12. STEP 10: Gaps & Uploads
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "12. Step 10: Recapture Gaps & Data Uploads", level=1)

    add_heading(doc, "Recapture Gaps", level=2)
    add_para(
        doc,
        "The Recapture Gaps module identifies conditions from prior measurement years that need "
        "to be re-documented in the current year to maintain RAF scores.",
    )
    add_image(doc, "19_raf_recapture_gaps.png", "Recapture Gaps Interface")
    add_para(doc, "")
    add_image(doc, "33_raf_recapture_gaps_detail.png", "Recapture Gaps - Detail View")
    add_para(doc, "")

    add_heading(doc, "Data Uploads (Document Analysis)", level=2)
    add_para(
        doc,
        "The Data Uploads page allows manual upload of clinical documents (PDF, images) for "
        "Gemini Vision AI analysis. The AI extracts ICD-10 codes, HCC mappings, medications, "
        "lab results, and MEAT compliance evidence from uploaded documents.",
    )
    add_image(doc, "32_raf_data_uploads.png", "Data Uploads - Document upload and AI analysis interface")

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 13. Technical Architecture
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "13. Technical Architecture", level=1)

    add_heading(doc, "Data Flow", level=2)
    add_para(doc, "OpenEMR (EHR)  --->  FHIR R4 / OAuth2  --->  RAF Intelligence", bold=True, size=12)
    add_para(doc, "")

    add_heading(doc, "FHIR Resources Synced (9 Types)", level=2)
    add_table(
        doc,
        ["#", "FHIR Resource", "RAF Intelligence Destination", "Purpose"],
        [
            ["1", "Patient", "Demographics + RAF demographic scoring", "Patient identity and age/sex factors"],
            ["2", "Condition", "ICD-10 codes -> HCC crosswalk -> RAF", "Primary source for HCC conditions"],
            ["3", "Encounter", "Clinical analysis by Gemini AI", "Encounter-level AI analysis"],
            ["4", "MedicationRequest", "Medication-based suspect detection", "Drug-to-condition inference"],
            ["5", "Observation", "Lab-based suspect detection", "Abnormal value flagging"],
            ["6", "DiagnosticReport", "NLP analysis of conclusions", "Radiology/pathology insights"],
            ["7", "Immunization", "HEDIS quality measures", "Vaccine compliance tracking"],
            ["8", "AllergyIntolerance", "Safety alerts", "Drug interaction prevention"],
            ["9", "DocumentReference", "Gemini Vision document analysis", "PDF/image code extraction"],
        ],
    )
    add_para(doc, "")

    add_heading(doc, "Technology Stack", level=2)
    add_table(
        doc,
        ["Component", "Technology"],
        [
            ["Backend API", "Python / FastAPI"],
            ["Frontend", "Next.js / React / TypeScript"],
            ["AI Engine", "Google Gemini 2.5 Pro"],
            ["Database", "MySQL 8.0"],
            ["Task Queue", "Celery + Redis"],
            ["EHR Integration", "HL7 FHIR R4 + OAuth2"],
            ["Deployment", "Docker Compose"],
            ["Security", "JWT + RBAC + HIPAA Multi-tenant"],
        ],
    )

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════
    # 14. Key Takeaways
    # ════════════════════════════════════════════════════════════
    add_heading(doc, "14. Key Takeaways", level=1)

    takeaways = [
        (
            "Seamless EHR Integration",
            "Patient data flows automatically from any FHIR R4-compliant EHR via secure OAuth2 "
            "authentication. Supports OpenEMR, Epic, Cerner, and other major EHR platforms.",
        ),
        (
            "AI-Powered Clinical Analysis",
            "Google Gemini 2.5 Pro analyzes every clinical encounter to identify missed diagnoses, "
            "validate existing codes, and extract MEAT compliance evidence.",
        ),
        (
            "Accurate RAF Scoring",
            "CMS-HCC V24/V28 blended model with demographic, disease, and interaction scoring. "
            "Automatic hierarchy trumping ensures no inflated scores.",
        ),
        (
            "Comprehensive Patient View",
            "All clinical data -- conditions, encounters, medications, labs, immunizations, "
            "allergies -- unified in a single patient view with data quality tracking.",
        ),
        (
            "Actionable Intelligence",
            "Suspect conditions with confidence scoring, care gap identification, chart chase "
            "automation, and provider worklists drive measurable revenue optimization.",
        ),
        (
            "Enterprise Ready",
            "Multi-tenant architecture, HIPAA-compliant, role-based access control, audit logging, "
            "and webhook integration for enterprise deployment.",
        ),
    ]

    for title, desc in takeaways:
        add_heading(doc, title, level=2)
        add_para(doc, desc)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("--- End of Document ---")
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    run.italic = True

    # ── Save ──
    doc.save(str(OUT))
    print(f"Document saved to: {OUT}")
    print(f"File size: {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    build()
