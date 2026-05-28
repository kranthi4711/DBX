from io import BytesIO
import pandas as pd


def export_pipeline_to_excel(pipeline: dict) -> bytes:
    bio = BytesIO()

    overview = pd.DataFrame([
        {
            "Name": pipeline.get("name", ""),
            "Description": pipeline.get("description", ""),
            "Output Target": f"{pipeline.get('output_catalog','')}.{pipeline.get('output_schema','')}.{pipeline.get('output_table','')}".strip("."),
            "Sources": len(pipeline.get("sources", [])),
            "Steps": len(pipeline.get("steps", [])),
        }
    ])

    sources_df = pd.DataFrame(pipeline.get("sources", []))
    steps_df = pd.DataFrame(pipeline.get("steps", []))

    if not steps_df.empty and "params" in steps_df.columns:
        steps_df["params"] = steps_df["params"].apply(lambda x: "{}" if x is None else json_safe(x))

    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="Overview", index=False)
        sources_df.to_excel(w, sheet_name="Sources", index=False)
        steps_df.to_excel(w, sheet_name="Steps", index=False)

    return bio.getvalue()


def json_safe(x):
    try:
        import json
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)
