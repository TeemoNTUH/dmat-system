using Dmat.Web.Data;
using Dmat.Web.Models.Entities;

namespace Dmat.Web.Services;

/// <summary>稽核紀錄(架構書 8.4):僅新增與查詢,應用層不提供修改/刪除。</summary>
public class AuditService(DmatDbContext db, IHttpContextAccessor httpContextAccessor)
{
    public void Log(string action, string? targetType = null, string? targetId = null, string? detail = null)
    {
        var ctx = httpContextAccessor.HttpContext;
        db.AuditLogs.Add(new AuditLog
        {
            Action = action,
            TargetType = targetType,
            TargetId = targetId,
            Detail = detail,
            UserName = ctx?.User?.Identity?.Name,
            SourceIp = ctx?.Connection?.RemoteIpAddress?.ToString(),
        });
        // 呼叫端負責 SaveChanges,與業務異動同一交易寫入
    }
}
