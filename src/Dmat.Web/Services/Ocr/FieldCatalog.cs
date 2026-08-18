namespace Dmat.Web.Services.Ocr;

public enum FieldKind { Text, Number, Checkbox, Select, Textarea }

/// <summary>覆核介面欄位定義:鍵名、中文標籤、輸入型態、所屬區塊</summary>
public record FieldDef(string Key, string Label, FieldKind Kind, string Group, string[]? Options = null);

/// <summary>
/// 紀錄單頁 1 欄位目錄(附錄 B.2 OCR 欄位對照)。順序即覆核介面呈現順序。
/// </summary>
public static class FieldCatalog
{
    public const string GroupTriage = "1. 檢傷分類";
    public const string GroupBasic = "2-3. 性別與基本資料";
    public const string GroupVitals = "4. 生命徵象";
    public const string GroupHistory = "5. 過去重要病史";
    public const string GroupPresent = "6. 現病史";
    public const string GroupTrauma = "7.1 創傷診斷";
    public const string GroupNonTrauma = "7.2 非創傷診斷";

    public static readonly string[] TriageOptions = ["1", "2", "3", "4", "4-1"];
    public static readonly string[] GenderOptions = ["男", "女", "其他"];

    public static readonly string[] TraumaLabels =
    [
        "撕裂傷", "表淺損傷", "鈍挫傷、拉扭傷", "中軸骨折", "骨盆骨折", "四肢閉鎖性骨折",
        "四肢開放性骨折", "截肢", "脫臼", "壓砸傷", "輕度頭部外傷", "中重度頭部外傷",
        "脊髓損傷", "氣血胸", "心血管損傷", "腹部臟器損傷", "燒傷", "環境急症", "其他外科",
    ];

    public static readonly string[] NonTraumaLabels =
    [
        "發燒", "肺炎", "氣喘或慢性阻塞性肺病", "急性腹痛", "腸胃炎", "出血性腹瀉",
        "上呼吸道感染", "泌尿道感染", "暈眩", "頭痛", "糖尿病相關病症", "消化道出血",
        "高血壓", "蜂窩性組織炎", "過敏或濕疹", "其他皮膚病", "急性冠心症", "心衰竭",
        "呼吸衰竭", "腦中風", "焦慮症", "其他精神疾病", "中毒", "婦產科急症", "其他",
    ];

    private static readonly string[] ChronicLabels =
        ["糖尿病", "高血壓", "長期透析", "心衰竭", "氣喘", "慢性阻塞性肺病", "其他"];

    public static readonly IReadOnlyList<FieldDef> All = Build();

    private static List<FieldDef> Build()
    {
        var defs = new List<FieldDef>
        {
            new(OcrFieldKeys.Triage, "檢傷分類(必填)", FieldKind.Select, GroupTriage, TriageOptions),
            new(OcrFieldKeys.Gender, "性別(必填)", FieldKind.Select, GroupBasic, GenderOptions),
            new(OcrFieldKeys.PatientName, "姓名", FieldKind.Text, GroupBasic),
            new(OcrFieldKeys.PatientAge, "年齡", FieldKind.Number, GroupBasic),
            new(OcrFieldKeys.PatientTagId, "傷票編號(必填)", FieldKind.Text, GroupBasic),
            new(OcrFieldKeys.BirthYear, "生日-年(西元)", FieldKind.Number, GroupBasic),
            new(OcrFieldKeys.BirthMonth, "生日-月", FieldKind.Number, GroupBasic),
            new(OcrFieldKeys.BirthDay, "生日-日", FieldKind.Number, GroupBasic),
            new(OcrFieldKeys.NationalId, "身分證字號(選填)", FieldKind.Text, GroupBasic),
            new(OcrFieldKeys.Nationality, "國籍(非本國籍)", FieldKind.Text, GroupBasic),
            new(OcrFieldKeys.Consciousness, "意識", FieldKind.Text, GroupVitals),
            new(OcrFieldKeys.TemperatureC, "體溫(°C)", FieldKind.Number, GroupVitals),
            new(OcrFieldKeys.Pulse, "脈搏", FieldKind.Number, GroupVitals),
            new(OcrFieldKeys.RespiratoryRate, "呼吸次數", FieldKind.Number, GroupVitals),
            new(OcrFieldKeys.Sbp, "收縮壓", FieldKind.Number, GroupVitals),
            new(OcrFieldKeys.Dbp, "舒張壓", FieldKind.Number, GroupVitals),
            new(OcrFieldKeys.SpO2, "血氧(%)", FieldKind.Number, GroupVitals),
            new(OcrFieldKeys.Pregnant, "懷孕", FieldKind.Checkbox, GroupHistory),
            new(OcrFieldKeys.VaccineTetanus, "疫苗-破傷風", FieldKind.Checkbox, GroupHistory),
            new(OcrFieldKeys.VaccineOther, "疫苗-其他", FieldKind.Checkbox, GroupHistory),
            new(OcrFieldKeys.VaccineOtherNote, "疫苗-其他補充", FieldKind.Text, GroupHistory),
            new(OcrFieldKeys.HasAllergy, "有過敏史", FieldKind.Checkbox, GroupHistory),
            new(OcrFieldKeys.AllergyNote, "過敏史補充", FieldKind.Text, GroupHistory),
        };

        defs.AddRange(OcrFieldKeys.ChronicKeys.Select((key, i) =>
            new FieldDef(key, $"慢性疾病-{ChronicLabels[i]}", FieldKind.Checkbox, GroupHistory)));
        defs.Add(new(OcrFieldKeys.ChronicOtherNote, "慢性疾病-其他補充", FieldKind.Text, GroupHistory));

        defs.Add(new(OcrFieldKeys.PresentIllness, "現病史", FieldKind.Textarea, GroupPresent));

        defs.AddRange(OcrFieldKeys.TraumaKeys.Select((key, i) =>
            new FieldDef(key, $"{i + 1} {TraumaLabels[i]}", FieldKind.Checkbox, GroupTrauma)));
        defs.AddRange(OcrFieldKeys.NonTraumaKeys.Select((key, i) =>
            new FieldDef(key, $"{i + 1} {NonTraumaLabels[i]}", FieldKind.Checkbox, GroupNonTrauma)));
        defs.Add(new(OcrFieldKeys.NonTraumaOtherNote, "非創傷-其他補充", FieldKind.Text, GroupNonTrauma));

        return defs;
    }
}
