using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Dmat.Web.Migrations.Sqlite
{
    /// <inheritdoc />
    public partial class InitialCreate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "AspNetRoles",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "TEXT", nullable: false),
                    DisplayName = table.Column<string>(type: "TEXT", maxLength: 50, nullable: false),
                    Name = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    NormalizedName = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    ConcurrencyStamp = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetRoles", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "AspNetUsers",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "TEXT", nullable: false),
                    DisplayName = table.Column<string>(type: "TEXT", maxLength: 50, nullable: false),
                    StationId = table.Column<Guid>(type: "TEXT", nullable: true),
                    UserName = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    NormalizedUserName = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    Email = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    NormalizedEmail = table.Column<string>(type: "TEXT", maxLength: 256, nullable: true),
                    EmailConfirmed = table.Column<bool>(type: "INTEGER", nullable: false),
                    PasswordHash = table.Column<string>(type: "TEXT", nullable: true),
                    SecurityStamp = table.Column<string>(type: "TEXT", nullable: true),
                    ConcurrencyStamp = table.Column<string>(type: "TEXT", nullable: true),
                    PhoneNumber = table.Column<string>(type: "TEXT", nullable: true),
                    PhoneNumberConfirmed = table.Column<bool>(type: "INTEGER", nullable: false),
                    TwoFactorEnabled = table.Column<bool>(type: "INTEGER", nullable: false),
                    LockoutEnd = table.Column<DateTimeOffset>(type: "TEXT", nullable: true),
                    LockoutEnabled = table.Column<bool>(type: "INTEGER", nullable: false),
                    AccessFailedCount = table.Column<int>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetUsers", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "AuditLogs",
                columns: table => new
                {
                    AuditLogId = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    UserId = table.Column<Guid>(type: "TEXT", nullable: true),
                    UserName = table.Column<string>(type: "TEXT", maxLength: 100, nullable: true),
                    Action = table.Column<string>(type: "TEXT", maxLength: 50, nullable: false),
                    TargetType = table.Column<string>(type: "TEXT", maxLength: 50, nullable: true),
                    TargetId = table.Column<string>(type: "TEXT", maxLength: 64, nullable: true),
                    Detail = table.Column<string>(type: "TEXT", nullable: true),
                    SourceIp = table.Column<string>(type: "TEXT", maxLength: 45, nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AuditLogs", x => x.AuditLogId);
                });

            migrationBuilder.CreateTable(
                name: "DiagnosisCodes",
                columns: table => new
                {
                    DiagnosisCodeId = table.Column<int>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Category = table.Column<byte>(type: "INTEGER", nullable: false),
                    ItemNo = table.Column<byte>(type: "INTEGER", nullable: false),
                    NameZh = table.Column<string>(type: "TEXT", maxLength: 50, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DiagnosisCodes", x => x.DiagnosisCodeId);
                });

            migrationBuilder.CreateTable(
                name: "Stations",
                columns: table => new
                {
                    StationId = table.Column<Guid>(type: "TEXT", nullable: false),
                    Code = table.Column<string>(type: "TEXT", maxLength: 20, nullable: false),
                    Name = table.Column<string>(type: "TEXT", maxLength: 100, nullable: false),
                    IsActive = table.Column<bool>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Stations", x => x.StationId);
                });

            migrationBuilder.CreateTable(
                name: "SyncLogs",
                columns: table => new
                {
                    SyncLogId = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    TableName = table.Column<string>(type: "TEXT", maxLength: 50, nullable: false),
                    RecordId = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    SyncStatus = table.Column<byte>(type: "INTEGER", nullable: false),
                    ChangedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    SyncedAt = table.Column<DateTime>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SyncLogs", x => x.SyncLogId);
                });

            migrationBuilder.CreateTable(
                name: "AspNetRoleClaims",
                columns: table => new
                {
                    Id = table.Column<int>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    RoleId = table.Column<Guid>(type: "TEXT", nullable: false),
                    ClaimType = table.Column<string>(type: "TEXT", nullable: true),
                    ClaimValue = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetRoleClaims", x => x.Id);
                    table.ForeignKey(
                        name: "FK_AspNetRoleClaims_AspNetRoles_RoleId",
                        column: x => x.RoleId,
                        principalTable: "AspNetRoles",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "AspNetUserClaims",
                columns: table => new
                {
                    Id = table.Column<int>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    UserId = table.Column<Guid>(type: "TEXT", nullable: false),
                    ClaimType = table.Column<string>(type: "TEXT", nullable: true),
                    ClaimValue = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetUserClaims", x => x.Id);
                    table.ForeignKey(
                        name: "FK_AspNetUserClaims_AspNetUsers_UserId",
                        column: x => x.UserId,
                        principalTable: "AspNetUsers",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "AspNetUserLogins",
                columns: table => new
                {
                    LoginProvider = table.Column<string>(type: "TEXT", nullable: false),
                    ProviderKey = table.Column<string>(type: "TEXT", nullable: false),
                    ProviderDisplayName = table.Column<string>(type: "TEXT", nullable: true),
                    UserId = table.Column<Guid>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetUserLogins", x => new { x.LoginProvider, x.ProviderKey });
                    table.ForeignKey(
                        name: "FK_AspNetUserLogins_AspNetUsers_UserId",
                        column: x => x.UserId,
                        principalTable: "AspNetUsers",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "AspNetUserRoles",
                columns: table => new
                {
                    UserId = table.Column<Guid>(type: "TEXT", nullable: false),
                    RoleId = table.Column<Guid>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetUserRoles", x => new { x.UserId, x.RoleId });
                    table.ForeignKey(
                        name: "FK_AspNetUserRoles_AspNetRoles_RoleId",
                        column: x => x.RoleId,
                        principalTable: "AspNetRoles",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_AspNetUserRoles_AspNetUsers_UserId",
                        column: x => x.UserId,
                        principalTable: "AspNetUsers",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "AspNetUserTokens",
                columns: table => new
                {
                    UserId = table.Column<Guid>(type: "TEXT", nullable: false),
                    LoginProvider = table.Column<string>(type: "TEXT", nullable: false),
                    Name = table.Column<string>(type: "TEXT", nullable: false),
                    Value = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AspNetUserTokens", x => new { x.UserId, x.LoginProvider, x.Name });
                    table.ForeignKey(
                        name: "FK_AspNetUserTokens_AspNetUsers_UserId",
                        column: x => x.UserId,
                        principalTable: "AspNetUsers",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "Patients",
                columns: table => new
                {
                    PatientId = table.Column<Guid>(type: "TEXT", nullable: false),
                    TagNo = table.Column<string>(type: "TEXT", maxLength: 30, nullable: true),
                    Name = table.Column<string>(type: "TEXT", maxLength: 50, nullable: true),
                    Gender = table.Column<byte>(type: "INTEGER", nullable: true),
                    EstAge = table.Column<short>(type: "INTEGER", nullable: true),
                    BirthDate = table.Column<DateOnly>(type: "TEXT", nullable: true),
                    NationalIdEncrypted = table.Column<string>(type: "TEXT", maxLength: 200, nullable: true),
                    Nationality = table.Column<string>(type: "TEXT", maxLength: 50, nullable: true),
                    StationId = table.Column<Guid>(type: "TEXT", nullable: true),
                    CurrentTriage = table.Column<byte>(type: "INTEGER", nullable: false),
                    Status = table.Column<byte>(type: "INTEGER", nullable: false),
                    PresentIllness = table.Column<string>(type: "TEXT", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    UpdatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Patients", x => x.PatientId);
                    table.ForeignKey(
                        name: "FK_Patients_Stations_StationId",
                        column: x => x.StationId,
                        principalTable: "Stations",
                        principalColumn: "StationId");
                });

            migrationBuilder.CreateTable(
                name: "DiagnosisRecords",
                columns: table => new
                {
                    DiagnosisRecordId = table.Column<Guid>(type: "TEXT", nullable: false),
                    PatientId = table.Column<Guid>(type: "TEXT", nullable: false),
                    DiagnosisCodeId = table.Column<int>(type: "INTEGER", nullable: false),
                    Note = table.Column<string>(type: "TEXT", maxLength: 200, nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DiagnosisRecords", x => x.DiagnosisRecordId);
                    table.ForeignKey(
                        name: "FK_DiagnosisRecords_DiagnosisCodes_DiagnosisCodeId",
                        column: x => x.DiagnosisCodeId,
                        principalTable: "DiagnosisCodes",
                        principalColumn: "DiagnosisCodeId",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_DiagnosisRecords_Patients_PatientId",
                        column: x => x.PatientId,
                        principalTable: "Patients",
                        principalColumn: "PatientId",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "PastHistories",
                columns: table => new
                {
                    PastHistoryId = table.Column<Guid>(type: "TEXT", nullable: false),
                    PatientId = table.Column<Guid>(type: "TEXT", nullable: false),
                    Pregnant = table.Column<bool>(type: "INTEGER", nullable: true),
                    VaccineTetanus = table.Column<bool>(type: "INTEGER", nullable: false),
                    VaccineOther = table.Column<bool>(type: "INTEGER", nullable: false),
                    VaccineOtherNote = table.Column<string>(type: "TEXT", maxLength: 100, nullable: true),
                    HasAllergy = table.Column<bool>(type: "INTEGER", nullable: true),
                    AllergyNote = table.Column<string>(type: "TEXT", maxLength: 200, nullable: true),
                    ChronicDiabetes = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicHypertension = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicDialysis = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicHeartFailure = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicAsthma = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicCopd = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicOther = table.Column<bool>(type: "INTEGER", nullable: false),
                    ChronicOtherNote = table.Column<string>(type: "TEXT", maxLength: 200, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PastHistories", x => x.PastHistoryId);
                    table.ForeignKey(
                        name: "FK_PastHistories_Patients_PatientId",
                        column: x => x.PatientId,
                        principalTable: "Patients",
                        principalColumn: "PatientId",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "RecordImages",
                columns: table => new
                {
                    ImageId = table.Column<Guid>(type: "TEXT", nullable: false),
                    PatientId = table.Column<Guid>(type: "TEXT", nullable: true),
                    FilePath = table.Column<string>(type: "TEXT", maxLength: 260, nullable: false),
                    FileHash = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    PageNo = table.Column<byte>(type: "INTEGER", nullable: false),
                    Status = table.Column<byte>(type: "INTEGER", nullable: false),
                    UploadedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    UploadedById = table.Column<Guid>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_RecordImages", x => x.ImageId);
                    table.ForeignKey(
                        name: "FK_RecordImages_Patients_PatientId",
                        column: x => x.PatientId,
                        principalTable: "Patients",
                        principalColumn: "PatientId");
                });

            migrationBuilder.CreateTable(
                name: "TriageRecords",
                columns: table => new
                {
                    TriageId = table.Column<Guid>(type: "TEXT", nullable: false),
                    PatientId = table.Column<Guid>(type: "TEXT", nullable: false),
                    Level = table.Column<byte>(type: "INTEGER", nullable: false),
                    Consciousness = table.Column<string>(type: "TEXT", maxLength: 20, nullable: true),
                    Temp = table.Column<decimal>(type: "decimal(4,1)", nullable: true),
                    Sbp = table.Column<short>(type: "INTEGER", nullable: true),
                    Dbp = table.Column<short>(type: "INTEGER", nullable: true),
                    Hr = table.Column<short>(type: "INTEGER", nullable: true),
                    Rr = table.Column<short>(type: "INTEGER", nullable: true),
                    SpO2 = table.Column<short>(type: "INTEGER", nullable: true),
                    Gcs = table.Column<byte>(type: "INTEGER", nullable: true),
                    TriagedAt = table.Column<DateTime>(type: "TEXT", nullable: false),
                    TriagedById = table.Column<Guid>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_TriageRecords", x => x.TriageId);
                    table.ForeignKey(
                        name: "FK_TriageRecords_Patients_PatientId",
                        column: x => x.PatientId,
                        principalTable: "Patients",
                        principalColumn: "PatientId",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "OcrResults",
                columns: table => new
                {
                    OcrResultId = table.Column<Guid>(type: "TEXT", nullable: false),
                    ImageId = table.Column<Guid>(type: "TEXT", nullable: false),
                    ResultJson = table.Column<string>(type: "TEXT", nullable: false),
                    ReviewedJson = table.Column<string>(type: "TEXT", nullable: true),
                    ModelName = table.Column<string>(type: "TEXT", maxLength: 100, nullable: true),
                    ReviewStatus = table.Column<byte>(type: "INTEGER", nullable: false),
                    ReviewedById = table.Column<Guid>(type: "TEXT", nullable: true),
                    ReviewedAt = table.Column<DateTime>(type: "TEXT", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "TEXT", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_OcrResults", x => x.OcrResultId);
                    table.ForeignKey(
                        name: "FK_OcrResults_RecordImages_ImageId",
                        column: x => x.ImageId,
                        principalTable: "RecordImages",
                        principalColumn: "ImageId",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_AspNetRoleClaims_RoleId",
                table: "AspNetRoleClaims",
                column: "RoleId");

            migrationBuilder.CreateIndex(
                name: "RoleNameIndex",
                table: "AspNetRoles",
                column: "NormalizedName",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_AspNetUserClaims_UserId",
                table: "AspNetUserClaims",
                column: "UserId");

            migrationBuilder.CreateIndex(
                name: "IX_AspNetUserLogins_UserId",
                table: "AspNetUserLogins",
                column: "UserId");

            migrationBuilder.CreateIndex(
                name: "IX_AspNetUserRoles_RoleId",
                table: "AspNetUserRoles",
                column: "RoleId");

            migrationBuilder.CreateIndex(
                name: "EmailIndex",
                table: "AspNetUsers",
                column: "NormalizedEmail");

            migrationBuilder.CreateIndex(
                name: "UserNameIndex",
                table: "AspNetUsers",
                column: "NormalizedUserName",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_DiagnosisCodes_Category_ItemNo",
                table: "DiagnosisCodes",
                columns: new[] { "Category", "ItemNo" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_DiagnosisRecords_DiagnosisCodeId",
                table: "DiagnosisRecords",
                column: "DiagnosisCodeId");

            migrationBuilder.CreateIndex(
                name: "IX_DiagnosisRecords_PatientId",
                table: "DiagnosisRecords",
                column: "PatientId");

            migrationBuilder.CreateIndex(
                name: "IX_OcrResults_ImageId",
                table: "OcrResults",
                column: "ImageId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_PastHistories_PatientId",
                table: "PastHistories",
                column: "PatientId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Patients_StationId",
                table: "Patients",
                column: "StationId");

            migrationBuilder.CreateIndex(
                name: "IX_Patients_TagNo",
                table: "Patients",
                column: "TagNo");

            migrationBuilder.CreateIndex(
                name: "IX_RecordImages_FileHash",
                table: "RecordImages",
                column: "FileHash",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_RecordImages_PatientId",
                table: "RecordImages",
                column: "PatientId");

            migrationBuilder.CreateIndex(
                name: "IX_SyncLogs_SyncStatus_ChangedAt",
                table: "SyncLogs",
                columns: new[] { "SyncStatus", "ChangedAt" });

            migrationBuilder.CreateIndex(
                name: "IX_TriageRecords_PatientId",
                table: "TriageRecords",
                column: "PatientId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "AspNetRoleClaims");

            migrationBuilder.DropTable(
                name: "AspNetUserClaims");

            migrationBuilder.DropTable(
                name: "AspNetUserLogins");

            migrationBuilder.DropTable(
                name: "AspNetUserRoles");

            migrationBuilder.DropTable(
                name: "AspNetUserTokens");

            migrationBuilder.DropTable(
                name: "AuditLogs");

            migrationBuilder.DropTable(
                name: "DiagnosisRecords");

            migrationBuilder.DropTable(
                name: "OcrResults");

            migrationBuilder.DropTable(
                name: "PastHistories");

            migrationBuilder.DropTable(
                name: "SyncLogs");

            migrationBuilder.DropTable(
                name: "TriageRecords");

            migrationBuilder.DropTable(
                name: "AspNetRoles");

            migrationBuilder.DropTable(
                name: "AspNetUsers");

            migrationBuilder.DropTable(
                name: "DiagnosisCodes");

            migrationBuilder.DropTable(
                name: "RecordImages");

            migrationBuilder.DropTable(
                name: "Patients");

            migrationBuilder.DropTable(
                name: "Stations");
        }
    }
}
