using Dmat.Web.Models.Entities;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

namespace Dmat.Web.Data;

public class DmatDbContext(DbContextOptions<DmatDbContext> options)
    : IdentityDbContext<AppUser, AppRole, Guid>(options)
{
    public DbSet<Patient> Patients => Set<Patient>();
    public DbSet<TriageRecord> TriageRecords => Set<TriageRecord>();
    public DbSet<PastHistory> PastHistories => Set<PastHistory>();
    public DbSet<DiagnosisCode> DiagnosisCodes => Set<DiagnosisCode>();
    public DbSet<DiagnosisRecord> DiagnosisRecords => Set<DiagnosisRecord>();
    public DbSet<RecordImage> RecordImages => Set<RecordImage>();
    public DbSet<OcrResult> OcrResults => Set<OcrResult>();
    public DbSet<Station> Stations => Set<Station>();
    public DbSet<AuditLog> AuditLogs => Set<AuditLog>();
    public DbSet<SyncLog> SyncLogs => Set<SyncLog>();

    protected override void OnModelCreating(ModelBuilder builder)
    {
        base.OnModelCreating(builder);

        builder.Entity<Patient>(e =>
        {
            e.HasKey(p => p.PatientId);
            e.HasIndex(p => p.TagNo);
            e.HasOne(p => p.PastHistory).WithOne(h => h.Patient!)
                .HasForeignKey<PastHistory>(h => h.PatientId);
        });

        builder.Entity<TriageRecord>(e =>
        {
            e.HasKey(t => t.TriageId);
            e.HasOne(t => t.Patient).WithMany(p => p.TriageRecords).HasForeignKey(t => t.PatientId);
        });

        builder.Entity<PastHistory>().HasKey(h => h.PastHistoryId);

        builder.Entity<DiagnosisCode>(e =>
        {
            e.HasKey(c => c.DiagnosisCodeId);
            e.HasIndex(c => new { c.Category, c.ItemNo }).IsUnique();
        });

        builder.Entity<DiagnosisRecord>(e =>
        {
            e.HasKey(d => d.DiagnosisRecordId);
            e.HasOne(d => d.Patient).WithMany(p => p.Diagnoses).HasForeignKey(d => d.PatientId);
            e.HasOne(d => d.DiagnosisCode).WithMany().HasForeignKey(d => d.DiagnosisCodeId);
        });

        builder.Entity<RecordImage>(e =>
        {
            e.HasKey(i => i.ImageId);
            e.HasIndex(i => i.FileHash).IsUnique(); // 多路徑交付去重(架構書 7.4.2)
            e.HasOne(i => i.Patient).WithMany(p => p.Images).HasForeignKey(i => i.PatientId);
        });

        builder.Entity<OcrResult>(e =>
        {
            e.HasKey(r => r.OcrResultId);
            e.HasOne(r => r.Image).WithOne(i => i.OcrResult!).HasForeignKey<OcrResult>(r => r.ImageId);
        });

        builder.Entity<Station>().HasKey(s => s.StationId);
        builder.Entity<AuditLog>().HasKey(a => a.AuditLogId);
        builder.Entity<SyncLog>(e =>
        {
            e.HasKey(s => s.SyncLogId);
            e.HasIndex(s => new { s.SyncStatus, s.ChangedAt });
        });
    }
}
