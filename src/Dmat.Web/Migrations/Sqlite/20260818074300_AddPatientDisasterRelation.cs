using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Dmat.Web.Migrations.Sqlite
{
    /// <inheritdoc />
    public partial class AddPatientDisasterRelation : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<byte>(
                name: "DisasterRelation",
                table: "Patients",
                type: "INTEGER",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "DisasterRelation",
                table: "Patients");
        }
    }
}
