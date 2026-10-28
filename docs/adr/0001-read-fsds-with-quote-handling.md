# 1. Read FSDS files with quote handling on

**Context:** The plan said FSDS files are unquoted, but 2026q3's num.txt quotes fields that contain tabs; read unquoted, 14 rows were rejected and others were silently shifted.
**Decision:** Parse with `quote='"'`; reconciliation against manifest line counts catches any misparse.
**Consequences:** No shifted columns; investment-fund segments parse intact; a test pins the exact case.
