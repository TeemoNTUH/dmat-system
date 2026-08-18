"""紀錄單頁 1 欄位鍵名(與 damt_db_fields.xlsx Field_Map.db_column 及 Web 端 OcrFieldKeys 對齊)。"""

CHRONIC_KEYS = [
    "chronic_disease_diabetes", "chronic_disease_hypertension", "chronic_disease_long_term_dialysis",
    "chronic_disease_heart_failure", "chronic_disease_asthma", "chronic_disease_copd", "chronic_disease_other",
]

TRAUMA_KEYS = [
    "trauma_laceration", "trauma_superficial_injury", "trauma_contusion_sprain", "trauma_axial_fracture",
    "trauma_pelvic_fracture", "trauma_closed_extremity_fracture", "trauma_open_extremity_fracture",
    "trauma_amputation", "trauma_dislocation", "trauma_crush_injury", "trauma_mild_head_injury",
    "trauma_moderate_severe_head_injury", "trauma_spinal_cord_injury", "trauma_hemo_pneumothorax",
    "trauma_cardiovascular_injury", "trauma_abdominal_organ_injury", "trauma_burn",
    "trauma_environmental_emergency", "trauma_other_surgical",
]

NON_TRAUMA_KEYS = [
    "non_trauma_fever", "non_trauma_pneumonia", "non_trauma_asthma_or_copd", "non_trauma_acute_abdominal_pain",
    "non_trauma_gastroenteritis", "non_trauma_bloody_diarrhea", "non_trauma_upper_respiratory_infection",
    "non_trauma_urinary_tract_infection", "non_trauma_dizziness", "non_trauma_headache",
    "non_trauma_diabetes_related", "non_trauma_gastrointestinal_bleeding", "non_trauma_hypertension",
    "non_trauma_cellulitis", "non_trauma_allergy_or_eczema", "non_trauma_other_skin_disease",
    "non_trauma_acute_coronary_syndrome", "non_trauma_heart_failure", "non_trauma_respiratory_failure",
    "non_trauma_stroke", "non_trauma_anxiety", "non_trauma_other_psychiatric_disease", "non_trauma_poisoning",
    "non_trauma_obstetric_gynecologic_emergency", "non_trauma_other",
]

TEXT_KEYS = [
    "triage", "gender", "patient_name", "patient_tag_id", "national_id", "nationality",
    "consciousness", "vaccine_other_note", "allergy_note", "chronic_disease_other_note",
    "present_illness_description", "non_trauma_other_note",
]

NUMBER_KEYS = [
    "patient_age", "birth_year", "birth_month", "birth_day",
    "temperature_c", "pulse", "respiratory_rate",
    "blood_pressure_systolic", "blood_pressure_diastolic", "spo2_percent",
]

BOOL_KEYS = ["pregnant", "vaccine_tetanus", "vaccine_other", "has_allergy",
             *CHRONIC_KEYS, *TRAUMA_KEYS, *NON_TRAUMA_KEYS]

ALL_KEYS = [*TEXT_KEYS, *NUMBER_KEYS, *BOOL_KEYS]
