import json
from io import BytesIO
from typing import Dict, List
from zipfile import ZIP_DEFLATED, ZipFile


def _safe_id(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (name or "visual"))
    cleaned = cleaned.strip("_") or "visual"
    return cleaned.lower()


def build_bi_manifest(
    pipeline_name: str,
    raw_tables: List[str],
    target_tables: List[str],
    kpis: List[str],
    visuals: List[Dict[str, str]],
) -> Dict:
    return {
        "pipeline_name": pipeline_name,
        "raw_tables": raw_tables,
        "target_tables": target_tables,
        "kpis": kpis,
        "visuals": visuals,
    }


def generate_python_visual_app(manifest: Dict) -> str:
    visuals = manifest.get("visuals", [])
    visual_blocks = []

    for idx, vis in enumerate(visuals, start=1):
        vtype = vis.get("visual_type", "bar")
        title = vis.get("title", f"Visual {idx}")
        x_axis = vis.get("x_axis", "category")
        y_axis = vis.get("y_axis", "value")
        color = vis.get("color_by", "")

        color_expr = f", color='{color}'" if color else ""
        visual_blocks.append(
            "\n".join(
                [
                    f"st.markdown('### {title}')",
                    f"fig_{idx} = px.{vtype}(df, x='{x_axis}', y='{y_axis}'{color_expr}, title='{title}', template='plotly_white')",
                    f"fig_{idx}.update_layout(height=460, margin=dict(l=30, r=30, t=60, b=30))",
                    f"st.plotly_chart(fig_{idx}, use_container_width=True)",
                ]
            )
        )

    visual_code = "\n\n".join(visual_blocks) if visual_blocks else "st.info('No visuals defined yet.')"

    raw_tables = manifest.get("raw_tables", [])
    target_tables = manifest.get("target_tables", [])
    kpis = manifest.get("kpis", [])

    return f'''import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Auto BI Visuals", layout="wide")

st.title("Auto BI Visuals")
st.caption("Generated from Databricks PySpark Pipeline Designer")

st.markdown("### Data Context")
st.write("Raw tables:", {raw_tables})
st.write("Target tables:", {target_tables})
st.write("KPI list:", {kpis})

uploaded = st.file_uploader("Upload data CSV for preview", type=["csv"])
if not uploaded:
    st.info("Upload a CSV to render visuals with your data.")
    st.stop()

df = pd.read_csv(uploaded)
{visual_code}
'''


def generate_js_visual_html(manifest: Dict) -> str:
    visuals = manifest.get("visuals", [])

    containers = []
    scripts = []

    for idx, vis in enumerate(visuals, start=1):
        vid = _safe_id(vis.get("title", f"visual_{idx}")) + f"_{idx}"
        title = vis.get("title", f"Visual {idx}")
        vtype = vis.get("visual_type", "bar")
        x_axis = vis.get("x_axis", "category")
        y_axis = vis.get("y_axis", "value")

        containers.append(f'<div class="card"><h3>{title}</h3><div id="{vid}" class="chart"></div></div>')

        scripts.append(
            f"""
const trace{idx} = {{
  type: '{vtype}',
  x: sampleData.map(r => r['{x_axis}']),
  y: sampleData.map(r => r['{y_axis}']),
  marker: {{color: '#0ea5e9'}},
}};
Plotly.newPlot('{vid}', [trace{idx}], {{
  paper_bgcolor: '#ffffff',
  plot_bgcolor: '#f8fafc',
  margin: {{l: 50, r: 20, t: 20, b: 50}}
}}, {{responsive: true}});
""".strip()
        )

    cards = "\n".join(containers) if containers else "<p>No visuals defined.</p>"
    script = "\n\n".join(scripts)

    return f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>Auto BI Visuals</title>
  <script src=\"https://cdn.plot.ly/plotly-2.35.2.min.js\"></script>
  <style>
    :root {{
      --bg: #f1f5f9;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #334155;
      --accent: #0ea5e9;
    }}
    body {{
      margin: 0;
      font-family: 'Segoe UI', Tahoma, sans-serif;
      background: radial-gradient(circle at 10% 10%, #dbeafe 0%, var(--bg) 45%);
      color: var(--ink);
    }}
    .wrap {{
      max-width: 1200px;
      margin: 24px auto;
      padding: 0 14px;
    }}
    .hero {{
      background: linear-gradient(120deg, #0ea5e9, #0284c7);
      color: white;
      padding: 18px 20px;
      border-radius: 14px;
      box-shadow: 0 12px 28px rgba(2, 132, 199, 0.25);
    }}
    .grid {{
      margin-top: 16px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--card);
      border-radius: 14px;
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
      padding: 10px 12px;
    }}
    .card h3 {{
      margin: 6px 0 8px;
      color: var(--muted);
    }}
    .chart {{
      width: 100%;
      height: 360px;
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"hero\">
      <h2 style=\"margin:0\">Auto BI Visuals (JavaScript)</h2>
      <p style=\"margin:6px 0 0\">Generated from pipeline metadata and KPI settings.</p>
    </div>
    <div class=\"grid\">{cards}</div>
  </div>

<script>
const sampleData = [
  {{ category: 'A', value: 120, segment: 'North' }},
  {{ category: 'B', value: 95, segment: 'South' }},
  {{ category: 'C', value: 140, segment: 'East' }},
  {{ category: 'D', value: 80, segment: 'West' }}
];

{script}
</script>
</body>
</html>
"""


def build_powerbi_handoff_zip(manifest: Dict) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("bi_manifest.json", json.dumps(manifest, indent=2))

        lines = [
            "Power BI Handoff Package",
            "",
            "This package contains metadata for automated report creation.",
            "A true .pbix binary cannot be generated directly by this app.",
            "Use bi_manifest.json with your Power BI automation process (REST API / Tabular Editor / deployment pipelines).",
            "",
            "Included files:",
            "- bi_manifest.json",
            "- kpis.txt",
            "- visuals.csv",
        ]
        zf.writestr("README.txt", "\n".join(lines))

        zf.writestr("kpis.txt", "\n".join(manifest.get("kpis", [])))

        visual_rows = ["title,visual_type,x_axis,y_axis,color_by,dataset_alias"]
        for v in manifest.get("visuals", []):
            visual_rows.append(
                ",".join(
                    [
                        (v.get("title") or "").replace(",", " "),
                        (v.get("visual_type") or "").replace(",", " "),
                        (v.get("x_axis") or "").replace(",", " "),
                        (v.get("y_axis") or "").replace(",", " "),
                        (v.get("color_by") or "").replace(",", " "),
                        (v.get("dataset_alias") or "").replace(",", " "),
                    ]
                )
            )
        zf.writestr("visuals.csv", "\n".join(visual_rows))

    buffer.seek(0)
    return buffer.getvalue()
