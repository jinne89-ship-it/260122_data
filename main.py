import io
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="기온 비교(같은 월-일 기준) 대시보드",
    layout="wide",
)

# =========================
# 0) 유틸: 데이터 로드/정규화
# =========================
REQUIRED_COLS = ["날짜", "지점", "평균기온(℃)", "최저기온(℃)", "최고기온(℃)"]

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # 공백/보이지 않는 문자 정리
    df = df.copy()
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]

    # 흔한 변형 대응(필요 시 확장 가능)
    col_map = {}
    for c in df.columns:
        if c in REQUIRED_COLS:
            continue
        # 예: 평균기온, 평균기온(℃) 등
        if "평균" in c and "기온" in c:
            col_map[c] = "평균기온(℃)"
        elif "최저" in c and "기온" in c:
            col_map[c] = "최저기온(℃)"
        elif "최고" in c and "기온" in c:
            col_map[c] = "최고기온(℃)"
        elif c in ["date", "Date", "날짜(일)"]:
            col_map[c] = "날짜"
        elif c in ["지점번호", "stn", "station", "지점코드"]:
            col_map[c] = "지점"

    if col_map:
        df = df.rename(columns=col_map)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing} / 현재 컬럼: {list(df.columns)}")

    return df[REQUIRED_COLS]


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # '날짜'가 YYYY-MM-DD 또는 YYYYMMDD 등 혼재 가능성 대비
    s = df["날짜"].astype(str).str.strip()
    # YYYYMMDD 형태면 하이픈 추가
    s2 = s.where(~s.str.fullmatch(r"\d{8}"), s.str.slice(0, 4) + "-" + s.str.slice(4, 6) + "-" + s.str.slice(6, 8))
    df["날짜"] = pd.to_datetime(s2, errors="coerce")
    return df


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ["지점", "평균기온(℃)", "최저기온(℃)", "최고기온(℃)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_base_data(path: str) -> pd.DataFrame:
    # 기본 탑재 데이터 로드
    df = pd.read_csv(path)
    df = normalize_columns(df)
    df = parse_dates(df)
    df = coerce_numeric(df)
    return df


def load_uploaded_csv(uploaded_file) -> pd.DataFrame:
    # 업로드 파일 로드(인코딩 이슈 대비)
    raw = uploaded_file.read()
    for enc in ["utf-8", "utf-8-sig", "cp949", "euc-kr"]:
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc)
            df = normalize_columns(df)
            df = parse_dates(df)
            df = coerce_numeric(df)
            return df
        except Exception:
            continue
    raise ValueError("업로드 CSV를 읽지 못했습니다(인코딩/형식 확인 필요).")


def combine_datasets(base_df: pd.DataFrame, uploads: list[pd.DataFrame]) -> pd.DataFrame:
    df = pd.concat([base_df] + uploads, ignore_index=True)
    # 중복 제거(날짜+지점 기준). 중복 시 마지막 값 유지
    df = df.sort_values(["지점", "날짜"]).drop_duplicates(subset=["지점", "날짜"], keep="last")
    return df


# =========================
# 1) UI: 데이터 선택/업로드
# =========================
st.title("🌡️ 같은 날짜(월-일) 기준 기온이 얼마나 춥거나 더웠는지 비교")

with st.sidebar:
    st.header("데이터")
    st.caption("기본 탑재 데이터 + 동일 형식 CSV 업로드를 합쳐서 분석합니다.")

    # ✅ Streamlit Cloud에서는 repo 내 파일을 읽게 두는 게 안정적입니다.
    BASE_PATH = "data/ta_20260122174530-1.csv"
    st.text(f"기본 데이터: {BASE_PATH}")

    uploaded_files = st.file_uploader(
        "추가 CSV 업로드(동일 형식)",
        type=["csv"],
        accept_multiple_files=True
    )

    st.divider()
    st.header("비교 설정")
    metric = st.selectbox(
        "비교할 지표",
        ["평균기온(℃)", "최저기온(℃)", "최고기온(℃)"],
        index=0
    )

# =========================
# 2) 데이터 로드 & 전처리
# =========================
try:
    base_df = load_base_data(BASE_PATH)
except Exception as e:
    st.error("기본 데이터 로드 실패: " + str(e))
    st.stop()

uploads = []
if uploaded_files:
    for f in uploaded_files:
        try:
            uploads.append(load_uploaded_csv(f))
        except Exception as e:
            st.warning(f"업로드 파일 '{f.name}' 처리 실패: {e}")

df = combine_datasets(base_df, uploads)

# 필수 품질 필터: 날짜가 파싱 안 된 행 제거
df = df.dropna(subset=["날짜"])

# 지점 선택
stations = sorted(df["지점"].dropna().unique().astype(int).tolist())
if not stations:
    st.error("유효한 '지점' 값이 없습니다.")
    st.stop()

