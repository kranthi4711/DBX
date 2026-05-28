from io import BytesIO
import json
import zipfile


def build_export_zip(pipeline_name: str, code_text: str, pipeline_json: dict, excel_bytes: bytes) -> bytes:
    bio = BytesIO()
    safe = "".join([c if c.isalnum() or c in "-_" else "_" for c in (pipeline_name or "pipeline")])

    with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{safe}.py", code_text)
        z.writestr(f"{safe}.json", json.dumps(pipeline_json, indent=2, ensure_ascii=False))
        z.writestr(f"{safe}.xlsx", excel_bytes)

    return bio.getvalue()
