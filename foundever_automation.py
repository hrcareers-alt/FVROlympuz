import json
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime

import gspread
import requests
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from philippine_places import BARE_CITY_CORES, norm_place, resolve_place

# Hourly runner: Asia/Manila minute :09, 8:09 AM through 12:09 AM.
# 1:09 AM through 7:09 AM are outside that window (see scripts/install_cron.sh).

SHEET_URL = "https://docs.google.com/spreadsheets/d/1NoRX955F0dpxMReiC-6lcd3hgxFDccS3H9hzabTQghE/edit"
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
TARGET_TABS = ["MODERN TRACTION", "JOBSTREET", "VALID CONSENT - TP, FVR & EXL"]
GQL = "https://backend.makipeople.com/v1/graphql"
MANILA_INVITATION = "1935866c-ed92-42cd-8ef8-7308dc96048c"
RUN_LOG = os.path.expanduser("~/.config/fvrolympuz/foundever_run.jsonl")
KNOCKOUT_LOG = os.path.expanduser("~/.config/fvrolympuz/foundever_knockouts.txt")

# Standing answers for every Foundever questionnaire.
REFERRAL_NAME = "XRP - Edward Belacse"
WORK_SETUP = "On-Site"

CITY_JOB_LINKS = {
    "cebu robinson": "https://jobs.foundever.com/job-invite/406350/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "cebu": "https://jobs.foundever.com/job/Cebu-Cebu-Customer-Service-Associate-Phil/1345433100/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "tarlac": "https://jobs.foundever.com/job/Tarlac-Tarlac-Customer-Service-Associate-Phil/1345432700/?utm_source=SourcingOther&utm_campaign=EBELACSE",
    "pasig": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "mandaluyong": "https://jobs.foundever.com/job-invite/406345/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "palawan": "https://jobs.foundever.com/job-invite/406352/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "makati": "https://jobs.foundever.com/job-invite/406349/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "baguio": "https://jobs.foundever.com/job/Baguio-Baguio-Customer-Service-Associate-Phil/1345433200/?utm_source=customcampaign&utm_campaign=NERP%20EBELACSE",
    "alabang": "https://jobs.foundever.com/job-invite/406346/?utm_source=OutsourcedStaff&utm_campaign=XRPBelacse",
    "quezon": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "manila": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
    "ncr": "https://jobs.foundever.com/job/Manila-NCR-Customer-Service-Associate-Phil/1345432200/?utm_campaign=XRPBelacse&utm_source=OutsourcedStaff",
}
DEFAULT_LINK = CITY_JOB_LINKS["quezon"]

# City label -> (region label, zip). Zips are the city or provincial-capital code.
# The sheet has no zip column, and the questionnaire requires one.
PLACE_GROUPS = [
    ("National Capital Region (NCR)", [
        ("City of Caloocan", "1400"), ("City of Las Piñas", "1740"), ("City of Makati", "1200"),
        ("City of Malabon", "1470"), ("City of Mandaluyong", "1550"), ("City of Manila", "1000"),
        ("City of Marikina", "1800"), ("City of Muntinlupa", "1770"), ("City of Navotas", "1485"),
        ("City of Parañaque", "1700"), ("City of Pasig", "1600"), ("City of San Juan", "1500"),
        ("City of Taguig", "1630"), ("City of Valenzuela", "1440"), ("Pasay City", "1300"),
        ("Pateros", "1620"), ("Quezon City", "1100"),
    ]),
    ("Cordillera Administrative Region (CAR)", [
        ("Abra", "2800"), ("Apayao", "3813"), ("Benguet", "2601"), ("City of Baguio", "2600"),
        ("Ifugao", "3600"), ("Kalinga", "3800"), ("Mountain Province", "2616"),
    ]),
    ("Region I (Ilocos Region)", [
        ("Ilocos Norte", "2900"), ("Ilocos Sur", "2700"), ("La Union", "2500"), ("Pangasinan", "2400"),
    ]),
    ("Region II (Cagayan Valley)", [
        ("Batanes", "3900"), ("Cagayan", "3500"), ("Isabela", "3300"), ("Nueva Vizcaya", "3700"), ("Quirino", "3400"),
    ]),
    ("Region III (Central Luzon)", [
        ("Aurora", "3200"), ("Bataan", "2100"), ("Bulacan", "3000"), ("City of Angeles", "2009"),
        ("City of Olongapo", "2200"), ("Nueva Ecija", "3100"), ("Pampanga", "2000"), ("Tarlac", "2300"), ("Zambales", "2207"),
    ]),
    ("Region IV-A (CALABARZON)", [
        ("Batangas", "4200"), ("Cavite", "4100"), ("City of Lucena", "4301"), ("Laguna", "4000"),
        ("Quezon", "4301"), ("Rizal", "1870"),
    ]),
    ("MIMAROPA Region", [
        ("City of Puerto Princesa", "5300"), ("Marinduque", "4900"), ("Occidental Mindoro", "5100"),
        ("Oriental Mindoro", "5200"), ("Palawan", "5300"), ("Romblon", "5500"),
    ]),
    ("Region V (Bicol Region)", [
        ("Albay", "4500"), ("Camarines Norte", "4600"), ("Camarines Sur", "4400"),
        ("Catanduanes", "4800"), ("Masbate", "5400"), ("Sorsogon", "4700"),
    ]),
    ("Region VI (Western Visayas)", [
        ("Aklan", "5600"), ("Antique", "5700"), ("Capiz", "5800"), ("City of Iloilo", "5000"),
        ("Guimaras", "5045"), ("Iloilo", "5000"),
    ]),
    ("Negros Island Region (NIR)", [
        ("City of Bacolod", "6100"), ("Negros Occidental", "6100"), ("Negros Oriental", "6200"), ("Siquijor", "6225"),
    ]),
    ("Region VII (Central Visayas)", [
        ("Bohol", "6300"), ("Cebu", "6000"), ("City of Cebu", "6000"), ("City of Lapu-Lapu", "6015"), ("City of Mandaue", "6014"),
    ]),
    ("Region VIII (Eastern Visayas)", [
        ("Biliran", "6543"), ("City of Tacloban", "6500"), ("Eastern Samar", "6800"), ("Leyte", "6500"),
        ("Northern Samar", "6400"), ("Samar", "6700"), ("Southern Leyte", "6600"),
    ]),
    ("Region IX (Zamboanga Peninsula)", [
        ("City of Isabela", "7300"), ("City of Zamboanga", "7000"), ("Zamboanga del Norte", "7100"),
        ("Zamboanga del Sur", "7016"), ("Zamboanga Sibugay", "7001"),
    ]),
    ("Region X (Northern Mindanao)", [
        ("Bukidnon", "8700"), ("Camiguin", "9100"), ("City of Cagayan de Oro", "9000"), ("City of Iligan", "9200"),
        ("Lanao del Norte", "9200"), ("Misamis Occidental", "7200"), ("Misamis Oriental", "9000"),
    ]),
    ("Region XI (Davao Region)", [
        ("City of Davao", "8000"), ("Davao del Norte", "8100"), ("Davao del Sur", "8002"),
        ("Davao de Oro", "8800"), ("Davao Occidental", "8016"), ("Davao Oriental", "8200"),
    ]),
    ("Region XII (SOCCSKSARGEN)", [
        ("City of General Santos", "9500"), ("Cotabato", "9400"), ("Sarangani", "9501"),
        ("South Cotabato", "9506"), ("Sultan Kudarat", "9800"),
    ]),
    ("Region XIII (Caraga)", [
        ("Agusan del Norte", "8600"), ("Agusan del Sur", "8500"), ("City of Butuan", "8600"),
        ("Dinagat Islands", "8412"), ("Surigao del Norte", "8400"), ("Surigao del Sur", "8300"),
    ]),
    ("Bangsamoro Autonomous Region in Muslim Mindanao (BARMM)", [
        ("BARMM Special Geographic Area", "9600"), ("Basilan", "7300"), ("Lanao del Sur", "9700"),
        ("Maguindanao del Norte", "9600"), ("Maguindanao del Sur", "9601"), ("Sulu", "7400"), ("Tawi-Tawi", "7500"),
    ]),
]

