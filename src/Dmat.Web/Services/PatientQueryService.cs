using Dmat.Web.Data;
using Dmat.Web.Models.Entities;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Services;

/// <summary>傷患清單的查詢條件。全為選填,未給即不套用該條件。</summary>
public record PatientFilter(
    string? Keyword = null,
    TriageLevel? Triage = null,
    PatientStatus? Status = null,
    int Page = 1)
{
    public const int PageSize = 50;

    public bool HasAnyFilter => !string.IsNullOrWhiteSpace(Keyword) || Triage is not null || Status is not null;
}

/// <summary>查詢結果與分頁資訊。</summary>
public class PatientPage
{
    public required List<Patient> Items { get; init; }
    public required int TotalCount { get; init; }
    public required PatientFilter Filter { get; init; }

    public int PageCount => Math.Max(1, (int)Math.Ceiling(TotalCount / (double)PatientFilter.PageSize));
    public int CurrentPage => Math.Clamp(Filter.Page, 1, PageCount);
    public bool HasPrevious => CurrentPage > 1;
    public bool HasNext => CurrentPage < PageCount;
}

/// <summary>
/// 傷患清單查詢:關鍵字、檢傷分類、動向狀態、分頁。
///
/// **為什麼需要這一層**
///
/// 原本的清單是「取最近更新的 200 筆」。大量傷患事件動輒上百人,這代表:
/// 超過 200 筆之後最早進站的傷患就從畫面上消失了,而那些往往正是還在等後送的人。
/// 要找特定傷票編號也只能靠瀏覽器搜尋當前頁面 —— 找不到時無法分辨是「沒這個人」
/// 還是「在第 201 筆之後」,這在現場是危險的模稜兩可。
///
/// 因此改為條件查詢 + 分頁,並在畫面上明確顯示總筆數。
/// </summary>
public class PatientQueryService(DmatDbContext db)
{
    public async Task<PatientPage> QueryAsync(PatientFilter filter, CancellationToken ct = default)
    {
        var q = db.Patients.AsNoTracking().AsQueryable();

        if (!string.IsNullOrWhiteSpace(filter.Keyword))
        {
            // SQLite 的 LIKE 對 ASCII 預設不分大小寫,傷票編號 sim-014 / SIM-014 都能找到。
            // 中文姓名不受影響。刻意不搜身分證字號:該欄加密儲存,無法比對,
            // 而且可搜尋等於在資料庫外洩時多開一條驗證管道。
            var kw = filter.Keyword.Trim();
            q = q.Where(p =>
                (p.TagNo != null && EF.Functions.Like(p.TagNo, $"%{kw}%")) ||
                (p.Name != null && EF.Functions.Like(p.Name, $"%{kw}%")));
        }

        if (filter.Triage is { } t) q = q.Where(p => p.CurrentTriage == t);
        if (filter.Status is { } s) q = q.Where(p => p.Status == s);

        var total = await q.CountAsync(ct);

        // 排序:檢傷分類優先(紅→黃→綠→黑→緩),同級再依更新時間。
        // 清單的用途是「接下來要處理誰」,依時間排會把最急的傷患埋在中間。
        var pageCount = Math.Max(1, (int)Math.Ceiling(total / (double)PatientFilter.PageSize));
        var page = Math.Clamp(filter.Page, 1, pageCount);

        var items = await q
            .OrderBy(p => p.CurrentTriage)
            .ThenByDescending(p => p.UpdatedAt)
            .Skip((page - 1) * PatientFilter.PageSize)
            .Take(PatientFilter.PageSize)
            .ToListAsync(ct);

        return new PatientPage { Items = items, TotalCount = total, Filter = filter with { Page = page } };
    }
}
