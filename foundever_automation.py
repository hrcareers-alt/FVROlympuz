import os
import re
import datetime
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1NoRX955F0dpxMReiC-6lcd3hgxFDccS3H9hzabTQghE/edit"
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")

# Target Tabs
TARGET_TABS = ["MODERN TRACTION", "JOBSTREET", "VALID CONSENT - TP, FVR & EXL"]

# City to Job Link Mapping
CITY_JOB_LINKS = {
    "cebu": "https://jobs.foundever.com/job/Cebu-Cebu-Customer-Service-Associate-Phil/1345433100/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "cebu robinson": "https://jobs.foundever.com/job-invite/406350/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "tarlac": "https://jobs.foundever.com/job/Tarlac-Tarlac-Customer-Service-Associate-Phil/1345432700/?utm_source=SourcingOther&utm_campaign=EBELACSE",
    "pasig": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "mandaluyong": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "palawan": "https://jobs.foundever.com/job-invite/406352/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "makati": "https://jobs.foundever.com/job-invite/406349/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "baguio": "https://jobs.foundever.com/job/Baguio-Baguio-Customer-Service-Associate-Phil/1345433200/?utm_source=customcampaign&utm_campaign=NERP%20EBELACSE",
    "alabang": "https://jobs.foundever.com/job-invite/406346/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "quezon": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "manila": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "ncr": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff"
}

DEFAULT_LINK = CITY_JOB_LINKS["quezon"]

# These answers are the same on every Foundever questionnaire.
FIXED_FOUNDEVER_ANSWERS = {
    "preferred_work_setup": "On-Site",
    "employee_referral_name": "XRP - EDWARD BELACSE",
}

def get_job_link(city_str):
    if not city_str:
        return DEFAULT_LINK
    c = str(city_str).lower().strip()
    if c in ["philippines", "ph"]:
        return CITY_JOB_LINKS["quezon"]
    for key, link in CITY_JOB_LINKS.items():
        if key in c:
            return link
    # Regional Fallbacks
    if any(p in c for p in ["leyte", "bohol", "mindanao"]):
        return CITY_JOB_LINKS["cebu"]
    if any(p in c for p in ["ilocos", "pangasinan"]):
        return CITY_JOB_LINKS["baguio"]
    if any(p in c for p in ["central luzon", "zambales"]):
        return CITY_JOB_LINKS["tarlac"]
    if any(p in c for p in ["south luzon", "bicol"]):
        return CITY_JOB_LINKS["alabang"]
    return DEFAULT_LINK

def format_phone(phone_str):
    digits = re.sub(r'\D', '', str(phone_str))
    if digits.startswith("63"):
        return "+" + digits
    if digits.startswith("0"):
        return "+63" + digits[1:]
    if len(digits) == 10:
        return "+63" + digits
    return "+" + digits

def validate_email(email_str):
    email = str(email_str).strip()
    if "," in email or "@" not in email or email.endswith("g,ail.com"):
        return None
    return email

def setup_gspread():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_url(SHEET_URL)