# Sheet typos and short forms that are not official PSGC names.
_PLACE_REWRITES = (
    ("cagayab de oro", "cagayan de oro"),
    ("angeles coty", "angeles"),
    ("gen santos", "general santos"),
    ("e samar", "eastern samar"),
    ("camrines", "camarines"),
    ("bukindon", "bukidnon"),
    ("rodriquez", "rodriguez"),
    ("montalban", "rodriguez"),
    ("gensan", "general santos"),
    ("cdo", "cagayan de oro"),
    ("alabang", "muntinlupa"),
)


def _norm_place(value):
    return norm_place(value)


def _is_city_label(label):
    return label.startswith("City of") or label.endswith(" City") or label == "Pateros"


def _prepare_place(raw):
    said_city = bool(re.search(r"\bcity\b", str(raw or ""), flags=re.IGNORECASE))
    sheet = _norm_place(raw)
    ncr = False
    if sheet in {"metro manila", "qc"}:
        return "quezon city", said_city, False
    if "metro manila" in sheet:
        ncr = True
        sheet = re.sub(r"(^| )metro manila( |$)", " ", sheet)
    sheet = re.sub(r"\b(brgy|barangay|bgy)\b", " ", sheet)
    for source, target in _PLACE_REWRITES:
        sheet = re.sub(
            rf"(^| ){re.escape(source)}( |$)",
            lambda match, replacement=target: f"{match.group(1)}{replacement}{match.group(2)}",
            sheet,
        )
    sheet = re.sub(r"(^| )sta( |$)", r"\1santa\2", sheet)
    sheet = re.sub(r"(^| )sto( |$)", r"\1santo\2", sheet)
    sheet = re.sub(r"(^| )qc( |$)", r"\1quezon city\2", sheet)
    sheet = re.sub(r"\s+", " ", sheet).strip()
    if not sheet and ncr:
        return "quezon city", said_city, False
    return sheet, said_city, ncr


def _place_index():
    index = {}
    for region, cities in PLACE_GROUPS:
        for label, zip_code in cities:
            index[label] = {"region": region, "zip": zip_code, "norm": _norm_place(label)}
    return index


PLACE_INDEX = _place_index()


def _direct_match(sheet, said_city):
    best = None
    best_key = None
    for label, info in PLACE_INDEX.items():
        label_norm = info["norm"]
        if not label_norm:
            continue
        exact = sheet == label_norm
        if exact:
            score = 2000 + len(label_norm)
        elif re.search(rf"(^| ){re.escape(label_norm)}( |$)", sheet):
            score = 1000 + len(label_norm)
        else:
            continue
        city = _is_city_label(label)
        if exact and (said_city or label_norm in BARE_CITY_CORES):
            city_pref = 1 if city else 0
        elif exact:
            city_pref = 0 if city else 1
        else:
            city_pref = -1 if city else 0
        key = (score, city_pref, len(label))
        if best_key is None or key > best_key:
            best_key = key
            best = label
    return best


