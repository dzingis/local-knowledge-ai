Write-Host "Creating Milestone 1A files..."

# ------------------------
# Directories
# ------------------------

$dirs = @(
    "docker",
    "docker\backend",
    "docker\mssql",
    "docker\mssql\init",

    "backend",
    "backend\api",
    "backend\config",

    "scripts"
)

foreach($dir in $dirs)
{
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

# ------------------------
# Files
# ------------------------

$files = @(

"docker-compose.yml",

".env.example",

"requirements.txt",

"docker\backend\Dockerfile",

"docker\mssql\init\001-create-database.sql",
"docker\mssql\init\002-create-schemas.sql",

"backend\__init__.py",
"backend\main.py",

"backend\api\__init__.py",
"backend\api\health.py",

"backend\config\__init__.py",
"backend\config\settings.py",

"scripts\start.ps1",
"scripts\stop.ps1",
"scripts\update.ps1"

)

foreach($file in $files)
{
    if(!(Test-Path $file))
    {
        New-Item -ItemType File -Path $file | Out-Null
        Write-Host "Created $file"
    }
    else
    {
        Write-Host "Exists  $file"
    }
}

Write-Host ""
Write-Host "Milestone 1A skeleton created."
Write-Host ""