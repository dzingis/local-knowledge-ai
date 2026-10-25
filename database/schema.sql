CREATE TABLE dbo.Documents (
    DocumentId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    FileName NVARCHAR(260) NOT NULL,
    FullPath NVARCHAR(4000) NOT NULL,
    Extension NVARCHAR(50) NOT NULL,
    FolderPath NVARCHAR(4000) NULL,
    FileSizeBytes BIGINT NULL,
    Sha256 CHAR(64) NULL,
    CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_Documents_CreatedAt DEFAULT SYSUTCDATETIME(),
    ModifiedAt DATETIME2 NULL,
    IndexedAt DATETIME2 NULL,
    IsDeleted BIT NOT NULL CONSTRAINT DF_Documents_IsDeleted DEFAULT 0
);
GO

CREATE TABLE dbo.DocumentChunks (
    ChunkId BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    DocumentId INT NOT NULL,
    PageNumber INT NULL,
    Heading NVARCHAR(1000) NULL,
    ChunkText NVARCHAR(MAX) NOT NULL,
    ChunkOrder INT NOT NULL,
    StartOffset INT NULL,
    EndOffset INT NULL,
    CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_DocumentChunks_CreatedAt DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_DocumentChunks_Documents FOREIGN KEY (DocumentId) REFERENCES dbo.Documents(DocumentId)
);
GO

CREATE TABLE dbo.Tags (
    TagId INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    TagName NVARCHAR(200) NOT NULL UNIQUE
);
GO

CREATE TABLE dbo.DocumentTags (
    DocumentId INT NOT NULL,
    TagId INT NOT NULL,
    CONSTRAINT PK_DocumentTags PRIMARY KEY (DocumentId, TagId),
    CONSTRAINT FK_DocumentTags_Documents FOREIGN KEY (DocumentId) REFERENCES dbo.Documents(DocumentId),
    CONSTRAINT FK_DocumentTags_Tags FOREIGN KEY (TagId) REFERENCES dbo.Tags(TagId)
);
GO