def _choose_label(sheet, direct, found):
    if found.blocked:
        return None
    if found.ambiguous:
        if not direct or not found.core:
            return None
        direct_norm = PLACE_INDEX[direct]["norm"]
        if direct_norm == found.core:
            return None
        return direct
    psgc = found.label
    if psgc and direct:
        if psgc == direct:
            return direct
        direct_norm = PLACE_INDEX[direct]["norm"]
        psgc_norm = PLACE_INDEX[psgc]["norm"]
        if sheet == direct_norm:
            return direct
        if sheet == psgc_norm:
            return psgc
        if _is_city_label(psgc) and not _is_city_label(direct):
            if psgc_norm and direct_norm.startswith(psgc_norm + " "):
                return direct
            return psgc
        if len(direct_norm) >= len(psgc_norm):
            return direct
        return psgc
    return psgc or direct


def match_place(raw):
    """Return (label, region, zip) for a sheet location, or None."""
    sheet, said_city, ncr = _prepare_place(raw)
    if not sheet:
        return None
    direct = _direct_match(sheet, said_city)
    found = resolve_place(sheet, list(PLACE_INDEX), said_city=said_city, ncr_only=ncr)
    chosen = _choose_label(sheet, direct, found)
    if not chosen:
        return None
    info = PLACE_INDEX[chosen]
    return chosen, info["region"], info["zip"]


def get_job_link(city_str):
    if not city_str:
        return DEFAULT_LINK
    c = str(city_str).lower().strip()
    if c in ["philippines", "ph"]:
        return CITY_JOB_LINKS["quezon"]
    for key, link in CITY_JOB_LINKS.items():
        if key in c:
            return link
    if any(p in c for p in ["leyte", "bohol", "mindanao"]):
        return CITY_JOB_LINKS["cebu"]
    if any(p in c for p in ["ilocos", "pangasinan"]):
        return CITY_JOB_LINKS["baguio"]
    if any(p in c for p in ["central luzon", "zambales"]):
        return CITY_JOB_LINKS["tarlac"]
    if any(p in c for p in ["south luzon", "bicol"]):
        return CITY_JOB_LINKS["alabang"]
    return DEFAULT_LINK


def local_phone(phone_str):
    digits = re.sub(r"\D", "", str(phone_str or ""))
    if digits.startswith("63"):
        digits = digits[2:]
    digits = digits.lstrip("0")
    if len(digits) == 10 and digits.startswith("9"):
        return "0" + digits
    return None


def phone_key(phone_str):
    local = local_phone(phone_str)
    return local[-10:] if local else ""


def validate_email(email_str):
    email = str(email_str or "").strip()
    if not email or any(ch in email for ch in " ,;/"):
        return None
    # Require a domain label before the dot so values like name@.gmail.com are held for review.
    if not re.fullmatch(r"[^@\s]+@[^@\s.][^@\s]*\.[^@\s]+", email):
        return None
    return email


