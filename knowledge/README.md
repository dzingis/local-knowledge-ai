# Knowledge folder

Put files in the folder that best matches their format. The watcher scans this
tree recursively when it is configured to watch the repository's `knowledge`
folder.

```text
knowledge/
  documents/
    pdf/
    word/
    markdown/
    text/
  code/
    sql/
    delphi/
  api/
    openapi/
  other/
```

- `documents/pdf/`: PDF files
- `documents/word/`: Word documents (`.docx`)
- `documents/markdown/`: Markdown files (`.md`)
- `documents/text/`: plain-text documentation
- `code/sql/`: SQL scripts and queries
- `code/delphi/`: Delphi source and project files
- `api/openapi/`: OpenAPI and Swagger specifications
- `other/`: supported files that do not fit another category

Subfolders are also watched. Keep temporary or partially copied files out of the
tree until complete; common temporary suffixes and Office lock files are ignored.
