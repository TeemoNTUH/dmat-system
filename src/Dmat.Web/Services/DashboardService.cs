using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

public class DashboardSummary
{
    public int Total { get; set; }
    public int Red { get; set; }
    public int Yellow { get; set; }
    public int Green { get; set; }
    public int Black { get; set; }
    public int Palliative { get; set; }
    public int InCare { get; set; }
    public int AwaitingEvacuation { get; set; }
    public int Deceased { get; set; }
    public int PendingReview { get; set; }

    // ---- 戰情看板(上方區塊)所需 ----
    public int Male { get; set; }
    public int Female { get; set; }
    public int OtherGender { get; set; }
    /// <summary>性別未填(覆核時可能留空)</summary>
    public int UnknownGender { get; set; }

    /// <summary>後送中(尚未離站)</summary>
    public int Evacuating { get; set; }
    /// <summary>已離站(處置後返家/轉出)</summary>
    public int Departed { get; set; }

    /// <summary>死亡 + 緩和治療(紀錄單 4 與 4-1 於看板合併為同一列)</summary>
    public int BlackOrPalliative => Black + Palliative;
    /// <summary>轉院後送 = 待後送 + 後送中</summary>
    public int Evacuation => AwaitingEvacuation + Evacuating;

    // ---- 直接災難相關比例(版面已就緒,資料待接) ----
    // 刻意用 int? 而非 int:資料模型還沒有「災難相關性」欄位,
    // 若給 0 會在看板上顯示成「經統計後確實是 0 人」,那是假資訊。
    // null 代表「尚未收集」,前端顯示為「—」。
    // 之後只要在此填入實際統計,看板與 SignalR 推播會自動開始顯示,不需再改前端。
    public int? DisasterDirect { get; set; }
    public int? DisasterIndirect { get; set; }
    public int? DisasterUnrelated { get; set; }

    /// <summary>災難相關性是否已有資料可統計</summary>
    public bool HasDisasterRelation =>
        DisasterDirect is not null || DisasterIndirect is not null || DisasterUnrelated is not null;

    /// <summary>非本國籍傷患數(國籍欄有填者)</summary>
    public int ForeignNationals { get; set; }
    /// <summary>具傳染病徵候診斷之傷患數(發燒/肺炎/腸胃炎/出血性腹瀉/上呼吸道感染)</summary>
    public int InfectiousWatch { get; set; }

    /// <summary>
    /// 指定回報項目/特殊通報警示。字串在服務層產生 —— Razor 首次渲染與 SignalR
    /// 推播後的重繪共用同一份,避免兩處各寫一次判斷邏輯而逐漸不一致。
    /// </summary>
    public List<string> Alerts { get; set; } = [];

    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}

/// <summary>
/// 儀表板統計模組(架構書 4.2)。
/// 本切片規模採即時查詢;大量傷患情境之預先彙總(materialized summary)為後續優化項目。
/// </summary>
public class DashboardService(DmatDbContext db)
{
    /// <summary>
    /// 具傳染病徵候的非創傷診斷項次(架構書 7.2 編號):
    /// 1 發燒、2 肺炎、5 腸胃炎、6 出血性腹瀉、7 上呼吸道感染。
    /// 用於群聚風險提示 —— 這是提醒指揮官留意,不是傳染病診斷。
    /// </summary>
    private static readonly byte[] InfectiousItemNos = [1, 2, 5, 6, 7];