def parse_dob(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def age_on(born, today):
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def map_education(edu, birth_year):
    text = re.sub(r"\s+", " ", str(edu or "").strip().lower().replace("’", "'"))
    k12 = birth_year is None or birth_year >= 1999
    undergrad = "College undergraduate (K-12 Curriculum)" if k12 else "College Undergraduate (Old HS Curriculum)"
    high_school = (
        "High school diploma or equivalent (K-12 Curriculum)"
        if k12
        else "Highschool Diploma or equivalent (Old HS Curriculum)"
    )
    year = None
    for word in ("1st", "2nd", "3rd", "4th", "5th"):
        if word in text:
            year = f"{word} Year College level Completed"
            break
    if text in {"college graduate", "bachelor's degree", "bachelors degree", "college education"}:
        return "Bachelor's degree or equivalent", "4th Year College level Completed", "Not Applicable"
    if "college" in text and "undergrad" in text or text == "college":
        return undergrad, year or "Not Applicable", "Not Applicable"
    if "associate" in text and "computer" in text:
        return "Some College or Associate/ Trade Degree", "2nd Year College level Completed", "Other Technology"
    if any(word in text for word in ("associate", "vocational", "tesda")):
        return "Some College or Associate/ Trade Degree", year or "Not Applicable", "Not Applicable"
    if "old curriculum" in text:
        return "Highschool Diploma or equivalent (Old HS Curriculum)", "Not Applicable", "Not Applicable"
    if "als" in text:
        return "Highschool Diploma or equivalent", "Not Applicable", "Not Applicable"
    if "shs" in text or "senior high" in text:
        return "Senior Highschool", "Not Applicable", "Not Applicable"
    if "high school" in text:
        return high_school, "Not Applicable", "Not Applicable"
    if text in {"others", "other"}:
        return "Other higher level of education", "Not Applicable", "Not Applicable"
    if "master" in text:
        return "Master's degree or equivalent", "Not Applicable", "Not Applicable"
    if "doctor" in text:
        return "Doctorate degree or equivalent", "Not Applicable", "Not Applicable"
    return None


def map_bpo(bpo):
    text = re.sub(r"\s+", " ", str(bpo or "").strip().lower())
    if text in {"", "none", "n/a", "na", "no", "no experience", "fresh graduate"}:
        return "Not Applicable", "No Call Center Experience", "Not Applicable"
    if any(token in text for token in ("1 - 5", "1-5", "1 to 5")):
        duration = "1 to 6 Months"
    elif any(token in text for token in ("6 - 11", "6-11", "6 to 11")):
        duration = "6 Months to 1 Year"
    elif "1 year" in text:
        duration = "Over 1 Year"
    elif any(token in text for token in ("2 year", "3 year", "4 year", "5 year")):
        duration = "Over 2 Years"
    else:
        return None
    return (
        "Call Center - Voice (Local and International Account)",
        duration,
        "Customer Service",
    )


def site_label(question_name, city_label, job_url):
    if question_name == "site_preference_ncr":
        if city_label == "City of Pasig":
            return "Technopoint (Pasig City)"
        if city_label == "City of Mandaluyong":
            return "Pioneer (Mandaluyong City)"
        return "ETON (Quezon City)"
    if question_name == "site_preference_cebu":
        if "406350" in (job_url or "") or "robinson" in (job_url or "").lower():
            return "Robinson's Galleria Center"
        return "Foundever Hub - Cybergate Galleria Center"
    return None


def _label_en(value):
    if isinstance(value, dict):
        return value.get("en") or next(iter(value.values()), "")
    return value or ""


class Maki:
    def __init__(self):
        self.http = requests.Session()
        self.invitations = {}
        self.schemas = {}
        self.legal_ids = {}

    def gql(self, token, query, variables=None, operation=None):
        body = {"query": query}
        if variables is not None:
            body["variables"] = variables
        if operation:
            body["operationName"] = operation
        headers = {
            "content-type": "application/json",
            "origin": "https://candidates.makipeople.com",
            "x-hasura-instance-token": token,
            "x-hasura-assessment-instance-token": token,
        }
        last_error = None
        for attempt in range(4):
            try:
                response = self.http.post(GQL, headers=headers, json=body, timeout=45)
                if response.status_code >= 500:
                    raise RuntimeError(f"HTTP {response.status_code}")
                payload = response.json()
                if payload.get("errors"):
                    raise RuntimeError(json.dumps(payload["errors"])[:500])
                return payload["data"]
            except Exception as exc:
                last_error = exc
                time.sleep(1.2 * (attempt + 1))
        raise last_error

    def invitation_token(self, job_url):
        if job_url in self.invitations:
            return self.invitations[job_url]
        token = None
        try:
            html = self.http.get(job_url, timeout=30, headers={"user-agent": "Mozilla/5.0"}).text
            found = re.findall(r"candidates\.makipeople\.com/([0-9a-f-]{36})/invitation", html)
            if found:
                token = found[0]
        except Exception as exc:
            print(f"Job page lookup failed for {job_url}: {exc}")
        if not token:
            print(f"No Maki invitation on the job page. Using the Manila assessment for {job_url}")
            token = MANILA_INVITATION
        self.invitations[job_url] = token
        return token

    def schema(self, token):
        if token in self.schemas:
            return self.schemas[token]
        data = self.gql(
            token,
            """
            query AdminSchema {
              assessments_admin_questions(order_by: {position: asc}) {
                is_required
                admin_question {
                  id
                  name
                  format
                  admin_question_answers(order_by: {order: asc}) { id label }
                }
              }
            }
            """,
            operation="AdminSchema",
        )
        questions = []
        for row in data["assessments_admin_questions"]:
            question = row["admin_question"]
            answers = {}
            for answer in question.get("admin_question_answers") or []:
                answers[_label_en(answer.get("label"))] = answer["id"]
            questions.append({
                "id": question["id"],
                "name": question["name"],
                "format": question["format"],
                "required": row["is_required"],
                "answers": answers,
            })
        self.schemas[token] = questions
        return questions

    def legal_document_ids(self, token):
        if token in self.legal_ids:
            return self.legal_ids[token]
        data = self.gql(
            token,
            "query Legal { candidate_legal_documents { id type } }",
            operation="Legal",
        )
        ids = [row["id"] for row in data["candidate_legal_documents"]]
        if len(ids) < 2:
            raise RuntimeError("Maki did not return the candidate legal documents.")
        self.legal_ids[token] = ids
        return ids

    def invite(self, invitation, candidate):
        data = self.gql(
            invitation,
            """
            mutation inviteCandidateFromMagicLink(
              $email: String, $firstName: String, $lastName: String,
              $linkToken: uuid!, $legalDocumentIds: [uuid!]!, $language: String
            ) {
              inviteCandidateFromMagicLink(
                email: $email
                first_name: $firstName
                last_name: $lastName
                link_token: $linkToken
                legal_document_ids: $legalDocumentIds
                language: $language
              ) {
                assessment_instance_link
                already_applied
              }
            }
            """,
            {
                "email": candidate["email"],
                "firstName": candidate["first_name"],
                "lastName": candidate["last_name"],
                "linkToken": invitation,
                "legalDocumentIds": self.legal_document_ids(invitation),
                "language": "en",
            },
            operation="inviteCandidateFromMagicLink",
        )
        return data["inviteCandidateFromMagicLink"]

    def submit(self, instance_token, answers):
        data = self.gql(
            instance_token,
            """
            mutation submitAdminQuestionAnswers($answers: [AdminQuestionAnswerInput!]!) {
              submitAdminQuestionAnswers(answers: $answers) { success knockOutReason }
            }
            """,
            {"answers": answers},
            operation="submitAdminQuestionAnswers",
        )
        return data["submitAdminQuestionAnswers"]

    def stored(self, instance_token):
        data = self.gql(
            instance_token,
            """
            query Stored {
              assessments_instances {
                admin_questions_completed_at
                stage
                identity { user { email first_name last_name } }
                assessment {
                  assessments_admin_questions(order_by: {position: asc}) {
                    admin_question {
                      id
                      name
                      format
                      assessment_instances_admin_questions {
                        assessment_instances_admin_question_answers {
                          admin_question_answer { id label }
                          text_answer
                          date_answer
                          country_answer
                        }
                      }
                    }
                  }
                }
              }
            }
            """,
            operation="Stored",
        )
        instances = data["assessments_instances"]
        return instances[0] if instances else None


def answer_id(question, label):
    answers = question["answers"]
    if label in answers:
        return answers[label]
    folded = {key.lower(): value for key, value in answers.items()}
    if label.lower() in folded:
        return folded[label.lower()]
    raise KeyError(f"{question['name']} has no option {label}")


def build_answers(schema, candidate):
    education = map_education(candidate["edu"], candidate["birth"].year if candidate["birth"] else None)
    experience = map_bpo(candidate["bpo"])
    if not education:
        raise ValueError(f"unmapped education {candidate['edu']!r}")
    if not experience:
        raise ValueError(f"unmapped BPO experience {candidate['bpo']!r}")
    edu_label, college_label, major_label = education
    industry_label, call_label, call_type_label = experience
    place = candidate["place"]
    address = re.sub(r"\s+", " ", candidate["city"]).strip().upper()
    signature = f"{candidate['first_name']} {candidate['last_name']}".strip()
    choices = {
        "state": place[1],
        "current_city": place[0],
        "highest_education_level": edu_label,
        "college_level": college_label,
        "college_major": major_label,
        "industry_experience": industry_label,
        "call_center_experience": call_label,
        "call_center_experience_type": call_type_label,
        "position_type_preference": "Full-time",
        "preferred_work_setup": WORK_SETUP,
        "previous_employment_status": "Never Employed at this Company",
        "filipino_citizen": "Yes",
        "age_18_or_older": "Yes",
        "gender": "Prefer not to say",
        "employment_application_consent": "Yes",
        "foundever_notifications_consent": "Yes",
    }
    texts = {
        "cell_phone": candidate["local_phone"],
        "alternate_phone": candidate["local_phone"],
        "current_address": address,
        "zip": place[2],
        "city": place[0].upper(),
        "street_address": address,
        "employee_referral_name": REFERRAL_NAME,
        "electronic_consent_agreement": signature,
    }
    payload = []
    for question in schema:
        name = question["name"]
        fmt = question["format"]
        if name.startswith("site_preference"):
            label = site_label(name, place[0], candidate["job_url"])
            if not label:
                label = next(iter(question["answers"]))
            payload.append({"admin_question_id": question["id"], "answer_ids": [answer_id(question, label)]})
            continue
        if name in choices:
            payload.append({"admin_question_id": question["id"], "answer_ids": [answer_id(question, choices[name])]})
            continue
        if name == "country":
            payload.append({"admin_question_id": question["id"], "country": "PHL"})
            continue
        if name == "date_of_birth":
            payload.append({
                "admin_question_id": question["id"],
                "date_answer": f"{candidate['birth'].isoformat()}T00:00:00+00:00",
            })
            continue
        if name in texts:
            payload.append({"admin_question_id": question["id"], "text_answer": texts[name]})
            continue
        if question["required"]:
            raise ValueError(f"no answer for required question {name}")
    return payload


def stored_map(instance):
    found = {}
    for row in instance["assessment"]["assessments_admin_questions"]:
        question = row["admin_question"]
        values = []
        for block in question.get("assessment_instances_admin_questions") or []:
            for answer in block.get("assessment_instances_admin_question_answers") or []:
                label = _label_en((answer.get("admin_question_answer") or {}).get("label"))
                values.append(label or answer.get("text_answer") or answer.get("country_answer") or answer.get("date_answer"))
        found[question["name"]] = values
    return found


def payload_from_stored(instance, schema):
    by_name = {question["name"]: question for question in schema}
    payload = []
    for row in instance["assessment"]["assessments_admin_questions"]:
        question = row["admin_question"]
        ids = []
        text = date_answer = country = None
        for block in question.get("assessment_instances_admin_questions") or []:
            for answer in block.get("assessment_instances_admin_question_answers") or []:
                if answer.get("admin_question_answer"):
                    ids.append(answer["admin_question_answer"]["id"])
                if answer.get("text_answer"):
                    text = answer["text_answer"]
                if answer.get("date_answer"):
                    date_answer = answer["date_answer"]
                if answer.get("country_answer"):
                    country = answer["country_answer"]
        name = question["name"]
        fmt = question["format"]
        if name == "employee_referral_name":
            text = REFERRAL_NAME
        if name == "preferred_work_setup":
            ids = [answer_id(by_name[name], WORK_SETUP)]
        if fmt in {"single_choice", "multiple_choice"} and ids:
            payload.append({"admin_question_id": question["id"], "answer_ids": ids})
        elif fmt == "text_answer" and text:
            payload.append({"admin_question_id": question["id"], "text_answer": text})
        elif fmt == "date_answer" and date_answer:
            payload.append({"admin_question_id": question["id"], "date_answer": date_answer})
        elif fmt == "country" and country:
            payload.append({"admin_question_id": question["id"], "country": country})
    return payload


def fixed_answers_ok(instance):
    found = stored_map(instance)
    referral = (found.get("employee_referral_name") or [None])[0]
    setup = (found.get("preferred_work_setup") or [None])[0]
    return referral == REFERRAL_NAME and setup == WORK_SETUP


def find_header(headers, predicate):
    for index, header in enumerate(headers):
        if predicate(header.strip().lower()):
            return index
    return None


def preference_column(headers, rows):
    """Preferred-company column. Modern Traction's header was cleared, but the values remain."""
    named = find_header(headers, lambda h: "preferred bpo" in h or "endorse to" in h)
    if named is not None:
        return named
    work_idx = find_header(headers, lambda h: "work set" in h)
    if work_idx is None or work_idx == 0 or headers[work_idx - 1].strip():
        return None
    blank_idx = work_idx - 1
    for row in rows[1:40]:
        if blank_idx >= len(row):
            continue
        sample = row[blank_idx].lower()
        if any(token in sample for token in ("foundever", "all of the above", "transcom", "concentrix", "teleperformance")):
            return blank_idx
    return None


def setup_gspread():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds).open_by_url(SHEET_URL)


