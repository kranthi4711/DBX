# Databricks PySpark Pipeline Designer (Client-facing) — v4

## What’s new
- ✅ **Edit step** (loads step into the form)
- ✅ **Delete step** (delete any step) + **Delete last step**
- ✅ **Multiple output targets** (write to more than one Unity Catalog table) — exported as **commented** write statements
- ✅ **BI Visual Studio page** (KPI-driven visual planning with Python/JS output and Power BI handoff package)

## Capabilities
- Browse Unity Catalog to choose source tables
- Dropdown-driven transformation builder
- Built-in demo Excel workbook with sample customers, products, orders, and order_items metadata plus dummy data sheets
- Diagram view (Source → Transform → Output alias → Target tables)
- BI Visual Studio page in Streamlit sidebar/pages:
  - Select raw and target tables
  - Enter KPI list
  - Define additional visuals (x-axis, y-axis, visual type, color)
  - Generate either Python Plotly app code or JavaScript HTML visuals
  - Download Power BI handoff package (manifest + KPI + visuals metadata)
- Export ZIP containing:
  - Generated PySpark code (.py)
  - Pipeline definition (.json)
  - Documentation (.xlsx) with Overview/Sources/Steps/Outputs

## Run in Databricks
Upload to a Databricks Repo and create a Streamlit app from `app.py`.

## Notes
This tool is **preview/export only**. It does not execute transformations or write tables.