    public async Task<DashboardSummary> GetSummaryAsync()
    {
        var byTriage = await db.Patients
            .GroupBy(p => p.CurrentTriage)
            .Select(g => new { Level = g.Key, Count = g.Count() })
            .ToListAsync();
        var byStatus = await db.Patients
            .GroupBy(p => p.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToListAsync();
        var byGender = await db.Patients
            .GroupBy(p => p.Gender)
            .Select(g => new { Gender = g.Key, Count = g.Count() })
            .ToListAsync();

        int Triage(TriageLevel l) => byTriage.FirstOrDefault(x => x.Level == l)?.Count ?? 0;
        int Status(PatientStatus s) => byStatus.FirstOrDefault(x => x.Status == s)?.Count ?? 0;
        int Sex(Gender? g) => byGender.FirstOrDefault(x => x.Gender == g)?.Count ?? 0;

        var foreign = await db.Patients
            .CountAsync(p => p.Nationality != null && p.Nationality != "");

        // 一位傷患可能同時有多項傳染病徵候診斷,取 Distinct 以免重複計人
        var infectious = await db.DiagnosisRecords
            .Where(d => d.DiagnosisCode!.Category == 2 && InfectiousItemNos.Contains(d.DiagnosisCode.ItemNo))
            .Select(d => d.PatientId)
            .Distinct()
            .CountAsync();

        var summary = new DashboardSummary
        {
            Total = byTriage.Sum(x => x.Count),
            Red = Triage(TriageLevel.Red),
            Yellow = Triage(TriageLevel.Yellow),
            Green = Triage(TriageLevel.Green),
            Black = Triage(TriageLevel.Black),
            Palliative = Triage(TriageLevel.Palliative),
            InCare = Status(PatientStatus.InCare),
            AwaitingEvacuation = Status(PatientStatus.AwaitingEvacuation),
            Evacuating = Status(PatientStatus.Evacuating),
            Departed = Status(PatientStatus.Departed),
            Deceased = Status(PatientStatus.Deceased),
            Male = Sex(Gender.Male),
            Female = Sex(Gender.Female),
            OtherGender = Sex(Gender.Other),
            UnknownGender = Sex(null),
            ForeignNationals = foreign,
            InfectiousWatch = infectious,
            // 含辨識中(Queued/Recognizing):這些影像已上傳但尚未進入傷患主檔,
            // 對指揮官而言同樣是「還沒算進統計的量」。
            PendingReview = await db.RecordImages.CountAsync(i =>
                i.Status == RecordImageStatus.Queued
                || i.Status == RecordImageStatus.Recognizing
                || i.Status == RecordImageStatus.PendingReview
                || i.Status == RecordImageStatus.ManualFallback),

            // 【待接】災難相關性(直接/間接/無相關)。
            // Patient 尚無此欄位;欄位確認後在此改為實際 GroupBy 統計即可,例如:
            //   DisasterDirect = await db.Patients.CountAsync(p => p.DisasterRelation == DisasterRelation.Direct),
            DisasterDirect = null,
            DisasterIndirect = null,
            DisasterUnrelated = null,
        };

        summary.Alerts = BuildAlerts(summary);
        return summary;
    }

    /// <summary>
    /// 依實際統計產生通報警示。**全部由真實資料推導,沒有任何固定文案。**
    /// 一切正常時仍回一則說明,避免版面空白讓人誤以為功能壞了。
    /// </summary>
    private static List<string> BuildAlerts(DashboardSummary s)
    {
        var alerts = new List<string>();

        if (s.ForeignNationals > 0)
            alerts.Add($"發現 {s.ForeignNationals} 名非本國籍傷患,需評估多語系翻譯協助。");

        alerts.Add(s.InfectiousWatch > 0
            ? $"{s.InfectiousWatch} 名傷患具傳染病徵候診斷(發燒/肺炎/腸胃炎/出血性腹瀉/上呼吸道感染),請留意群聚風險。"
            : "尚未出現傳染病徵候之診斷。");

        if (s.Red > 0)
            alerts.Add($"紅級(復甦急救){s.Red} 人,請確認急救資源與後送順位。");

        if (s.PendingReview > 0)
            alerts.Add($"尚有 {s.PendingReview} 張紀錄單影像待覆核,統計數字可能低估實際收治量。");

        if (s.UnknownGender > 0)
            alerts.Add($"{s.UnknownGender} 筆傷患資料性別未填,請於覆核時補齊。");

        return alerts;
    }

    public Task<List<Patient>> GetRecentPatientsAsync(int count = 20) =>
        db.Patients.OrderByDescending(p => p.UpdatedAt).Take(count).ToListAsync();
}