def load_candidates(doc):
    existing = set()
    ready = []
    remarks = []
    skipped = []
    today = date.today()

    for sheet_name in TARGET_TABS:
        worksheet = doc.worksheet(sheet_name)
        data = worksheet.get_all_values()
        if not data:
            continue
        headers = [header.strip() for header in data[0]]
        lowered = [header.lower() for header in headers]
        fvr_idx = find_header(headers, lambda h: h in {"foundever", "fvr"})
        pref_idx = preference_column(headers, data)
        email_idx = find_header(headers, lambda h: "email" in h and "address" not in h)
        phone_idx = find_header(headers, lambda h: "mobile" in h or "phone" in h or "contact" in h)
        first_idx = find_header(headers, lambda h: h == "first name")
        last_idx = find_header(headers, lambda h: h == "last name")
        city_idx = find_header(headers, lambda h: "city" in h or h == "location")
        dob_idx = find_header(headers, lambda h: "birthdate" in h)
        bpo_idx = find_header(headers, lambda h: ("bpo" in h or "callcenter" in h or "call center" in h) and "preferred" not in h and "endorse" not in h)
        edu_idx = find_header(headers, lambda h: "educat" in h)
        required = {
            "foundever": fvr_idx, "preference": pref_idx, "email": email_idx, "phone": phone_idx,
            "first": first_idx, "last": last_idx, "city": city_idx, "birthdate": dob_idx,
            "bpo": bpo_idx, "education": edu_idx,
        }
        missing = [name for name, index in required.items() if index is None]
        if missing:
            raise RuntimeError(f"{sheet_name} is missing columns: {', '.join(missing)}")
        print(
            f"{sheet_name}: preference={headers[pref_idx]!r} phone={headers[phone_idx]!r} "
            f"city={headers[city_idx]!r} education={headers[edu_idx]!r}"
        )

        def cell(row, index):
            return row[index].strip() if index < len(row) else ""

        for row_number, row in enumerate(data[1:], start=2):
            remark = cell(row, fvr_idx)
            email = cell(row, email_idx).lower()
            phone = phone_key(cell(row, phone_idx))
            full_name = f"{cell(row, first_idx)} {cell(row, last_idx)}".strip().lower()
            if remark:
                # A not-interested or invalid row is not an existing Foundever application.
                if remark.strip().lower() not in {"executive team / n", "invalid", "no", "n"}:
                    if email:
                        existing.add(("email", email))
                    if phone:
                        existing.add(("phone", phone))
                    if full_name:
                        existing.add(("name", full_name))
                continue
            if not cell(row, first_idx) and not cell(row, last_idx) and not email:
                continue
            preference = cell(row, pref_idx).lower()
            interested = "foundever" in preference or "all of the above" in preference
            target = (worksheet, row_number, fvr_idx + 1)
            if not interested:
                remarks.append((*target, "Executive Team / N"))
                continue
            record = {
                "worksheet": worksheet,
                "sheet": sheet_name,
                "row": row_number,
                "col": fvr_idx + 1,
                "first_name": cell(row, first_idx),
                "last_name": cell(row, last_idx),
                "email": cell(row, email_idx),
                "phone": cell(row, phone_idx),
                "city": cell(row, city_idx),
                "pref": cell(row, pref_idx),
                "dob": cell(row, dob_idx),
                "bpo": cell(row, bpo_idx),
                "edu": cell(row, edu_idx),
            }
            valid_email = validate_email(record["email"])
            if not valid_email:
                skipped.append((sheet_name, row_number, "invalid email", record["email"]))
                continue
            record["email"] = valid_email
            keys = [("email", valid_email.lower())]
            if phone:
                keys.append(("phone", phone))
            if full_name:
                keys.append(("name", full_name))
            if any(key in existing for key in keys):
                remarks.append((*target, "Existing Applicant"))
                continue
            for key in keys:
                existing.add(key)
            if record["city"].strip().lower() in {"n/a", "na", "abroad"}:
                remarks.append((*target, "INVALID"))
                continue
            place = match_place(record["city"])
            if not place:
                city_text = record["city"] or ""
                if not re.search(r"[a-zA-Z]", city_text) or re.fullmatch(r"[A-Za-z]\d+", city_text.strip()):
                    remarks.append((*target, "INVALID"))
                else:
                    skipped.append((sheet_name, row_number, "unmatched city", record["city"]))
                continue
            birth = parse_dob(record["dob"])
            if not birth or not (16 <= age_on(birth, today) <= 100):
                skipped.append((sheet_name, row_number, "unusable birthdate", record["dob"]))
                continue
            if age_on(birth, today) < 18:
                skipped.append((sheet_name, row_number, "under 18", record["dob"]))
                continue
            local = local_phone(record["phone"])
            if not local:
                skipped.append((sheet_name, row_number, "unusable phone", record["phone"]))
                continue
            if not map_education(record["edu"], birth.year):
                skipped.append((sheet_name, row_number, "unmapped education", record["edu"]))
                continue
            if not map_bpo(record["bpo"]):
                skipped.append((sheet_name, row_number, "unmapped bpo", record["bpo"]))
                continue
            record["birth"] = birth
            record["local_phone"] = local
            record["place"] = place
            record["job_url"] = get_job_link(record["city"])
            ready.append(record)
    return ready, remarks, skipped


