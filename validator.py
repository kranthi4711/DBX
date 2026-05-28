from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import pandas as pd


@dataclass
class DiffSummary:
    passed: bool
    message: str
    missing_rows: int = 0
    extra_rows: int = 0
    mismatched_cells: int = 0


def _cast_series(s: pd.Series, dtype: str) -> pd.Series:
    dtype = (dtype or 'string').lower()
    if dtype in ('int', 'integer', 'bigint'):
        return pd.to_numeric(s, errors='coerce').astype('Int64')
    if dtype in ('double', 'float', 'decimal', 'numeric'):
        return pd.to_numeric(s, errors='coerce')
    if dtype in ('bool', 'boolean'):
        return s.astype(str).str.lower().map({'true': True, 'false': False}).astype('boolean')
    # date/timestamp left as string; Spark-side casting is recommended if needed
    return s.astype(str)


def long_to_wide(df_long: pd.DataFrame, key_cols: List[str], col_name: str, value_name: str) -> pd.DataFrame:
    """Pivot long format (RowId, Column, Value) into a row-per-record dataframe."""
    wide = df_long.pivot_table(index=key_cols, columns=col_name, values=value_name, aggfunc='first').reset_index()
    wide.columns = [str(c) for c in wide.columns]
    return wide


def read_testcase_excel(path_or_bytes) -> Dict[str, Dict[str, pd.DataFrame]]:
    """Return dict[TestCase] = {'inputs':df, 'expected':df, 'settings':df}."""
    xl = pd.ExcelFile(path_or_bytes, engine='openpyxl')
    inputs = pd.read_excel(xl, 'Inputs')
    expected = pd.read_excel(xl, 'Expected')
    settings = pd.read_excel(xl, 'Settings')

    out = {}
    for tc in sorted(set(inputs['TestCase']).union(set(expected['TestCase']))):
        out[tc] = {
            'inputs': inputs[inputs['TestCase'] == tc].copy(),
            'expected': expected[expected['TestCase'] == tc].copy(),
            'settings': settings[settings['TestCase'] == tc].copy() if 'TestCase' in settings.columns else settings.copy(),
        }
    return out


def parse_settings(df_settings: pd.DataFrame) -> Dict[str, str]:
    kv = {}
    if df_settings is None or df_settings.empty:
        return kv
    for _, r in df_settings.iterrows():
        k = str(r.get('Key', '')).strip()
        v = str(r.get('Value', '')).strip()
        if k:
            kv[k] = v
    return kv


def compare_frames(actual: pd.DataFrame, expected: pd.DataFrame, pk: List[str] | None, mode: str = 'keyed', tol: float = 0.0) -> Tuple[DiffSummary, pd.DataFrame]:
    """Compare two pandas dataframes and return summary + detailed diff rows."""

    mode = (mode or 'keyed').lower()
    if actual is None:
        actual = pd.DataFrame()
    if expected is None:
        expected = pd.DataFrame()

    # Align columns
    all_cols = sorted(set(actual.columns).union(set(expected.columns)))
    actual2 = actual.reindex(columns=all_cols)
    expected2 = expected.reindex(columns=all_cols)

    details = []

    if mode == 'ordered':
        if len(actual2) != len(expected2):
            return DiffSummary(False, f'Row count mismatch: actual={len(actual2)} expected={len(expected2)}', extra_rows=max(0, len(actual2)-len(expected2)), missing_rows=max(0, len(expected2)-len(actual2))), pd.DataFrame()
        mismatched = 0
        for i in range(len(expected2)):
            for c in all_cols:
                av = actual2.iloc[i][c]
                ev = expected2.iloc[i][c]
                if pd.isna(av) and pd.isna(ev):
                    continue
                if isinstance(av, (int, float)) and isinstance(ev, (int, float)) and tol:
                    if pd.isna(av) or pd.isna(ev) or abs(av-ev) > tol:
                        mismatched += 1
                        details.append({'row': i, 'column': c, 'expected': ev, 'actual': av, 'type': 'mismatch'})
                elif str(av) != str(ev):
                    mismatched += 1
                    details.append({'row': i, 'column': c, 'expected': ev, 'actual': av, 'type': 'mismatch'})
        passed = mismatched == 0
        return DiffSummary(passed, 'OK' if passed else f'{mismatched} mismatched cells', mismatched_cells=mismatched), pd.DataFrame(details)

    if mode in ('unordered', 'set'):
        # Compare as sets of rows (stringified)
        a_set = set(tuple(x) for x in actual2.fillna('<NA>').astype(str).values.tolist())
        e_set = set(tuple(x) for x in expected2.fillna('<NA>').astype(str).values.tolist())
        missing = e_set - a_set
        extra = a_set - e_set
        for r in missing:
            details.append({'type': 'missing_row', 'expected_row': r})
        for r in extra:
            details.append({'type': 'extra_row', 'actual_row': r})
        passed = (not missing) and (not extra)
        return DiffSummary(passed, 'OK' if passed else 'Row set mismatch', missing_rows=len(missing), extra_rows=len(extra)), pd.DataFrame(details)

    # keyed (default)
    pk = pk or []
    if not pk:
        # fallback to unordered
        return compare_frames(actual2, expected2, pk=None, mode='unordered', tol=tol)

    for k in pk:
        if k not in all_cols:
            return DiffSummary(False, f'Primary key column not found: {k}'), pd.DataFrame()

    a = actual2.set_index(pk)
    e = expected2.set_index(pk)

    missing_idx = e.index.difference(a.index)
    extra_idx = a.index.difference(e.index)

    for idx in missing_idx:
        details.append({'type': 'missing_key', 'key': idx})
    for idx in extra_idx:
        details.append({'type': 'extra_key', 'key': idx})

    common_idx = e.index.intersection(a.index)
    mismatched = 0

    for idx in common_idx:
        for c in all_cols:
            if c in pk:
                continue
            av = a.loc[idx, c]
            ev = e.loc[idx, c]
            if pd.isna(av) and pd.isna(ev):
                continue
            if isinstance(av, (int, float)) and isinstance(ev, (int, float)) and tol:
                if pd.isna(av) or pd.isna(ev) or abs(av-ev) > tol:
                    mismatched += 1
                    details.append({'type': 'mismatch', 'key': idx, 'column': c, 'expected': ev, 'actual': av})
            elif str(av) != str(ev):
                mismatched += 1
                details.append({'type': 'mismatch', 'key': idx, 'column': c, 'expected': ev, 'actual': av})

    passed = (len(missing_idx) == 0) and (len(extra_idx) == 0) and (mismatched == 0)
    return DiffSummary(passed, 'OK' if passed else 'Differences found', missing_rows=len(missing_idx), extra_rows=len(extra_idx), mismatched_cells=mismatched), pd.DataFrame(details)
