import io
import os
from datetime import date
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="기온 비교(같은 날짜 대비)", layout="wide")


# -----------------------------
# Data loading utilities
# -----------------------------
def _find_header_line_index(lines: list[str]) -> int:
    """
    KMA-like CSVs sometimes have metadata rows before the real header.
    We scan lines and find the first line that contains the expected header tokens.
    """
    for i, line in enumerate(lines):
        s = line.strip().replace("\ufeff", "")  # BOM guard
        # Heuristic: must contain these tokens
        if ("날짜" in s) and ("지점" in s) and ("평균기온" in s) and ("최저기온" in s) and ("최고기온" in s):
            return i
    return -1


def read_kma_csv(file_like_or_path) -> pd.DataFrame:
    """
    Reads CSV that may include metadata lines on top.
    Accepts: file path (str) or file-like (BytesIO/StringIO).
    Returns cleaned dataframe with columns:
      date, station, tavg, tmin, tmax, month, day, year
    """
    # Read raw text
    if isinstance(file_like_or_path, str):
        with open(file_like_or_path, "rb") as f:
            raw = f.read()
    else:
        raw = file_like_or_path.read()
        # reset pointer for potential re-reads
        try:
            file_like_or_path.seek(0)
        except Exception:
            pass

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    header_idx = _find_header_line_index(lines)

    if header_idx == -1:
        raise ValueError("CSV에서 헤더(날짜/지점/평균기온/최저기온/최고기온)를 찾지 못했습니다. 형식을 확인해주세요.")

    data_text = "\n".join(lines[header_idx:])

    df = pd.read_csv(io.StringIO(data_text))

    # Normalize/rename
    expected = ["날짜", "지점", "평균기온(℃)", "최저기온(℃)", "최고기온(℃)"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}")

    df = df[expected].copy()

    # Clean date strings (often includes tabs)
    df["날짜"] = df["날짜"].astype(str).str.strip()

    # Parse dates
    df["date"] = pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()

    # Convert station & temps
    df["station"] = pd.to_numeric(df["지점"], errors="coerce")
    df["tavg"] = pd.to_numeric(df["평균기온(℃)"], errors="coerce")
    df["tmin"] = pd.to_numeric(df["최저기온(℃)"], errors="coerce")
    df["tmax"] = pd.to_numeric(df["최고기온(℃)"], errors="coerce")

    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["day"] = df["date"].dt.day

    # Keep only station rows that exist
    df = df.dropna(subset=["station"]).copy()
    df["station"] = df["station"].astype(int)

    return df.sort_values("date").reset_index(drop=True)


def pick_default_date(df: pd.DataFrame) -> date:
    # choose most recent date with at least one of (tavg,tmin,tmax) not null
    df2 = df.dropna(subset=["tavg", "tmin", "tmax"], how="all")
    if df2.empty:
        # fallback: last date in dataset
        return df["date"].max().date()
    return df2["date"].max().date()


# -----------------------------
# UI
# -----------------------------
st.title("🌡️ 같은 날짜(월-일) 기준 기온 비교")

with st.sidebar:
    st.header("데이터")
    st.write("기본 데이터는 리포지토리에 포함된 CSV를 읽고, 업로드하면 업로드한 데이터로 자동 전환됩니다.")
    uploaded = st.file_uploader("같은 형식의 CSV 업로드", type=["csv"])

    default_path = "ta_20260122174530-1.csv"  # 리포지토리에 이 이름으로 넣어두는 것을 권장
    st.caption(f"기본 파일 경로: {default_path} (없으면 앱이 오류를 냅니다)")

    st.header("비교 설정")
    metric = st.selectbox("비교할 지표", ["평균기온(tavg)", "최저기온(tmin)", "최고기온(tmax)"], index=0)
    baseline = st.selectbox("기준값", ["역대 평균", "역대 중앙값"], index=0)

    st.header("날짜")
    st.caption("날짜를 선택하지 않으면 데이터의 가장 최근 날짜로 자동 설정됩니다.")


# Load data
try:
    if uploaded is not None:
        df = read_kma_csv(uploaded)
        data_label = f"업로드 데이터 ({uploaded.name})"
    else:
        if not os.path.exists(default_path):
            st.error(f"기본 데이터 파일을 찾을 수 없습니다: {default_path}\n"
                     f"Streamlit Cloud 리포지토리 루트에 이 파일을 업로드/커밋해주세요.")
            st.stop()
        df = read_kma_csv(default_path)
        data_label = f"기본 데이터 ({default_path})"
except Exception as e:
    st.error(f"데이터 로딩 실패: {e}")
    st.stop()

st.caption(f"사용 중인 데이터: **{data_label}** · 기간: {df['date'].min().date()} ~ {df['date'].max().date()} · 행: {len(df):,}")

# Date selector default
default_dt = pick_default_date(df)
target_dt = st.date_input("비교할 날짜", value=default_dt)

m = target_dt.month
d = target_dt.day

# Filter same month-day across years
same_md = df[(df["month"] == m) & (df["day"] == d)].copy()

# Choose value column
col = {"평균기온(tavg)": "tavg", "최저기온(tmin)": "tmin", "최고기온(tmax)": "tmax"}[metric]

# Target row (exact date) - may be missing if dataset doesn't include it
target_row = df[df["date"].dt.date == target_dt].copy()
target_val = None
station = None
if not target_row.empty:
    target_val = target_row.iloc[-1][col]
    station = target_row.iloc[-1]["station"]

