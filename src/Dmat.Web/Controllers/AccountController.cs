using Dmat.Web.Models.Entities;
using Dmat.Web.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace Dmat.Web.Controllers;

public class LoginVm
{
    public string UserName { get; set; } = "";
    public string Password { get; set; } = "";
    public string? ReturnUrl { get; set; }
}

public class AccountController(
    SignInManager<AppUser> signInManager,
    Data.DmatDbContext db,
    AuditService audit) : Controller
{
    [AllowAnonymous]
    public IActionResult Login(string? returnUrl = null) => View(new LoginVm { ReturnUrl = returnUrl });

    [HttpPost, AllowAnonymous, ValidateAntiForgeryToken]
    public async Task<IActionResult> Login(LoginVm vm)
    {
        // 登入失敗次數過多自動鎖定(架構書 8.1,lockoutOnFailure: true)
        var result = await signInManager.PasswordSignInAsync(vm.UserName, vm.Password,
            isPersistent: true, lockoutOnFailure: true);
        if (result.Succeeded)
        {
            audit.Log("Login", "AppUser", vm.UserName);
            await db.SaveChangesAsync();
            return LocalRedirect(vm.ReturnUrl ?? "/");
        }
        ModelState.AddModelError("", result.IsLockedOut ? "帳號已鎖定,請 15 分鐘後再試" : "帳號或密碼錯誤");
        return View(vm);
    }

    [HttpPost, ValidateAntiForgeryToken]
    public async Task<IActionResult> Logout()
    {
        await signInManager.SignOutAsync();
        return RedirectToAction(nameof(Login));
    }

    [AllowAnonymous]
    public IActionResult Denied() => View();
}
