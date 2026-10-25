IF DB_ID(N'AIKnowledge') IS NULL
BEGIN
    CREATE DATABASE AIKnowledge;
END;
GO

USE AIKnowledge;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'AI')
    EXEC(N'CREATE SCHEMA AI');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Graph')
    EXEC(N'CREATE SCHEMA Graph');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Code')
    EXEC(N'CREATE SCHEMA Code');
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Search')
    EXEC(N'CREATE SCHEMA Search');
GO
