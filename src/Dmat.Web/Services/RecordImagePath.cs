namespace Dmat.Web.Services;

/// <summary>
/// 紀錄單影像檔路徑的儲存與解析。
///
/// **為什麼需要這一層**
///
/// RecordImage.FilePath 存的是相對路徑。若直接用 <c>Path.GetRelativePath</c> 的結果,
/// 在 Windows 上會得到 <c>app_data\images\202607\xxx.jpg</c>(反斜線),
/// 在 Linux 上則是 <c>app_data/images/202607/xxx.jpg</c>(斜線)。
///
/// 資料庫一旦跨平台搬移(例如開發時在 Windows 建檔、正式部署到 GB10 的 Ubuntu),
/// 舊資料就會失效 —— 因為 Linux 把 <c>\</c> 當成合法的檔名字元而非目錄分隔符,
/// <c>File.Exists</c> 找不到檔案,畫面上就是破圖、點擊得到 404。
///
/// 因此:
/// - **寫入**一律正規化為斜線(<c>/</c> 在 Windows 的 .NET 檔案 API 同樣可用)。
/// - **讀取**同時容忍兩種分隔符,舊資料不必做資料遷移即可正常顯示。
/// </summary>
public static class RecordImagePath
{
    /// <summary>存入資料庫前正規化:一律使用斜線,確保跨平台可讀。</summary>
    public static string ToStorage(string relativePath) => relativePath.Replace('\\', '/');

    /// <summary>
    /// 把資料庫中的相對路徑還原為本機絕對路徑。
    /// 兩種分隔符都接受,因此可正確讀取由另一個作業系統寫入的舊紀錄。
    /// </summary>
    public static string Resolve(IWebHostEnvironment env, string filePath)
    {
        var normalized = filePath
            .Replace('\\', Path.DirectorySeparatorChar)
            .Replace('/', Path.DirectorySeparatorChar);

        return Path.IsPathRooted(normalized)
            ? normalized
            : Path.Combine(env.ContentRootPath, normalized);
    }

    /// <summary>檔案是否實際存在(路徑解析失敗時視為不存在,不拋例外)。</summary>
    public static bool Exists(IWebHostEnvironment env, string filePath)
    {
        try { return File.Exists(Resolve(env, filePath)); }
        catch (ArgumentException) { return false; }   // 路徑含非法字元
        catch (PathTooLongException) { return false; }
    }
}
