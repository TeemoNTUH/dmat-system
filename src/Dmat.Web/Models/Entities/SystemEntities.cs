using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Identity;

namespace Dmat.Web.Models.Entities;

/// <summary>醫療站</summary>
public class Station
{
    public Guid StationId { get; set; } = Guid.NewGuid();

    [MaxLength(20)]
    public string Code { get; set; } = "";

    [MaxLength(100)]
    public string Name { get; set; } = "";

    public bool IsActive { get; set; } = true;
}

/// <summary>
/// 稽核紀錄(架構書 8.4)。應用層僅提供新增與查詢,不提供修改/刪除。
/// </summary>
public class AuditLog
{
    public long AuditLogId { get; set; }

    public Guid? UserId { get; set; }
    [MaxLength(100)]
    public string? UserName { get; set; }

    [MaxLength(50)]
    public string Action { get; set; } = "";

    [MaxLength(50)]
    public string? TargetType { get; set; }
    [MaxLength(64)]
    public string? TargetId { get; set; }

    public string? Detail { get; set; }

    [MaxLength(45)]
    public string? SourceIp { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

/// <summary>
/// 同步紀錄(架構書 7.6)。
/// 【預留】中央彙整同步暫不實作:網路恢復後由同步服務讀取本表之待同步範圍,
/// 以 HTTPS 批次上傳至中央資料庫(單向上傳為主),支援斷點續傳。
/// </summary>
public class SyncLog
{
    public long SyncLogId { get; set; }

    [MaxLength(50)]
    public string TableName { get; set; } = "";
    [MaxLength(64)]
    public string RecordId { get; set; } = "";

    /// <summary>0 待同步、1 已上傳、2 衝突待人工確認</summary>
    public byte SyncStatus { get; set; }

    public DateTime ChangedAt { get; set; } = DateTime.UtcNow;
    public DateTime? SyncedAt { get; set; }
}

/// <summary>使用者(ASP.NET Core Identity)</summary>
public class AppUser : IdentityUser<Guid>
{
    [MaxLength(50)]
    public string DisplayName { get; set; } = "";

    public Guid? StationId { get; set; }
}

public class AppRole : IdentityRole<Guid>
{
    public AppRole() { }
    public AppRole(string name) : base(name) { }

    [MaxLength(50)]
    public string DisplayName { get; set; } = "";
}

/// <summary>角色名稱常數(架構書 2.2 / 8.2)</summary>
public static class RoleNames
{
    /// <summary>第一線醫護人員</summary>
    public const string Medic = "Medic";
    /// <summary>醫療站站長</summary>
    public const string StationLeader = "StationLeader";
    /// <summary>指揮官</summary>
    public const string Commander = "Commander";
    /// <summary>系統管理者</summary>
    public const string Admin = "Admin";
}
