USE AIKnowledge;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Graph')
    EXEC(N'CREATE SCHEMA Graph');
GO

IF OBJECT_ID(N'Graph.Entity', N'U') IS NULL
BEGIN
    CREATE TABLE Graph.Entity (
        EntityId UNIQUEIDENTIFIER NOT NULL
            CONSTRAINT DF_Graph_Entity_EntityId DEFAULT NEWSEQUENTIALID(),
        CanonicalName NVARCHAR(1000) NOT NULL,
        NormalizedName NVARCHAR(500) NOT NULL,
        EntityType NVARCHAR(200) NOT NULL,
        Description NVARCHAR(MAX) NULL,
        MetadataJson NVARCHAR(MAX) NOT NULL
            CONSTRAINT DF_Graph_Entity_Metadata DEFAULT N'{}',
        CreatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_Entity_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_Entity_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Graph_Entity PRIMARY KEY (EntityId),
        CONSTRAINT UQ_Graph_Entity_NormalizedName_Type
            UNIQUE (NormalizedName, EntityType),
        CONSTRAINT CK_Graph_Entity_MetadataJson
            CHECK (ISJSON(MetadataJson) = 1)
    );
    CREATE INDEX IX_Graph_Entity_Type_Name
        ON Graph.Entity (EntityType, CanonicalName);
END;
GO

IF OBJECT_ID(N'Graph.EntityAlias', N'U') IS NULL
BEGIN
    CREATE TABLE Graph.EntityAlias (
        AliasId BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_Graph_EntityAlias PRIMARY KEY,
        EntityId UNIQUEIDENTIFIER NOT NULL,
        AliasName NVARCHAR(500) NOT NULL,
        NormalizedAlias NVARCHAR(500) NOT NULL,
        CreatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_EntityAlias_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_Graph_EntityAlias_Entity
            FOREIGN KEY (EntityId) REFERENCES Graph.Entity(EntityId) ON DELETE CASCADE,
        CONSTRAINT UQ_Graph_EntityAlias_Entity_Normalized
            UNIQUE (EntityId, NormalizedAlias)
    );
    CREATE INDEX IX_Graph_EntityAlias_Normalized
        ON Graph.EntityAlias (NormalizedAlias);
END;
GO

IF OBJECT_ID(N'Graph.EntityProperty', N'U') IS NULL
BEGIN
    CREATE TABLE Graph.EntityProperty (
        EntityId UNIQUEIDENTIFIER NOT NULL,
        PropertyKey NVARCHAR(200) NOT NULL,
        PropertyValue NVARCHAR(MAX) NOT NULL,
        CreatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_EntityProperty_CreatedAt DEFAULT SYSUTCDATETIME(),
        UpdatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_EntityProperty_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Graph_EntityProperty PRIMARY KEY (EntityId, PropertyKey),
        CONSTRAINT FK_Graph_EntityProperty_Entity
            FOREIGN KEY (EntityId) REFERENCES Graph.Entity(EntityId) ON DELETE CASCADE
    );
END;
GO

IF OBJECT_ID(N'Graph.EntityDocument', N'U') IS NULL
BEGIN
    CREATE TABLE Graph.EntityDocument (
        EntityId UNIQUEIDENTIFIER NOT NULL,
        DocumentId UNIQUEIDENTIFIER NOT NULL,
        SourcePath NVARCHAR(4000) NULL,
        Confidence FLOAT NOT NULL,
        Evidence NVARCHAR(MAX) NULL,
        CreatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_EntityDocument_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Graph_EntityDocument PRIMARY KEY (EntityId, DocumentId),
        CONSTRAINT FK_Graph_EntityDocument_Entity
            FOREIGN KEY (EntityId) REFERENCES Graph.Entity(EntityId) ON DELETE CASCADE,
        CONSTRAINT CK_Graph_EntityDocument_Confidence
            CHECK (Confidence >= 0 AND Confidence <= 1)
    );
    CREATE INDEX IX_Graph_EntityDocument_Document
        ON Graph.EntityDocument (DocumentId, EntityId);
END;
GO

