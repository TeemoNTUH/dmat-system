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

    /// <summary>
    /// AI 服務各階段耗時(轉寫 / 規則結構化 / 各題複查 / 複查整批),隨 ResultJson 存入資料庫,
    /// 用來判斷辨識慢在哪一段。只保留計時與摘要欄位 ——
    /// AI 服務回傳的 evidence、複查答案等含病歷內容的欄位刻意不收(見 <see cref="OcrStageTiming"/>)。
    /// </summary>
    [JsonPropertyName("stages")]
    public List<OcrStageTiming> Stages { get; set; } = [];

    /// <summary>
    /// Web 端量測的整體往返耗時(毫秒):上傳、AI 服務前處理、所有推論與網路時間都算在內。
    /// 失敗(含逾時)時也會記錄,用來對照 <c>AiService:TimeoutSeconds</c> 是否太緊。
    /// </summary>
    [JsonPropertyName("elapsedMs")]
    public long? ElapsedMs { get; set; }
}

/// <summary>
/// 單一辨識階段的計時紀錄(對應 AI 服務回傳 stages[] 的子集)。
/// 未列出的屬性(evidence、answer 等)反序列化時直接略過,不會進資料庫。
/// </summary>
public class OcrStageTiming
{
    /// <summary>ocr_transcribe / structure_rules / verify / verify_batch / direct_json</summary>
    [JsonPropertyName("stage")] public string Stage { get; set; } = "";

    [JsonPropertyName("elapsedMs")] public long? ElapsedMs { get; set; }

    /// <summary>複查題目名稱(如「檢傷分類」),僅 verify 階段有值</summary>
    [JsonPropertyName("target")] public string? Target { get; set; }

    /// <summary>複查題型:single / multi / value</summary>
    [JsonPropertyName("kind")] public string? Kind { get; set; }

    /// <summary>轉寫輸出字數(ocr_transcribe / direct_json);字數異常多通常代表模型重複輸出</summary>
    [JsonPropertyName("chars")] public int? Chars { get; set; }

    /// <summary>規則結構化擷取到的欄位數(structure_rules)</summary>
    [JsonPropertyName("extracted")] public int? Extracted { get; set; }

    /// <summary>複查答案是否被採用(verify)</summary>
    [JsonPropertyName("applied")] public bool? Applied { get; set; }

    /// <summary>
    /// 複查回答因超過 DMAT_VERIFY_MAX_TOKENS 被截斷(verify)。代表模型沒照指示只回答答案,
    /// 該題一律不採用、沿用第一輪結果;經常出現時表示該題提示詞需要調整。
    /// </summary>
    [JsonPropertyName("truncated")] public bool? Truncated { get; set; }

    /// <summary>複查題數與併發上限(verify_batch)</summary>
    [JsonPropertyName("tasks")] public int? Tasks { get; set; }
    [JsonPropertyName("concurrency")] public int? Concurrency { get; set; }

    /// <summary>該階段失敗原因(verify 失敗時)</summary>
    [JsonPropertyName("error")] public string? Error { get; set; }
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