def write_remarks(items):
    grouped = defaultdict(list)
    sheets = {}
    for worksheet, row, col, value in items:
        sheets[worksheet.title] = worksheet
        grouped[worksheet.title].append({"range": rowcol_to_a1(row, col), "values": [[value]]})
    for title, cells in grouped.items():
        for offset in range(0, len(cells), 80):
            chunk = cells[offset:offset + 80]
            last_error = None
            for attempt in range(5):
                try:
                    sheets[title].batch_update(chunk)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    time.sleep(2 * (attempt + 1))
            if last_error:
                raise last_error
        print(f"Updated {len(cells)} Foundever cells on {title}.")


def append_log(entry):
    os.makedirs(os.path.dirname(RUN_LOG), exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def load_knockouts():
    if not os.path.exists(KNOCKOUT_LOG):
        return set()
    with open(KNOCKOUT_LOG, encoding="utf-8") as handle:
        return {line.strip().lower() for line in handle if line.strip()}


def remember_knockout(email):
    os.makedirs(os.path.dirname(KNOCKOUT_LOG), exist_ok=True)
    with open(KNOCKOUT_LOG, "a", encoding="utf-8") as handle:
        handle.write(email.strip().lower() + "\n")


def check_mapping():
    samples = {
        "Quezon City": "Quezon City",
        "Candelaria Quezon": "Quezon",
        "Bacolod City": "City of Bacolod",
        "Bacolod": "City of Bacolod",
        "Maalas-as, Rosario, Batangas": "Batangas",
        "Maalas-as, Rosario": "Batangas",
        "Dolores, Eastern Samar": "Eastern Samar",
        "Tanza, Cavite": "Cavite",
        "Angeles coty": "City of Angeles",
        "Angeles City, Pampanga": "City of Angeles",
        "Talisay Batangas": "Batangas",
        "Talisay, Cebu": "Cebu",
        "Ilagan City Isabela": "Isabela",
        "Isabela": "Isabela",
        "City of Isabela": "City of Isabela",
        "Cebu": "City of Cebu",
        "Manila": "City of Manila",
        "Davao": "City of Davao",
        "Davao City, Davao Del Sur": "Davao del Sur",
        "Parañaque City": "City of Parañaque",
        "Binangonan": "Rizal",
        "Oslob": "Cebu",
        "Santa Rosa City": "Laguna",
        "Bauan, Batangas": "Batangas",
        "BAMBAN": "Tarlac",
        "Noveleta": "Cavite",
        "Baybay": "Leyte",
        "Cabuyao": "Laguna",
        "Piat": "Cagayan",
        "Bangar": "La Union",
        "Binalonan": "Pangasinan",
        "Baguio": "City of Baguio",
        "Baguio City": "City of Baguio",
        "qc": "Quezon City",
        "metro manila": "Quezon City",
        "Compostela Valley": "Davao de Oro",
        "North Cotabato": "Cotabato",
        "Western Samar": "Samar",
        "Maguindanao": "Maguindanao del Norte",
        "Maguindanao del Sur": "Maguindanao del Sur",
        "Intramuros": "City of Manila",
        "Mandaluyong": "City of Mandaluyong",
        "Pateros": "Pateros",
        "Alabang": "City of Muntinlupa",
        "San Fernando, Pampanga": "Pampanga",
        "San Fernando, La Union": "La Union",
        "San Mateo, Rizal": "Rizal",
        "San Mateo, Isabela": "Isabela",
        "San Miguel, Bulacan": "Bulacan",
        "Imus": "Cavite",
        "Tagaytay": "Cavite",
        "Calamba, Laguna": "Laguna",
        "Calamba City": "Laguna",
        "Biñan": "Laguna",
        "Rodriguez": "Rizal",
        "montalban": "Rizal",
        "cdo": "City of Cagayan de Oro",
        "gensan": "City of General Santos",
        "bukindon": "Bukidnon",
        "e samar": "Eastern Samar",
        "Iloilo": "City of Iloilo",
        "Pasig City": "City of Pasig",
        "Sta. Rosa City": "Laguna",
        "Santa Rosa, Laguna": "Laguna",
        "San Juan, Metro Manila": "City of San Juan",
        "San Juan, Batangas": "Batangas",
        "Hagonoy, Bulacan": "Bulacan",
        "Hagonoy, Davao del Sur": "Davao del Sur",
        "Rosario, Batangas": "Batangas",
        "Taytay, Rizal": "Rizal",
        "Taytay, Palawan": "Palawan",
        "Bacolod, Lanao del Norte": "Lanao del Norte",
    }
    unresolved = [
        "Hagonoy", "San Fernando", "Rosario", "San Mateo", "Talisay", "Taytay",
        "Pilar", "San Miguel", "Bato", "Looc", "Magsaysay", "Tudela",
        "San Francisco", "San Quintin", "Valencia", "Liloan", "Calamba",
        "Sta. Rosa", "Santa Rosa", "San Juan", "Compostela", "Talisay City",
        "San Fernando City",
    ]
    for raw, expected in samples.items():
        found = match_place(raw)
        if not found or found[0] != expected:
            raise RuntimeError(f"place match {raw!r} -> {found} expected {expected}")
    for raw in unresolved:
        found = match_place(raw)
        if found:
            raise RuntimeError(f"place match {raw!r} should stay unresolved, got {found}")
    baguio = match_place("Baguio")
    if baguio[1] != "Cordillera Administrative Region (CAR)" or baguio[2] != "2600":
        raise RuntimeError(f"Baguio must stay on the Baguio city row, got {baguio}")
    angeles = match_place("Angeles City, Pampanga")
    if angeles[2] != "2009":
        raise RuntimeError(f"Angeles must use the Angeles zip, got {angeles}")
    if map_bpo("")[1] != "No Call Center Experience":
        raise RuntimeError("blank BPO must map to no call center experience")
    if map_bpo("3 Years & Above")[1] != "Over 2 Years":
        raise RuntimeError("3 years of BPO must map to Over 2 Years")
    graduated = map_education("College Graduate", 2002)
    if graduated[0] != "Bachelor's degree or equivalent" or graduated[1] != "4th Year College level Completed":
        raise RuntimeError(f"college graduate mapping {graduated}")
    if local_phone("9813257775") != "09813257775":
        raise RuntimeError("phone normalization failed")
    if REFERRAL_NAME != "XRP - Edward Belacse" or WORK_SETUP != "On-Site":
        raise RuntimeError("standing questionnaire answers changed")


def submit_candidate(maki, candidate):
    invitation = maki.invitation_token(candidate["job_url"])
    schema = maki.schema(invitation)
    names = {question["name"] for question in schema}
    if "employee_referral_name" not in names or "preferred_work_setup" not in names:
        raise RuntimeError("questionnaire is missing referral or work setup")
    invited = maki.invite(invitation, candidate)
    instance = invited.get("assessment_instance_link")
    if not instance:
        raise RuntimeError(f"Maki did not return an application link: {invited}")
    if invited.get("already_applied"):
        stored = maki.stored(instance)
        if stored and stored.get("admin_questions_completed_at") and fixed_answers_ok(stored):
            return {"status": "already", "instance": instance}
        if stored and stored.get("admin_questions_completed_at"):
            result = maki.submit(instance, payload_from_stored(stored, schema))
        else:
            result = maki.submit(instance, build_answers(schema, candidate))
    else:
        result = maki.submit(instance, build_answers(schema, candidate))
    if not result.get("success"):
        raise RuntimeError(f"submit failed: {result}")
    if result.get("knockOutReason"):
        return {"status": "knockout", "instance": instance, "reason": result["knockOutReason"]}
    stored = maki.stored(instance)
    if not stored or not fixed_answers_ok(stored):
        found = stored_map(stored) if stored else {}
        raise RuntimeError(
            "saved referral/work setup mismatch: "
            f"referral={found.get('employee_referral_name')} setup={found.get('preferred_work_setup')}"
        )
    return {"status": "submitted", "instance": instance, "stored": stored_map(stored)}


def run_foundever_pipeline():
    check_mapping()
    dry = os.getenv("FOUNDEVER_DRY", "").strip() in {"1", "true", "yes"}
    limit_raw = os.getenv("FOUNDEVER_LIMIT", "").strip()
    limit = int(limit_raw) if limit_raw else None
    doc = setup_gspread()
    ready, remarks, skipped = load_candidates(doc)
    print(f"Ready {len(ready)}. Sheet remarks queued {len(remarks)}. Skipped {len(skipped)}.")
    skip_counts = defaultdict(int)
    for item in skipped:
        skip_counts[item[2]] += 1
        if item[2] in {"unmatched city", "unmapped education", "unmapped bpo", "unusable birthdate"}:
            print(f"Skip {item[0]} row {item[1]}: {item[2]} {item[3]!r}")
    print("Skip summary:", dict(skip_counts))
    remark_counts = defaultdict(int)
    for item in remarks:
        remark_counts[item[3]] += 1
    print("Remark summary:", dict(remark_counts))
    if dry:
        maki = Maki()
        for candidate in ready[:3]:
            schema = maki.schema(maki.invitation_token(candidate["job_url"]))
            answers = build_answers(schema, candidate)
            print(
                f"DRY {candidate['sheet']} row {candidate['row']}: "
                f"{candidate['first_name']} {candidate['last_name']} | {candidate['city']} -> {candidate['place'][0]} | "
                f"{candidate['edu']} | {candidate['bpo']} | phone {candidate['local_phone']} | "
                f"answers {len(answers)} | referral {REFERRAL_NAME} | {WORK_SETUP}"
            )
        print("Dry run only. No sheet cells and no questionnaires were submitted.")
        return

    knockouts = load_knockouts()
    queue = [candidate for candidate in ready if candidate["email"].lower() not in knockouts]
    if limit is not None:
        queue = queue[:limit]
        print(f"Limited run: {len(queue)} candidate(s). Other sheet remarks are left for the full run.")
    else:
        if remarks:
            write_remarks(remarks)
            remarks = []

    maki = Maki()
    pending = []
    submitted = 0
    for index, candidate in enumerate(queue, start=1):
        label = f"{candidate['first_name']} {candidate['last_name']}"
        print(f"[{index}/{len(queue)}] {candidate['sheet']} row {candidate['row']} {label}")
        try:
            outcome = submit_candidate(maki, candidate)
        except Exception as exc:
            print(f"  FAILED {label}: {exc}")
            append_log({"email": candidate["email"], "row": candidate["row"], "sheet": candidate["sheet"], "error": str(exc)})
            continue
        status = outcome["status"]
        if status == "knockout":
            print(f"  Knocked out ({outcome['reason']}). Sheet left blank.")
            remember_knockout(candidate["email"])
            append_log({"email": candidate["email"], "status": "knockout", "instance": outcome["instance"]})
            continue
        pending.append((candidate["worksheet"], candidate["row"], candidate["col"], "Executive Team / Y"))
        submitted += 1
        print(f"  {status} {outcome['instance']} -> Executive Team / Y")
        append_log({
            "email": candidate["email"],
            "status": status,
            "instance": outcome["instance"],
            "sheet": candidate["sheet"],
            "row": candidate["row"],
            "referral": REFERRAL_NAME,
            "work_setup": WORK_SETUP,
        })
        if len(pending) >= 20:
            write_remarks(pending)
            pending = []
        time.sleep(0.15)
    if pending:
        write_remarks(pending)
    print(f"Submitted or confirmed {submitted} Foundever questionnaire(s).")


if __name__ == "__main__":
    run_foundever_pipeline()