IF OBJECT_ID(N'Graph.Relationship', N'U') IS NULL
BEGIN
    CREATE TABLE Graph.Relationship (
        RelationshipId UNIQUEIDENTIFIER NOT NULL
            CONSTRAINT DF_Graph_Relationship_Id DEFAULT NEWSEQUENTIALID(),
        SourceEntityId UNIQUEIDENTIFIER NOT NULL,
        TargetEntityId UNIQUEIDENTIFIER NOT NULL,
        RelationshipType NVARCHAR(200) NOT NULL,
        Confidence FLOAT NOT NULL,
        SourceDocumentId UNIQUEIDENTIFIER NULL,
        Evidence NVARCHAR(MAX) NULL,
        MetadataJson NVARCHAR(MAX) NOT NULL
            CONSTRAINT DF_Graph_Relationship_Metadata DEFAULT N'{}',
        CreatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_Relationship_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Graph_Relationship PRIMARY KEY (RelationshipId),
        CONSTRAINT FK_Graph_Relationship_Source
            FOREIGN KEY (SourceEntityId) REFERENCES Graph.Entity(EntityId) ON DELETE CASCADE,
        CONSTRAINT FK_Graph_Relationship_Target
            FOREIGN KEY (TargetEntityId) REFERENCES Graph.Entity(EntityId),
        CONSTRAINT CK_Graph_Relationship_Confidence
            CHECK (Confidence >= 0 AND Confidence <= 1),
        CONSTRAINT CK_Graph_Relationship_NoSelfEdge
            CHECK (SourceEntityId <> TargetEntityId),
        CONSTRAINT CK_Graph_Relationship_MetadataJson
            CHECK (ISJSON(MetadataJson) = 1)
    );
    CREATE INDEX IX_Graph_Relationship_Source_Type
        ON Graph.Relationship (SourceEntityId, RelationshipType);
    CREATE INDEX IX_Graph_Relationship_Target_Type
        ON Graph.Relationship (TargetEntityId, RelationshipType);
    CREATE INDEX IX_Graph_Relationship_Document
        ON Graph.Relationship (SourceDocumentId);
END;
GO

IF OBJECT_ID(N'Graph.EntityEmbedding', N'U') IS NULL
BEGIN
    CREATE TABLE Graph.EntityEmbedding (
        EntityId UNIQUEIDENTIFIER NOT NULL,
        QdrantPointId NVARCHAR(100) NOT NULL,
        ModelName NVARCHAR(200) NOT NULL,
        UpdatedAt DATETIME2 NOT NULL
            CONSTRAINT DF_Graph_EntityEmbedding_UpdatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Graph_EntityEmbedding PRIMARY KEY (EntityId),
        CONSTRAINT UQ_Graph_EntityEmbedding_Point UNIQUE (QdrantPointId),
        CONSTRAINT FK_Graph_EntityEmbedding_Entity
            FOREIGN KEY (EntityId) REFERENCES Graph.Entity(EntityId) ON DELETE CASCADE
    );
END;
GO

-- Upgrade the earlier Graph schema without dropping its tables or data.
IF COL_LENGTH(N'Graph.Entity', N'CanonicalName') IS NULL
    ALTER TABLE Graph.Entity ADD CanonicalName NVARCHAR(1000) NULL;
IF COL_LENGTH(N'Graph.Entity', N'NormalizedName') IS NULL
    ALTER TABLE Graph.Entity ADD NormalizedName NVARCHAR(500) NULL;
IF COL_LENGTH(N'Graph.Entity', N'Description') IS NULL
    ALTER TABLE Graph.Entity ADD Description NVARCHAR(MAX) NULL;
IF COL_LENGTH(N'Graph.Entity', N'MetadataJson') IS NULL
    ALTER TABLE Graph.Entity ADD MetadataJson NVARCHAR(MAX) NULL;
IF COL_LENGTH(N'Graph.Entity', N'CreatedAt') IS NULL
    ALTER TABLE Graph.Entity ADD CreatedAt DATETIME2 NULL;
IF COL_LENGTH(N'Graph.Entity', N'UpdatedAt') IS NULL
    ALTER TABLE Graph.Entity ADD UpdatedAt DATETIME2 NULL;
GO

