using Dmat.Web.Models.Entities;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Data;

/// <summary>
/// 種子資料:角色、模擬任務帳號(架構書 8.1 預先建立之任務帳號)、醫療站、診斷代碼字典。
/// 模擬帳號僅供開發與演練,正式導入時應由院方依演練編組發放。
/// </summary>
public static class DbSeeder
{
    /// <summary>開發/演練用預設密碼(README 有記載;正式環境務必更換)</summary>
    public const string DevPassword = "Dmat#2026";

    public static async Task SeedAsync(IServiceProvider services)
    {
        var db = services.GetRequiredService<DmatDbContext>();
        var roleManager = services.GetRequiredService<RoleManager<AppRole>>();
        var userManager = services.GetRequiredService<UserManager<AppUser>>();

        await db.Database.MigrateAsync();

        // ---- 角色 ----
        var roles = new (string Name, string DisplayName)[]
        {
            (RoleNames.Medic, "醫護人員"),
            (RoleNames.StationLeader, "站長"),
            (RoleNames.Commander, "指揮官"),
            (RoleNames.Admin, "系統管理者"),
        };
        foreach (var (name, display) in roles)
        {
            if (await roleManager.FindByNameAsync(name) is null)
                await roleManager.CreateAsync(new AppRole(name) { DisplayName = display });
        }

        // ---- 醫療站 ----
        var station = await db.Stations.FirstOrDefaultAsync();
        if (station is null)
        {
            station = new Station { Code = "NTUH-01", Name = "台大醫療站" };
            db.Stations.Add(station);
            await db.SaveChangesAsync();
        }

        // ---- 模擬任務帳號 ----
        var users = new (string UserName, string DisplayName, string Role)[]
        {
            ("admin", "系統管理者", RoleNames.Admin),
            ("commander", "指揮官", RoleNames.Commander),
            ("leader01", "站長 站長一", RoleNames.StationLeader),
            ("medic01", "醫護 甲一", RoleNames.Medic),
            ("medic02", "醫護 甲二", RoleNames.Medic),
            ("medic03", "醫護 甲三", RoleNames.Medic),
        };
        foreach (var (userName, display, role) in users)
        {
            if (await userManager.FindByNameAsync(userName) is null)
            {
                var user = new AppUser
                {
                    UserName = userName,
                    Email = $"{userName}@dmat.local",
                    EmailConfirmed = true,
                    DisplayName = display,
                    StationId = station.StationId,
                };
                var result = await userManager.CreateAsync(user, DevPassword);
                if (result.Succeeded)
                    await userManager.AddToRoleAsync(user, role);
            }
        }

        // ---- 診斷代碼字典(紀錄單 7.1 創傷 19 項 / 7.2 非創傷 25 項) ----
        if (!await db.DiagnosisCodes.AnyAsync())
        {
            string[] trauma =
            [
                "撕裂傷", "表淺損傷", "鈍挫傷、拉扭傷", "中軸骨折", "骨盆骨折", "四肢閉鎖性骨折",
                "四肢開放性骨折", "截肢", "脫臼", "壓砸傷", "輕度頭部外傷", "中重度頭部外傷",
                "脊髓損傷", "氣血胸", "心血管損傷", "腹部臟器損傷", "燒傷", "環境急症", "其他外科",
            ];
            string[] nonTrauma =
            [
                "發燒", "肺炎", "氣喘或慢性阻塞性肺病", "急性腹痛", "腸胃炎", "出血性腹瀉",
                "上呼吸道感染", "泌尿道感染", "暈眩", "頭痛", "糖尿病相關病症", "消化道出血",
                "高血壓", "蜂窩性組織炎", "過敏或濕疹", "其他皮膚病", "急性冠心症", "心衰竭",
                "呼吸衰竭", "腦中風", "焦慮症", "其他精神疾病", "中毒", "婦產科急症", "其他",
            ];
            db.DiagnosisCodes.AddRange(trauma.Select((n, i) =>
                new DiagnosisCode { Category = 1, ItemNo = (byte)(i + 1), NameZh = n }));
            db.DiagnosisCodes.AddRange(nonTrauma.Select((n, i) =>
                new DiagnosisCode { Category = 2, ItemNo = (byte)(i + 1), NameZh = n }));
            await db.SaveChangesAsync();
        }
    }
}
