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

IF OBJECT_ID(N'AI.IngestionQueue', N'U') IS NULL
BEGIN
    CREATE TABLE AI.IngestionQueue (
        QueueId BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_IngestionQueue PRIMARY KEY,
        FileName NVARCHAR(260) NOT NULL,
        FullPath NVARCHAR(4000) NOT NULL,
        Extension NVARCHAR(50) NOT NULL,
        FolderPath NVARCHAR(4000) NOT NULL,
        FileSizeBytes BIGINT NOT NULL,
        ModifiedUtc DATETIME2 NOT NULL,
        Sha256 CHAR(64) NOT NULL,
        Status NVARCHAR(20) NOT NULL,
        ChangeType NVARCHAR(20) NOT NULL,
        EnqueuedAt DATETIME2 NOT NULL
            CONSTRAINT DF_IngestionQueue_EnqueuedAt DEFAULT SYSUTCDATETIME(),
        ProcessedAt DATETIME2 NULL,
        ErrorMessage NVARCHAR(MAX) NULL,
        RetryCount INT NOT NULL
            CONSTRAINT DF_IngestionQueue_RetryCount DEFAULT 0
    );

    CREATE INDEX IX_IngestionQueue_Status_EnqueuedAt
        ON AI.IngestionQueue (Status, EnqueuedAt);
END;
GO