with st.sidebar:
    station = st.selectbox("지점", stations, index=0)

df_s = df[df["지점"] == station].copy()
df_s = df_s.sort_values("날짜")

# 날짜 선택: 기본은 "가장 최근 날짜"
most_recent_date = df_s["날짜"].max()
with st.sidebar:
    target_date = st.date_input("기준 날짜(미지정 시 최신)", value=most_recent_date.date())

target_date = pd.to_datetime(target_date)

# =========================
# 3) 같은 월-일 비교(클리마톨로지)
# =========================
df_s["mmdd"] = df_s["날짜"].dt.strftime("%m-%d")
target_mmdd = target_date.strftime("%m-%d")

same_day = df_s[df_s["mmdd"] == target_mmdd].copy()

# 기준 날짜의 값(해당 날짜가 데이터에 없으면 가장 가까운 이전 날짜로 대체할지 결정)
row = df_s[df_s["날짜"] == target_date]
if row.empty:
    # 가장 가까운 이전 날짜로 fallback
    prev = df_s[df_s["날짜"] < target_date]
    if prev.empty:
        st.error("선택한 날짜 이전에 데이터가 없습니다.")
        st.stop()
    fallback_date = prev["날짜"].max()
    st.info(f"선택한 날짜({target_date.date()}) 데이터가 없어, 가장 가까운 이전 날짜({fallback_date.date()})로 비교합니다.")
    target_date = fallback_date
    target_mmdd = target_date.strftime("%m-%d")
    same_day = df_s[df_s["mmdd"] == target_mmdd].copy()
    row = df_s[df_s["날짜"] == target_date]

target_value = float(row.iloc[0][metric]) if pd.notna(row.iloc[0][metric]) else np.nan

# 같은 월-일 분포에서 '선택 연도'를 제외한 기준도 함께 제공(자기포함 편향 방지)
same_day_excl = same_day[same_day["날짜"].dt.year != target_date.year].copy()

def summarize_distribution(x: pd.Series):
    x = x.dropna()
    if x.empty:
        return None
    return {
        "n": int(x.shape[0]),
        "mean": float(x.mean()),
        "std": float(x.std(ddof=1)) if x.shape[0] > 1 else float("nan"),
        "min": float(x.min()),
        "p25": float(x.quantile(0.25)),
        "median": float(x.median()),
        "p75": float(x.quantile(0.75)),
        "max": float(x.max()),
    }

dist_all = summarize_distribution(same_day[metric])
dist_excl = summarize_distribution(same_day_excl[metric])

def percentile_of_value(series: pd.Series, value: float):
    s = series.dropna().values
    if s.size == 0 or np.isnan(value):
        return np.nan
    return float((s < value).mean() * 100.0)

pct_all = percentile_of_value(same_day[metric], target_value)
pct_excl = percentile_of_value(same_day_excl[metric], target_value)

def z_score(mean, std, value):
    if std is None or np.isnan(std) or std == 0 or np.isnan(value):
        return np.nan
    return float((value - mean) / std)

z_all = z_score(dist_all["mean"], dist_all["std"], target_value) if dist_all else np.nan
z_excl = z_score(dist_excl["mean"], dist_excl["std"], target_value) if dist_excl else np.nan

# “얼마나 춥거나/더웠는지” = (선택값 - 같은 월-일 평균)
delta_all = (target_value - dist_all["mean"]) if dist_all and not np.isnan(target_value) else np.nan
delta_excl = (target_value - dist_excl["mean"]) if dist_excl and not np.isnan(target_value) else np.nan

# =========================
# 4) 화면 구성
# =========================
st.subheader(f"지점 {station} · 기준 날짜 {target_date.date()} · 비교 지표: {metric}")
st.caption(f"비교 기준: 같은 월-일({target_mmdd})의 역사적 분포")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric("기준 날짜 값", f"{target_value:.2f}℃" if not np.isnan(target_value) else "결측")

with c2:
    if dist_excl:
        st.metric(
            "같은 월-일 평균(자기연도 제외)",
            f"{dist_excl['mean']:.2f}℃",
            f"{delta_excl:+.2f}℃" if not np.isnan(delta_excl) else None
        )
    else:
        st.metric("같은 월-일 평균(자기연도 제외)", "N/A")

with c3:
    st.metric(
        "퍼센타일(자기연도 제외)",
        f"{pct_excl:.1f}%" if not np.isnan(pct_excl) else "N/A",
    )

with c4:
    st.metric(
        "Z-점수(자기연도 제외)",
        f"{z_excl:+.2f}" if not np.isnan(z_excl) else "N/A",
    )

st.divider()

# =========================
# 5) Plotly 그래프
# =========================

