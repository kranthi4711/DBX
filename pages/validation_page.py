import streamlit as st
import pandas as pd

from validator import read_testcase_excel, long_to_wide, parse_settings, compare_frames

st.set_page_config(page_title="Validation", layout="wide")

st.title("Pipeline Validation")
st.caption("Upload a testcase Excel with Inputs/Expected/Settings. This page compares actual vs expected and shows pass/fail.")

uploaded = st.file_uploader("Upload testcase Excel", type=["xlsx"]) 

st.warning("This validation page compares using pandas only. For Spark execution, connect it to your pipeline runner and produce actual outputs as pandas DataFrames.")

if not uploaded:
    st.stop()

cases = read_testcase_excel(uploaded)

case_name = st.selectbox("Select test case", list(cases.keys()))
case = cases[case_name]

settings = parse_settings(case['settings'])
mode = settings.get('CompareMode', 'keyed')
try:
    tol = float(settings.get('ToleranceNumeric', '0') or 0)
except Exception:
    tol = 0.0

st.subheader("Inputs")
st.dataframe(case['inputs'], use_container_width=True)

st.subheader("Expected")
st.dataframe(case['expected'], use_container_width=True)

# Pivot long format into wide frames
inputs_long = case['inputs']
expected_long = case['expected']

# Build input datasets map
input_aliases = sorted(inputs_long['DatasetAlias'].unique().tolist())

st.markdown("### Build actual outputs")
st.info("Hook point: You should run your pipeline using these input datasets and produce outputs as pandas DataFrames.\n\nFor now, we demonstrate validation by treating expected outputs as the actual outputs (placeholder).")

# Placeholder: actual_outputs = expected outputs (so it passes)
actual_outputs = {}

# Expected outputs wide per alias
exp_outputs = {}
for out_alias in sorted(expected_long['OutputAlias'].unique().tolist()):
    sub = expected_long[expected_long['OutputAlias'] == out_alias]
    wide = long_to_wide(sub, key_cols=['RowId'], col_name='Column', value_name='Value')
    exp_outputs[out_alias] = wide.drop(columns=['RowId'], errors='ignore')
    actual_outputs[out_alias] = exp_outputs[out_alias].copy()

results = []
diff_details = {}

for out_alias, exp_df in exp_outputs.items():
    act_df = actual_outputs.get(out_alias, pd.DataFrame())

    pk_key = f"PrimaryKey:{out_alias}"
    pk = [x.strip() for x in settings.get(pk_key, '').split(',') if x.strip()]

    summary, detail = compare_frames(act_df, exp_df, pk=pk, mode=mode, tol=tol)
    results.append({
        'TestCase': case_name,
        'OutputAlias': out_alias,
        'Mode': mode,
        'PrimaryKey': ','.join(pk) if pk else '',
        'Passed': summary.passed,
        'MissingRows': summary.missing_rows,
        'ExtraRows': summary.extra_rows,
        'MismatchedCells': summary.mismatched_cells,
        'Message': summary.message,
    })
    diff_details[out_alias] = detail

res_df = pd.DataFrame(results)

st.subheader("Validation result")
st.dataframe(res_df, use_container_width=True)

# Summary banner
if res_df['Passed'].all():
    st.success("✅ All validations passed")
else:
    st.error("❌ Some validations failed. Review the details below.")

st.divider()
st.subheader("Actual vs Expected comparison")

out_sel = st.selectbox("Select output", list(exp_outputs.keys()))
col1, col2 = st.columns(2)
with col1:
    st.markdown("**Expected**")
    st.dataframe(exp_outputs[out_sel], use_container_width=True)
with col2:
    st.markdown("**Actual**")
    st.dataframe(actual_outputs[out_sel], use_container_width=True)

st.markdown("### Differences")
d = diff_details.get(out_sel)
if d is None or d.empty:
    st.write("No differences")
else:
    st.dataframe(d, use_container_width=True)
