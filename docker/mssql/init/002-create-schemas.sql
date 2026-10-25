USE AIKnowledge;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'AI')
    EXEC('CREATE SCHEMA AI');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'Graph')
    EXEC('CREATE SCHEMA Graph');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'Code')
    EXEC('CREATE SCHEMA Code');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'Search')
    EXEC('CREATE SCHEMA Search');
GO
