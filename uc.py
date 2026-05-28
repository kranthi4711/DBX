"""
Unity Catalog browser with optional Demo Excel mode.

Why this exists
--------------
In Databricks, Unity Catalog metadata is available through the SparkSession already configured
for the workspace (no explicit connection string needed).

For local/demo runs (or client demos without workspace access), this module can operate in a
"demo mode" powered by an uploaded Excel file.

Demo Excel schema
-----------------
Provide an Excel sheet with columns:
- CatalogName
- SchemaName
- TableName
- ColumnNames  (comma/semicolon-separated, e.g. "id,name,amount")

Notes:
- Column headers are matched case-insensitively.
- Common variants like "catalogueName" are also accepted.
- Dropdowns are populated with UNIQUE values.

Usage
-----
browser = UCBrowser()                       # normal mode (Databricks)
browser = UCBrowser(demo_excel=bytes_data)  # demo mode from uploaded Excel (bytes)
browser = UCBrowser(demo_excel="path.xlsx", force_demo=True)

Streamlit example
-----------------
uploaded = st.file_uploader("Demo UC Excel", type=["xlsx"])
if uploaded:
    browser = UCBrowser(demo_excel=uploaded.getvalue(), force_demo=True, demo_sheet="UC")
else:
    browser = UCBrowser()
"""

from __future__ import annotations

from typing import Dict, List, Optional, Union
from io import BytesIO


