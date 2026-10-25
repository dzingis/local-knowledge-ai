$folders = @(
"docs",
"database",
"database\migrations",
"backend",
"backend\api",
"backend\config",
"backend\core",
"backend\indexer",
"backend\search",
"backend\services",
"backend\watcher",
"backend\tests",
"backend\parsers",
"backend\parsers\pdf",
"backend\parsers\docx",
"backend\parsers\sql",
"backend\parsers\delphi",
"backend\parsers\swagger",
"backend\parsers\xml",
"backend\parsers\excel",
"backend\parsers\text",
"scripts",
"config",
"frontend",
"samples",
"models",
"logs",
"temp"
)

foreach($folder in $folders)
{
    New-Item -ItemType Directory -Force $folder | Out-Null
}

$files = @(
"LICENSE",
".gitignore",
".env.example",
"docker-compose.yml",
"requirements.txt",
"pyproject.toml",

"docs\Architecture.md",
"docs\Roadmap.md",
"docs\Database.md",
"docs\API.md",
"docs\Installation.md",
"docs\Security.md",
"docs\Configuration.md",
"docs\FAQ.md",

"database\schema.sql",
"database\indexes.sql",
"database\views.sql",
"database\procedures.sql",
"database\seed.sql",

"backend\__init__.py",
"backend\app.py",
"backend\main.py",

"backend\api\__init__.py",
"backend\api\chat.py",
"backend\api\search.py",
"backend\api\documents.py",
"backend\api\settings.py",
"backend\api\health.py",

"backend\config\__init__.py",
"backend\config\settings.py",
"backend\config\logging.py",
"backend\config\constants.py",

"backend\core\__init__.py",
"backend\core\database.py",
"backend\core\ollama.py",
"backend\core\qdrant.py",
"backend\core\embeddings.py",
"backend\core\security.py",

"backend\indexer\__init__.py",
"backend\indexer\scanner.py",
"backend\indexer\chunker.py",
"backend\indexer\metadata.py",
"backend\indexer\hasher.py",
"backend\indexer\index_manager.py",

"backend\search\__init__.py",
"backend\search\semantic.py",
"backend\search\keyword.py",
"backend\search\hybrid.py",
"backend\search\reranker.py",
"backend\search\citations.py",

"backend\services\__init__.py",
"backend\services\chat_service.py",
"backend\services\document_service.py",
"backend\services\indexing_service.py",
"backend\services\metadata_service.py",
"backend\services\openfile_service.py",

"backend\watcher\__init__.py",
"backend\watcher\filesystem.py",
"backend\watcher\scheduler.py",
"backend\watcher\worker.py",

"backend\parsers\__init__.py",

"backend\parsers\pdf\parser.py",
"backend\parsers\pdf\tables.py",
"backend\parsers\pdf\images.py",

"backend\parsers\docx\parser.py",
"backend\parsers\docx\styles.py",

"backend\parsers\sql\parser.py",
"backend\parsers\sql\procedures.py",
"backend\parsers\sql\views.py",
"backend\parsers\sql\tables.py",
"backend\parsers\sql\dependencies.py",

"backend\parsers\delphi\parser.py",
"backend\parsers\delphi\units.py",
"backend\parsers\delphi\classes.py",
"backend\parsers\delphi\methods.py",

"backend\parsers\swagger\parser.py",
"backend\parsers\swagger\endpoints.py",
"backend\parsers\swagger\schemas.py",

"backend\parsers\xml\parser.py",

"backend\parsers\excel\parser.py",

"backend\parsers\text\parser.py",

"backend\tests\test_sql.py",
"backend\tests\test_pdf.py",
"backend\tests\test_search.py",
"backend\tests\test_chat.py",

"scripts\install.ps1",
"scripts\start.ps1",
"scripts\stop.ps1",
"scripts\update.ps1",
"scripts\backup.ps1",
"scripts\rebuild_index.ps1",

"config\appsettings.json",
"config\folders.json",
"config\models.json"
)

foreach($file in $files)
{
    if(!(Test-Path $file))
    {
        New-Item -ItemType File $file | Out-Null
    }
}

Write-Host ""
Write-Host "========================================="
Write-Host " Local Knowledge AI skeleton created"
Write-Host "========================================="
Write-Host ""