# Build historical baseline excluding target year? (keep simple: include all available years)
hist = same_md.dropna(subset=[col]).copy()

if hist.empty:
    st.warning("선택한 날짜(월-일)에 대한 유효한 과거 데이터가 없습니다.")
    st.stop()

if baseline == "역대 평균":
    base_val = hist[col].mean()
else:
    base_val = hist[col].median()

# Rank / percentile
# Define percentile as position within sorted historical (including target if available)
sorted_vals = hist[col].sort_values().reset_index(drop=True)
if target_val is not None and pd.notna(target_val):
    # percentile: fraction <= target
    pct = (sorted_vals <= target_val).mean() * 100.0
    # rank: 1 = coldest (min) or 1 = hottest? We'll provide both.
    cold_rank = int((sorted_vals < target_val).sum()) + 1
    hot_rank = int((sorted_vals > target_val).sum()) + 1
else:
    pct = None
    cold_rank = None
    hot_rank = None

anomaly = None
if target_val is not None and pd.notna(target_val):
    anomaly = float(target_val - base_val)

# Summary cards
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("선택 날짜", str(target_dt))
with c2:
    if target_val is None or pd.isna(target_val):
        st.metric("해당일 값", "데이터 없음")
    else:
        st.metric(f"해당일 {metric}", f"{target_val:.1f} ℃")
with c3:
    st.metric(baseline, f"{base_val:.1f} ℃")
with c4:
    if anomaly is None:
        st.metric("평년대비(Δ)", "계산 불가")
    else:
        word = "더움" if anomaly > 0 else ("추움" if anomaly < 0 else "같음")
        st.metric("같은 날짜 대비(Δ)", f"{anomaly:+.1f} ℃", help=f"{baseline} 대비 얼마나 {word}인지")


# Extra text summary
st.subheader("해석")
if target_val is None or pd.isna(target_val):
    st.info("선택한 날짜의 값이 데이터에 없거나 결측입니다. 아래 그래프는 '역대 같은 월-일' 분포만 보여줍니다.")
else:
    msg = f"- {target_dt}의 **{metric}**은 **{target_val:.1f}℃**\n"
    msg += f"- 같은 월-일(예: {m}/{d})의 {baseline}은 **{base_val:.1f}℃** → **{anomaly:+.1f}℃** 차이\n"
    if pct is not None:
        msg += f"- 이 값은 과거 같은 날짜들 가운데 **백분위 {pct:.1f}** (값이 낮을수록 '추운 쪽')\n"
        msg += f"- (참고) 추운쪽 순위: **{cold_rank} / {len(sorted_vals)}**, 더운쪽 순위: **{hot_rank} / {len(sorted_vals)}**\n"
    st.markdown(msg)


# -----------------------------
# Plotly charts
# -----------------------------
st.subheader("1) 역대 같은 월-일 분포 (박스플롯 + 해당일 표시)")

box_df = hist[["year", col]].rename(columns={col: "value"}).copy()
box_df["label"] = f"{m:02d}-{d:02d}"

fig_box = px.box(
    box_df,
    x="label",
    y="value",
    points="all",
    hover_data=["year"],
    title=f"{m:02d}-{d:02d} {metric} 분포(역대)",
)

if target_val is not None and pd.notna(target_val):
    fig_box.add_trace(
        go.Scatter(
            x=[f"{m:02d}-{d:02d}"],
            y=[target_val],
            mode="markers",
            name=str(target_dt),
            marker=dict(size=14, symbol="diamond"),
            hovertemplate=f"{target_dt}<br>{metric}: {target_val:.1f}℃<extra></extra>",
        )
    )

st.plotly_chart(fig_box, use_container_width=True)

st.subheader("2) 연도별 같은 월-일 값 추이 (해당일 강조)")

line_df = hist[["year", col]].rename(columns={col: "value"}).sort_values("year")
fig_line = px.line(
    line_df,
    x="year",
    y="value",
    markers=True,
    title=f"연도별 {m:02d}-{d:02d} {metric} 추이",
)

if target_val is not None and pd.notna(target_val):
    fig_line.add_trace(
        go.Scatter(
            x=[target_dt.year],
            y=[target_val],
            mode="markers",
            name="선택 연도",
            marker=dict(size=14, symbol="diamond"),
            hovertemplate=f"{target_dt.year}년<br>{metric}: {target_val:.1f}℃<extra></extra>",
        )
    )

# baseline line
fig_line.add_hline(y=base_val, line_dash="dash", annotation_text=baseline, annotation_position="top left")
st.plotly_chart(fig_line, use_container_width=True)

st.subheader("3) 해당일 vs 기준값(평년) 비교 (막대)")
if target_val is None or pd.isna(target_val):
    st.info("해당일 값이 없어 막대 비교는 생략합니다.")
else:
    comp_df = pd.DataFrame(
        {"구분": ["해당일", baseline], "value": [target_val, base_val]}
    )
    fig_bar = px.bar(comp_df, x="구분", y="value", title=f"{metric} 비교")
    st.plotly_chart(fig_bar, use_container_width=True)

st.caption("※ '같은 날짜' 비교는 선택한 날짜의 월-일(예: 1/21)과 일치하는 과거 모든 연도의 기록을 기준으로 계산합니다.")