class UCBrowser:
    def __init__(
        self,
        demo_excel: Optional[Union[str, bytes, BytesIO]] = None,
        demo_sheet: Union[int, str] = 0,
        force_demo: bool = False,
    ):
        self.spark = None
        self._demo = True
        # index: catalog -> schema -> table -> [columns]
        self._demo_index: Dict[str, Dict[str, Dict[str, List[str]]]] = {}

        if not force_demo:
            try:
                # In Databricks, spark is available and configured for Unity Catalog.
                from pyspark.sql import SparkSession  # noqa

                self.spark = SparkSession.builder.getOrCreate()
                self._demo = False
            except Exception:
                self.spark = None
                self._demo = True

        # If demo is forced or spark couldn't be created, optionally load demo excel.
        if self._demo and demo_excel is not None:
            self.load_demo_excel(demo_excel=demo_excel, demo_sheet=demo_sheet)

    # --------------------- Public API (used by app.py) ---------------------
    def catalogs(self) -> List[str]:
        if self._demo:
            return sorted(self._demo_index.keys())
        rows = self.spark.sql("SHOW CATALOGS").collect()
        return sorted([r[0] for r in rows])

    def schemas(self, catalog: str) -> List[str]:
        if not catalog:
            return []
        if self._demo:
            return sorted(self._demo_index.get(catalog, {}).keys())
        rows = self.spark.sql(f"SHOW SCHEMAS IN {catalog}").collect()
        return sorted([r[0] for r in rows])

    def tables(self, catalog: str, schema: str) -> List[str]:
        if not (catalog and schema):
            return []
        if self._demo:
            return sorted(self._demo_index.get(catalog, {}).get(schema, {}).keys())

        rows = self.spark.sql(f"SHOW TABLES IN {catalog}.{schema}").collect()
        out = []
        for r in rows:
            # SHOW TABLES output varies; pick last string field
            for v in list(r)[::-1]:
                if isinstance(v, str):
                    out.append(v)
                    break
        return sorted(list(set(out)))

    def columns_from_fullname(self, full_name: str) -> List[str]:
        if not full_name or full_name.count(".") != 2:
            return []
        if self._demo:
            catalog, schema, table = full_name.split(".")
            return list(self._demo_index.get(catalog, {}).get(schema, {}).get(table, []))
        return self.spark.table(full_name).columns

    # --------------------- Demo Excel helpers ---------------------
    def load_demo_excel(self, demo_excel: Union[str, bytes, BytesIO], demo_sheet: Union[int, str] = 0) -> None:
        """
        Load demo metadata from Excel.

        demo_excel can be:
        - path to .xlsx
        - bytes (uploaded file)
        - BytesIO
        """
        import pandas as pd

        if isinstance(demo_excel, BytesIO):
            bio = demo_excel
        elif isinstance(demo_excel, bytes):
            bio = BytesIO(demo_excel)
        elif isinstance(demo_excel, str):
            bio = demo_excel
        else:
            raise TypeError("demo_excel must be a path (str), bytes, or BytesIO")

        df = pd.read_excel(bio, sheet_name=demo_sheet, engine="openpyxl")
        if df is None or df.empty:
            self._demo_index = {}
            return

        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        # Accept multiple header variants (case-insensitive)
        colmap = {c.lower(): c for c in df.columns}

        def pick(*names: str) -> Optional[str]:
            for n in names:
                if n.lower() in colmap:
                    return colmap[n.lower()]
            return None

        c_catalog = pick("CatalogName", "catalogName", "catalog", "catalogueName", "catalogue")
        c_schema = pick("SchemaName", "schemaName", "schema", "database", "databaseName")
        c_table = pick("TableName", "tableName", "table")
        c_cols = pick("ColumnNames", "columns", "columnNames", "column_list")

        # NEW: support multiple column fields like ColumnName1, ColumnName2, ...
        
        multi_col_fields = []
        for c in df.columns:
            name = str(c).strip()
            low = name.lower()

            if low in ("columnnames", "columnname", "columns", "column_names","ColumnNames"):
                continue  # exclude the single-cell list column

            if low.startswith("ColumnNames") or low.startswith("column"):
                multi_col_fields.append(name)

        # Ensure a stable ordering: Column1, Column2, Column3...
        def _col_sort_key(colname: str):
            import re
            m = re.search(r"(\\d+)$", colname.strip())
            return (0, int(m.group(1))) if m else (1, colname.lower())

        multi_col_fields = sorted(multi_col_fields, key=_col_sort_key)

        missing = [
            k for k, v in {
                "CatalogName": c_catalog,
                "SchemaName": c_schema,
                "TableName": c_table,
                "ColumnNames": c_cols
            }.items()
            if v is None
        ]
        if missing:
            raise ValueError(f"Demo Excel missing required columns: {', '.join(missing)}")

        # Normalize values
        df[c_catalog] = df[c_catalog].astype(str).str.strip()
        df[c_schema] = df[c_schema].astype(str).str.strip()
        df[c_table] = df[c_table].astype(str).str.strip()
        df[c_cols] = df[c_cols].fillna("").astype(str).str.strip()

        index: Dict[str, Dict[str, Dict[str, List[str]]]] = {}

        for _, row in df.iterrows():
            catalog = row[c_catalog]
            schema = row[c_schema]
            table = row[c_table]
            cols = []

            # Case 1: Columns provided across multiple Excel columns (ColumnName1..N)
            if multi_col_fields:
                for c in multi_col_fields:
                    v = row.get(c, "")
                    if v is None:
                        continue
                    v = str(v).strip()
                    if v and v.lower() != "nan":
                        cols.append(v)

            # Case 2: Fallback to single ColumnNames cell (comma/semicolon/pipe separated)
            elif c_cols is not None:
                cols_raw = row.get(c_cols, "")
                if cols_raw is not None:
                    raw = str(cols_raw).strip()
                    if raw and raw.lower() != "nan":
                        raw = raw.replace("|", ",").replace(";", ",").replace("\n", ",").replace("\r", ",")
                        # Handle python-list style: ['a','b']
                        if raw.startswith("[") and raw.endswith("]"):
                            raw = raw[1:-1].replace("'", "").replace('"', "")
                        for token in raw.split(","):
                            t = token.strip()
                            if t:
                                cols.append(t)

            # De-duplicate while preserving order
            seen = set()
            cols_unique = []
            for c in cols:
                if c not in seen:
                    seen.add(c)
                    cols_unique.append(c)

            # Get existing list for this table (if any)
            tbl_dict = index.setdefault(catalog, {}).setdefault(schema, {})
            existing = tbl_dict.get(table, [])

            # Append new cols and keep unique order
            seen = set(existing)
            for c in cols_unique:
                if c not in seen:
                    existing.append(c)
                    seen.add(c)

            tbl_dict[table] = existing

            if not catalog or str(catalog).lower() == "nan":
                continue
            if not schema or str(schema).lower() == "nan":
                continue
            if not table or str(table).lower() == "nan":
                continue

            # Split columns by comma/semicolon/pipe
            cols = []
            if cols_raw and str(cols_raw).lower() != "nan":
                for token in str(cols_raw).replace("|", ",").replace(";", ",").split(","):
                    t = token.strip()
                    if t:
                        cols.append(t)

            # Ensure unique column names preserving order
            seen = set()
            cols_unique = []
            for c in cols:
                if c not in seen:
                    seen.add(c)
                    cols_unique.append(c)

            # ---------- ACCUMULATE columns instead of overwriting ----------
            tbl_dict = index.setdefault(catalog, {}).setdefault(schema, {})

            # get existing cols for the table (if any)
            existing = tbl_dict.get(table, [])

            # append new columns while preserving order + uniqueness
            seen = set(existing)
            for c in cols_unique:
                if c and c not in seen:
                    existing.append(c)
                    seen.add(c)

            tbl_dict[table] = existing
            # --------------------------------------------------------------

        self._demo_index = index
        self._demo = True

    def is_demo(self) -> bool:
        return bool(self._demo)