using System.Text.Json;
using System.Text.Json.Serialization;

namespace Dmat.Web.Services.Ocr;

/// <summary>
/// AI 辨識服務回傳之結構化結果(架構書 5.2)。
/// 欄位鍵名與 damt_db_fields.xlsx 之 Field_Map.db_column 一致,該檔為欄位對照之單一事實來源。
/// </summary>
public class OcrAnalyzeResult
{
    [JsonPropertyName("jobId")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("model")]
    public string Model { get; set; } = "";

    /// <summary>
    /// true 表示產生此結果的是模擬引擎:欄位為寫死的樣張假資料,與影像無關。
    /// 覆核介面必須據此顯示警示,避免假資料被當成辨識結果送進傷患主檔。
    /// </summary>
    [JsonPropertyName("isMock")]
    public bool IsMock { get; set; }

    /// <summary>欄位鍵 → 值/信心分數;鍵名為 snake_case(如 triage、patient_name、trauma_laceration)</summary>
    [JsonPropertyName("fields")]
    public Dictionary<string, OcrFieldValue> Fields { get; set; } = [];

    /// <summary>資料合理性檢核警示(生命徵象範圍、檢傷邏輯)</summary>
    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];
}

public class OcrFieldValue
{
    /// <summary>辨識值:文字欄為字串、數值欄為數字、勾選框為布林;空白為 null</summary>
    [JsonPropertyName("value")]
    public JsonElement Value { get; set; }

    [JsonPropertyName("confidence")]
    public double Confidence { get; set; }

    /// <summary>信心分數低於門檻,需人工確認</summary>
    [JsonPropertyName("needReview")]
    public bool NeedReview { get; set; }

    [JsonIgnore]
    public string? AsString => Value.ValueKind switch
    {
        JsonValueKind.String => Value.GetString(),
        JsonValueKind.Number => Value.GetRawText(),
        JsonValueKind.True => "true",
        JsonValueKind.False => "false",
        _ => null,
    };

    [JsonIgnore]
    public bool AsBool => Value.ValueKind == JsonValueKind.True
        || (Value.ValueKind == JsonValueKind.String && bool.TryParse(Value.GetString(), out var b) && b);
}

/// <summary>OCR 欄位鍵名常數(頁 1;與 Field_Map.db_column 對齊)</summary>
public static class OcrFieldKeys
{
    public const string Triage = "triage";                 // "1"/"2"/"3"/"4"/"4-1"
    public const string Gender = "gender";                 // "男"/"女"/"其他"
    public const string PatientName = "patient_name";
    public const string PatientAge = "patient_age";
    public const string PatientTagId = "patient_tag_id";
    public const string BirthYear = "birth_year";
    public const string BirthMonth = "birth_month";
    public const string BirthDay = "birth_day";
    public const string NationalId = "national_id";
    public const string Nationality = "nationality";
    public const string Consciousness = "consciousness";
    public const string TemperatureC = "temperature_c";
    public const string Pulse = "pulse";
    public const string RespiratoryRate = "respiratory_rate";
    public const string Sbp = "blood_pressure_systolic";
    public const string Dbp = "blood_pressure_diastolic";
    public const string SpO2 = "spo2_percent";
    public const string Pregnant = "pregnant";
    public const string VaccineTetanus = "vaccine_tetanus";
    public const string VaccineOther = "vaccine_other";
    public const string VaccineOtherNote = "vaccine_other_note";
    public const string HasAllergy = "has_allergy";
    public const string AllergyNote = "allergy_note";
    public const string PresentIllness = "present_illness_description";
    public const string NonTraumaOtherNote = "non_trauma_other_note";

    /// <summary>慢性疾病勾選鍵(Field_Map 順序)</summary>
    public static readonly string[] ChronicKeys =
    [
        "chronic_disease_diabetes", "chronic_disease_hypertension", "chronic_disease_long_term_dialysis",
        "chronic_disease_heart_failure", "chronic_disease_asthma", "chronic_disease_copd", "chronic_disease_other",
    ];
    public const string ChronicOtherNote = "chronic_disease_other_note";

    /// <summary>創傷診斷勾選鍵,索引 = 紀錄單項次 - 1(7.1 創傷 19 項)</summary>
    public static readonly string[] TraumaKeys =
    [
        "trauma_laceration", "trauma_superficial_injury", "trauma_contusion_sprain", "trauma_axial_fracture",
        "trauma_pelvic_fracture", "trauma_closed_extremity_fracture", "trauma_open_extremity_fracture",
        "trauma_amputation", "trauma_dislocation", "trauma_crush_injury", "trauma_mild_head_injury",
        "trauma_moderate_severe_head_injury", "trauma_spinal_cord_injury", "trauma_hemo_pneumothorax",
        "trauma_cardiovascular_injury", "trauma_abdominal_organ_injury", "trauma_burn",
        "trauma_environmental_emergency", "trauma_other_surgical",
    ];

    /// <summary>非創傷診斷勾選鍵,索引 = 紀錄單項次 - 1(7.2 非創傷 25 項)</summary>
    public static readonly string[] NonTraumaKeys =
    [
        "non_trauma_fever", "non_trauma_pneumonia", "non_trauma_asthma_or_copd", "non_trauma_acute_abdominal_pain",
        "non_trauma_gastroenteritis", "non_trauma_bloody_diarrhea", "non_trauma_upper_respiratory_infection",
        "non_trauma_urinary_tract_infection", "non_trauma_dizziness", "non_trauma_headache",
        "non_trauma_diabetes_related", "non_trauma_gastrointestinal_bleeding", "non_trauma_hypertension",
        "non_trauma_cellulitis", "non_trauma_allergy_or_eczema", "non_trauma_other_skin_disease",
        "non_trauma_acute_coronary_syndrome", "non_trauma_heart_failure", "non_trauma_respiratory_failure",
        "non_trauma_stroke", "non_trauma_anxiety", "non_trauma_other_psychiatric_disease", "non_trauma_poisoning",
        "non_trauma_obstetric_gynecologic_emergency", "non_trauma_other",
    ];
}