# (A) 같은 월-일 값의 연도별 추이
same_day_plot = same_day.copy()
same_day_plot["연도"] = same_day_plot["날짜"].dt.year

fig_year = px.line(
    same_day_plot.sort_values("연도"),
    x="연도",
    y=metric,
    markers=True,
    title=f"같은 월-일({target_mmdd})의 연도별 {metric} 추이"
)
fig_year.add_vline(x=target_date.year, line_dash="dash")
st.plotly_chart(fig_year, use_container_width=True)

# (B) 분포 비교(박스플롯) + 기준값 표시
fig_box = px.box(
    same_day_plot,
    y=metric,
    points="all",
    title=f"같은 월-일({target_mmdd}) {metric} 분포(점=각 연도)"
)
if not np.isnan(target_value):
    fig_box.add_hline(y=target_value, line_dash="dash")
st.plotly_chart(fig_box, use_container_width=True)

# (C) 최근 3년 타임라인(컨텍스트)
last_year = int(df_s["날짜"].dt.year.max())
start = pd.Timestamp(year=last_year - 2, month=1, day=1)
recent = df_s[df_s["날짜"] >= start].copy()

fig_recent = px.line(
    recent,
    x="날짜",
    y=metric,
    title=f"최근 3년 {metric} 타임라인(지점 {station})"
)
fig_recent.add_vline(x=target_date, line_dash="dash")
st.plotly_chart(fig_recent, use_container_width=True)

# =========================
# 6) 테이블(요약 + 연도별 값)
# =========================
left, right = st.columns([1, 1])

with left:
    st.markdown("#### 분포 요약(같은 월-일)")
    summary_rows = []
    if dist_all:
        summary_rows.append(["포함 기준", "전체 연도 포함"])
        summary_rows.append(["표본수(n)", dist_all["n"]])
        summary_rows.append(["평균", f"{dist_all['mean']:.2f}"])
        summary_rows.append(["표준편차", f"{dist_all['std']:.2f}" if not np.isnan(dist_all["std"]) else "N/A"])
        summary_rows.append(["최소~최대", f"{dist_all['min']:.2f} ~ {dist_all['max']:.2f}"])
        summary_rows.append(["중앙값(IQR)", f"{dist_all['median']:.2f} ({dist_all['p25']:.2f}~{dist_all['p75']:.2f})"])
        summary_rows.append(["기준값-평균", f"{delta_all:+.2f}" if not np.isnan(delta_all) else "N/A"])
        summary_rows.append(["퍼센타일", f"{pct_all:.1f}%" if not np.isnan(pct_all) else "N/A"])
        summary_rows.append(["Z-점수", f"{z_all:+.2f}" if not np.isnan(z_all) else "N/A"])

    if dist_excl:
        summary_rows.append(["포함 기준", "자기 연도 제외"])
        summary_rows.append(["표본수(n)", dist_excl["n"]])
        summary_rows.append(["평균", f"{dist_excl['mean']:.2f}"])
        summary_rows.append(["표준편차", f"{dist_excl['std']:.2f}" if not np.isnan(dist_excl["std"]) else "N/A"])
        summary_rows.append(["최소~최대", f"{dist_excl['min']:.2f} ~ {dist_excl['max']:.2f}"])
        summary_rows.append(["중앙값(IQR)", f"{dist_excl['median']:.2f} ({dist_excl['p25']:.2f}~{dist_excl['p75']:.2f})"])
        summary_rows.append(["기준값-평균", f"{delta_excl:+.2f}" if not np.isnan(delta_excl) else "N/A"])
        summary_rows.append(["퍼센타일", f"{pct_excl:.1f}%" if not np.isnan(pct_excl) else "N/A"])
        summary_rows.append(["Z-점수", f"{z_excl:+.2f}" if not np.isnan(z_excl) else "N/A"])

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows, columns=["항목", "값"])
        st.dataframe(summary_df, use_container_width=True, hide_index=True)
    else:
        st.warning("같은 월-일 분포를 구성할 데이터가 부족합니다(결측 또는 데이터 부족).")

with right:
    st.markdown("#### 같은 월-일 연도별 원자료")
    show = same_day_plot[["날짜", "연도", metric]].sort_values("연도")
    st.dataframe(show, use_container_width=True, hide_index=True)

st.divider()

# =========================
# 7) 간단 품질 체크(업로드 합친 뒤)
# =========================
st.markdown("### 데이터 품질 체크(결측치)")
miss = df_s[REQUIRED_COLS].isna().sum().to_frame("결측치 수")
miss["비율(%)"] = (miss["결측치 수"] / len(df_s) * 100).round(2)
st.dataframe(miss, use_container_width=True)

st.caption("※ 필요하시면 ‘연도별 결측치 분포’ 그래프/리포트도 추가해드릴 수 있습니다.")