IF COL_LENGTH(N'Graph.Entity', N'EntityName') IS NOT NULL
BEGIN
    EXEC(N'
        UPDATE Graph.Entity
        SET CanonicalName = COALESCE(CanonicalName, EntityName, N''Unknown'')
        WHERE CanonicalName IS NULL;
    ');
END;

UPDATE Graph.Entity
SET CanonicalName = COALESCE(CanonicalName, N'Unknown'),
    NormalizedName = COALESCE(
        NormalizedName,
        LOWER(LTRIM(RTRIM(
            REPLACE(REPLACE(REPLACE(CanonicalName, N'_', N' '), N'.', N' '), N'-', N' ')
        )))
    ),
    EntityType = COALESCE(EntityType, N'unknown'),
    MetadataJson = COALESCE(MetadataJson, N'{}'),
    CreatedAt = COALESCE(CreatedAt, SYSUTCDATETIME()),
    UpdatedAt = COALESCE(UpdatedAt, SYSUTCDATETIME());
GO

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Entity') AND name = N'CanonicalName'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Entity ALTER COLUMN CanonicalName NVARCHAR(1000) NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Entity') AND name = N'NormalizedName'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Entity ALTER COLUMN NormalizedName NVARCHAR(500) NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Entity') AND name = N'EntityType'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Entity ALTER COLUMN EntityType NVARCHAR(200) NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Entity') AND name = N'MetadataJson'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Entity ALTER COLUMN MetadataJson NVARCHAR(MAX) NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Entity') AND name = N'CreatedAt'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Entity ALTER COLUMN CreatedAt DATETIME2 NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Entity') AND name = N'UpdatedAt'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Entity ALTER COLUMN UpdatedAt DATETIME2 NOT NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'Graph.Entity')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'Graph.Entity'), N'MetadataJson', 'ColumnId')
)
    ALTER TABLE Graph.Entity ADD CONSTRAINT DF_Graph_Entity_Metadata
        DEFAULT N'{}' FOR MetadataJson;
IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'Graph.Entity')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'Graph.Entity'), N'CreatedAt', 'ColumnId')
)
    ALTER TABLE Graph.Entity ADD CONSTRAINT DF_Graph_Entity_CreatedAt
        DEFAULT SYSUTCDATETIME() FOR CreatedAt;
IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'Graph.Entity')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'Graph.Entity'), N'UpdatedAt', 'ColumnId')
)
    ALTER TABLE Graph.Entity ADD CONSTRAINT DF_Graph_Entity_UpdatedAt
        DEFAULT SYSUTCDATETIME() FOR UpdatedAt;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'Graph.Entity')
      AND name = N'IX_Graph_Entity_NormalizedName_Type'
)
    CREATE INDEX IX_Graph_Entity_NormalizedName_Type
        ON Graph.Entity (NormalizedName, EntityType);
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'Graph.Entity')
      AND name = N'IX_Graph_Entity_Type_Name'
)
    CREATE INDEX IX_Graph_Entity_Type_Name
        ON Graph.Entity (EntityType, CanonicalName);
GO

IF COL_LENGTH(N'Graph.Relationship', N'SourceEntityId') IS NULL
    ALTER TABLE Graph.Relationship ADD SourceEntityId UNIQUEIDENTIFIER NULL;
IF COL_LENGTH(N'Graph.Relationship', N'TargetEntityId') IS NULL
    ALTER TABLE Graph.Relationship ADD TargetEntityId UNIQUEIDENTIFIER NULL;
IF COL_LENGTH(N'Graph.Relationship', N'Confidence') IS NULL
    ALTER TABLE Graph.Relationship ADD Confidence FLOAT NULL;
IF COL_LENGTH(N'Graph.Relationship', N'SourceDocumentId') IS NULL
    ALTER TABLE Graph.Relationship ADD SourceDocumentId UNIQUEIDENTIFIER NULL;
IF COL_LENGTH(N'Graph.Relationship', N'Evidence') IS NULL
    ALTER TABLE Graph.Relationship ADD Evidence NVARCHAR(MAX) NULL;
IF COL_LENGTH(N'Graph.Relationship', N'MetadataJson') IS NULL
    ALTER TABLE Graph.Relationship ADD MetadataJson NVARCHAR(MAX) NULL;
IF COL_LENGTH(N'Graph.Relationship', N'CreatedAt') IS NULL
    ALTER TABLE Graph.Relationship ADD CreatedAt DATETIME2 NULL;
GO

