from __future__ import annotations

from pathlib import Path

import pytest
from sqlglot.errors import ParseError

import backend.parsers.sql_parser as sql_parser_module
from backend.parsers.parser_models import ParsedDocument, ParsedObjectType
from backend.parsers.parser_service import ParserService
from backend.parsers.sql_parser import SqlObjectType, SqlParser


def test_tsql_ast_ignores_comments_and_literals_and_extracts_procedure_details() -> None:
    sql = """
    -- CREATE VIEW dbo.FakeComment AS SELECT * FROM dbo.NotReal
    CREATE OR ALTER PROCEDURE [sales].[Get Orders]
        @orderId INT,
        @status NVARCHAR(20) = N'-- FROM dbo.NotReal',
        @returnCode INT OUTPUT
    AS
    BEGIN
        /* FROM dbo.HiddenComment */
        SELECT o.Id FROM [AcmeDB].[sales].[Orders] AS o
        JOIN dbo.StatusCodes AS s ON s.Id = o.StatusId;
        UPDATE dbo.Audit SET UpdatedAt = GETDATE();
        EXEC dbo.RebuildOrder @orderId;
        EXEC(N'SELECT * FROM dbo.HiddenDynamicSql
GO
SELECT 1');
    END
    """

    result = SqlParser().parse_text(sql)
    definition = result.definitions[0]

    assert definition.operation == "CREATE OR ALTER"
    assert definition.object_type is SqlObjectType.PROCEDURE
    assert [(parameter.name, parameter.data_type, parameter.output) for parameter in definition.parameters] == [
        ("orderId", "INTEGER", False),
        ("status", "NVARCHAR(20)", False),
        ("returnCode", "INTEGER", True),
    ]
    assert definition.parameters[1].default == "N'-- FROM dbo.NotReal'"
    assert definition.dynamic_sql
    assert {
        (reference.database, reference.schema, reference.name, reference.kind)
        for reference in definition.referenced_objects
    } == {
        ("AcmeDB", "sales", "Orders", "read"),
        (None, "dbo", "StatusCodes", "read"),
        (None, "dbo", "Audit", "write"),
        (None, "dbo", "RebuildOrder", "execute"),
    }


def test_cte_aliases_are_not_reported_as_dependencies() -> None:
    sql = """
    CREATE VIEW [reporting].[Open Orders] AS
    WITH open_orders AS (
        SELECT * FROM [Warehouse].[sales].[Orders]
    )
    SELECT * FROM open_orders JOIN dbo.Customers c ON c.Id = open_orders.CustomerId
    """

    result = SqlParser().parse_text(sql)

    assert {(ref.database, ref.schema, ref.name) for ref in result.referenced_objects} == {
        ("Warehouse", "sales", "Orders"),
        (None, "dbo", "Customers"),
    }
    assert result.definitions[0].name == "Open Orders"


def test_multiple_definitions_across_batches_keep_individual_dependencies() -> None:
    sql = """
    CREATE VIEW dbo.FirstView AS SELECT * FROM dbo.FirstTable
    GO
    ALTER VIEW dbo.SecondView AS SELECT * FROM [Archive].[dbo].[SecondTable]
    GO
    """

    result = SqlParser().parse_text(sql)

    assert [(definition.operation, definition.name) for definition in result.definitions] == [
        ("CREATE", "FirstView"),
        ("ALTER", "SecondView"),
    ]
    assert [
        [(reference.database, reference.schema, reference.name) for reference in definition.referenced_objects]
        for definition in result.definitions
    ] == [
        [(None, "dbo", "FirstTable")],
        [("Archive", "dbo", "SecondTable")],
    ]
    assert result.created_objects[1].name == "SecondView"
    assert "2 objects" in result.to_parsed_document().title


def test_alter_procedure_fallback_preserves_parameters_and_access_kind() -> None:
    sql = """
    ALTER PROCEDURE dbo.RefreshData @batchSize INT = 100, @force BIT OUTPUT
    AS
    BEGIN
        INSERT INTO dbo.Target SELECT * FROM dbo.Source;
        EXEC dbo.ValidateBatch @batchSize;
    END
    """

    definition = SqlParser().parse_text(sql).definitions[0]

    assert definition.operation == "ALTER"
    assert [(parameter.name, parameter.default, parameter.output) for parameter in definition.parameters] == [
        ("batchSize", "100", False),
        ("force", None, True),
    ]
    assert {(ref.name, ref.kind) for ref in definition.referenced_objects} == {
        ("Target", "write"),
        ("Source", "read"),
        ("ValidateBatch", "execute"),
    }


def test_regex_fallback_masks_comments_and_string_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = """
    -- CREATE VIEW dbo.Decoy AS SELECT * FROM dbo.CommentTable
    CREATE VIEW dbo.RealView AS
    SELECT * FROM dbo.RealTable
    WHERE Note = 'FROM dbo.StringTable'
    """

    def reject_ast(*args: object, **kwargs: object) -> None:
        raise ParseError("unsupported T-SQL syntax")

    monkeypatch.setattr(sql_parser_module, "parse", reject_ast)
    definition = SqlParser().parse_text(sql).definitions[0]

    assert definition.name == "RealView"
    assert [(reference.name, reference.kind) for reference in definition.referenced_objects] == [
        ("RealTable", "read")
    ]


def test_parser_service_returns_ingestion_document_for_sql_file(tmp_path: Path) -> None:
    sql_file = tmp_path / "objects.sql"
    sql_file.write_text(
        "CREATE VIEW dbo.Items AS SELECT * FROM dbo.SourceItems",
        encoding="utf-8",
    )

    parsed = ParserService().parse_file(sql_file)

    assert isinstance(parsed, ParsedDocument)
    assert parsed.object_type is ParsedObjectType.VIEW
    assert parsed.metadata["definitions"][0]["name"] == "Items"