def run_foundever_pipeline():
    doc = setup_gspread()
    existing_records = set()
    rows_to_process = []

    print("--- STEP 1: Scanning tabs and indexing existing applicants ---")
    for sheet_name in TARGET_TABS:
        ws = doc.worksheet(sheet_name)
        data = ws.get_all_values()
        if not data:
            continue
        
        headers = [h.strip() for h in data[0]]
        
        # Locate columns dynamically by header name
        fvr_col_idx = None
        for i, h in enumerate(headers):
            if "foundever" in h.lower() or h.lower() == "fvr":
                fvr_col_idx = i
                break

        pref_col_idx = next((i for i, h in enumerate(headers) if "preferred company" in h.lower() or "endorse to" in h.lower()), None)
        email_col_idx = next((i for i, h in enumerate(headers) if "email" in h.lower()), None)
        phone_col_idx = next((i for i, h in enumerate(headers) if "mobile" in h.lower() or "phone" in h.lower()), None)
        first_col_idx = next((i for i, h in enumerate(headers) if "first" in h.lower()), None)
        last_col_idx = next((i for i, h in enumerate(headers) if "last" in h.lower()), None)
        city_col_idx = next((i for i, h in enumerate(headers) if h.lower() in ["city", "location"]), None)
        dob_col_idx = next((i for i, h in enumerate(headers) if "birthdate" in h.lower()), None)
        bpo_col_idx = next((i for i, h in enumerate(headers) if "bpo" in h.lower()), None)
        edu_col_idx = next((i for i, h in enumerate(headers) if "education" in h.lower()), None)

        for row_idx, row in enumerate(data[1:], start=2):
            fvr_remark = row[fvr_col_idx].strip() if fvr_col_idx is not None and len(row) > fvr_col_idx else ""
            email = row[email_col_idx].strip().lower() if email_col_idx is not None and len(row) > email_col_idx else ""
            phone = row[phone_col_idx].strip() if phone_col_idx is not None and len(row) > phone_col_idx else ""
            first = row[first_col_idx].strip().lower() if first_col_idx is not None and len(row) > first_col_idx else ""
            last = row[last_col_idx].strip().lower() if last_col_idx is not None and len(row) > last_col_idx else ""
            full_name = f"{first} {last}"

            # Track duplicates
            if fvr_remark:
                if email: existing_records.add(email)
                if phone: existing_records.add(phone)
                if full_name.strip(): existing_records.add(full_name)
            else:
                rows_to_process.append({
                    'worksheet': ws,
                    'row_idx': row_idx,
                    'fvr_col_idx': fvr_col_idx + 1,
                    'first_name': row[first_col_idx].strip() if first_col_idx is not None else "",
                    'last_name': row[last_col_idx].strip() if last_col_idx is not None else "",
                    'email': row[email_col_idx].strip() if email_col_idx is not None else "",
                    'phone': row[phone_col_idx].strip() if phone_col_idx is not None else "",
                    'city': row[city_col_idx].strip() if city_col_idx is not None else "",
                    'pref': row[pref_col_idx].strip() if pref_col_idx is not None else "",
                    'dob': row[dob_col_idx].strip() if dob_col_idx is not None else "",
                    'bpo': row[bpo_col_idx].strip() if bpo_col_idx is not None else "",
                    'edu': row[edu_col_idx].strip() if edu_col_idx is not None else "",
                })

    print(f"Found {len(rows_to_process)} candidate rows for processing.")

    for candidate in rows_to_process:
        ws = candidate['worksheet']
        r_idx = candidate['row_idx']
        c_idx = candidate['fvr_col_idx']

        # Double check cell isn't filled
        current_val = ws.cell(r_idx, c_idx).value or ""
        if current_val.strip():
            continue

        pref = candidate['pref'].lower()
        if "foundever" not in pref and "all of the above" not in pref:
            ws.update_cell(r_idx, c_idx, "Executive Team / N")
            print(f"Row {r_idx} ({ws.title}): Not interested in Foundever -> Executive Team / N")
            continue

        email = validate_email(candidate['email'])
        phone = candidate['phone']
        full_name = f"{candidate['first_name']} {candidate['last_name']}".strip().lower()

        if not email:
            print(f"Row {r_idx} ({ws.title}): Invalid email format -> Skipped for review")
            continue

        if email.lower() in existing_records or phone in existing_records or full_name in existing_records:
            ws.update_cell(r_idx, c_idx, "Existing Applicant")
            print(f"Row {r_idx} ({ws.title}): Duplicate detected -> Existing Applicant")
            continue

        if candidate['city'].lower() in ["n/a", "na", "abroad"]:
            ws.update_cell(r_idx, c_idx, "INVALID")
            print(f"Row {r_idx} ({ws.title}): Invalid/Abroad location -> INVALID")
            continue

        # The Foundever questionnaire is filled on the Maki assessment.
        # Do not stamp the sheet as submitted until that questionnaire is confirmed.
        job_url = get_job_link(candidate['city'])
        print(
            f"Row {r_idx} ({ws.title}): {candidate['first_name']} {candidate['last_name']} "
            f"is ready for the Foundever questionnaire at {job_url}. "
            f"Work setup {FIXED_FOUNDEVER_ANSWERS['preferred_work_setup']}. "
            f"Referral {FIXED_FOUNDEVER_ANSWERS['employee_referral_name']}. "
            "Sheet left blank for review."
        )

if __name__ == "__main__":
    run_foundever_pipeline()