IF COL_LENGTH(N'Graph.Relationship', N'SourceEntity') IS NOT NULL
    EXEC(N'
        UPDATE Graph.Relationship
        SET SourceEntityId = COALESCE(SourceEntityId, SourceEntity)
        WHERE SourceEntityId IS NULL;
    ');
IF COL_LENGTH(N'Graph.Relationship', N'TargetEntity') IS NOT NULL
    EXEC(N'
        UPDATE Graph.Relationship
        SET TargetEntityId = COALESCE(TargetEntityId, TargetEntity)
        WHERE TargetEntityId IS NULL;
    ');
IF COL_LENGTH(N'Graph.Relationship', N'Weight') IS NOT NULL
    EXEC(N'
        UPDATE Graph.Relationship
        SET Confidence = COALESCE(Confidence, Weight, 0.8)
        WHERE Confidence IS NULL;
    ');

UPDATE Graph.Relationship
SET Confidence = COALESCE(Confidence, 0.8),
    RelationshipType = COALESCE(RelationshipType, N'REFERENCES'),
    MetadataJson = COALESCE(MetadataJson, N'{}'),
    CreatedAt = COALESCE(CreatedAt, SYSUTCDATETIME());
GO

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Relationship') AND name = N'SourceEntityId'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Relationship ALTER COLUMN SourceEntityId UNIQUEIDENTIFIER NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Relationship') AND name = N'TargetEntityId'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Relationship ALTER COLUMN TargetEntityId UNIQUEIDENTIFIER NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Relationship') AND name = N'RelationshipType'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Relationship ALTER COLUMN RelationshipType NVARCHAR(200) NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Relationship') AND name = N'Confidence'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Relationship ALTER COLUMN Confidence FLOAT NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Relationship') AND name = N'MetadataJson'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Relationship ALTER COLUMN MetadataJson NVARCHAR(MAX) NOT NULL;
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'Graph.Relationship') AND name = N'CreatedAt'
      AND is_nullable = 1
)
    ALTER TABLE Graph.Relationship ALTER COLUMN CreatedAt DATETIME2 NOT NULL;
GO

-- The legacy source/target columns were NOT NULL and had no defaults.
-- Keep their values but allow new writes to use the current *EntityId columns.
IF COL_LENGTH(N'Graph.Relationship', N'SourceEntity') IS NOT NULL
    ALTER TABLE Graph.Relationship ALTER COLUMN SourceEntity UNIQUEIDENTIFIER NULL;
IF COL_LENGTH(N'Graph.Relationship', N'TargetEntity') IS NOT NULL
    ALTER TABLE Graph.Relationship ALTER COLUMN TargetEntity UNIQUEIDENTIFIER NULL;
IF COL_LENGTH(N'Graph.Relationship', N'Weight') IS NOT NULL
    ALTER TABLE Graph.Relationship ALTER COLUMN Weight FLOAT NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'Graph.Relationship')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'Graph.Relationship'), N'MetadataJson', 'ColumnId')
)
    ALTER TABLE Graph.Relationship ADD CONSTRAINT DF_Graph_Relationship_Metadata
        DEFAULT N'{}' FOR MetadataJson;
IF NOT EXISTS (
    SELECT 1 FROM sys.default_constraints
    WHERE parent_object_id = OBJECT_ID(N'Graph.Relationship')
      AND parent_column_id = COLUMNPROPERTY(OBJECT_ID(N'Graph.Relationship'), N'CreatedAt', 'ColumnId')
)
    ALTER TABLE Graph.Relationship ADD CONSTRAINT DF_Graph_Relationship_CreatedAt
        DEFAULT SYSUTCDATETIME() FOR CreatedAt;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'Graph.Relationship')
      AND name = N'IX_Graph_Relationship_Source_Type'
)
    CREATE INDEX IX_Graph_Relationship_Source_Type
        ON Graph.Relationship (SourceEntityId, RelationshipType);
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'Graph.Relationship')
      AND name = N'IX_Graph_Relationship_Target_Type'
)
    CREATE INDEX IX_Graph_Relationship_Target_Type
        ON Graph.Relationship (TargetEntityId, RelationshipType);
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'Graph.Relationship')
      AND name = N'IX_Graph_Relationship_Document'
)
    CREATE INDEX IX_Graph_Relationship_Document
        ON Graph.Relationship (SourceDocumentId);
GO