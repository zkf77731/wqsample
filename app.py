import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os

st.set_page_config(page_title="水质变频采样看板", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

st.title("水质监测断面流量与气象")

STATION_FILE = r'C:\web\station.xlsx'
DATA_DIR = r'C:\web\data'

@st.cache_data
def load_stations():
    if not os.path.exists(STATION_FILE):
        return {}
    try:
        df_stations = pd.read_excel(STATION_FILE)
        stations_dict = {}
        for _, row in df_stations.iterrows():
            name = str(row['station']).strip()
            stations_dict[name] = {"lat": float(row['lat']), "lon": float(row['lon'])}
        return stations_dict
    except Exception as e:
        st.error(f"读取站点 Excel 失败: {e}")
        return {}

@st.cache_data(ttl=600)
def load_and_merge_data(station_name):
    precip_file = os.path.join(DATA_DIR, f"{station_name}_precip.csv")
    stream_file = os.path.join(DATA_DIR, f"{station_name}_streamflow.csv")
    sample_file = os.path.join(DATA_DIR, f"{station_name}_sample.csv")

    if not os.path.exists(precip_file) or not os.path.exists(stream_file):
        return None

    df_p = pd.read_csv(precip_file)
    df_s = pd.read_csv(stream_file)

    df_p['time'] = pd.to_datetime(df_p['time'], utc=True).dt.tz_convert('Asia/Shanghai')
    df_s['time'] = pd.to_datetime(df_s['time'], utc=True).dt.tz_convert('Asia/Shanghai')

    df_merged = pd.merge(df_s, df_p, on='time', how='outer')

    if os.path.exists(sample_file):
        df_samp = pd.read_csv(sample_file)
        df_samp['time'] = pd.to_datetime(df_samp['time'], utc=True).dt.tz_convert('Asia/Shanghai')
        df_merged = pd.merge(df_merged, df_samp[['time', 'state']], on='time', how='outer')
    else:
        df_merged['state'] = 'off'

    df_merged = df_merged.sort_values('time').reset_index(drop=True)

    df_merged['streamflow_m3s'] = df_merged['streamflow_m3s'].interpolate(method='linear')

    return df_merged

stations = load_stations()

# ==========================================
# 侧边栏及地图控制逻辑
# ==========================================
st.sidebar.header("控制面板")

if not stations:
    st.error(f"未找到站点数据，请检查 {STATION_FILE} 是否存在。")
    st.stop()

selected_station = st.sidebar.selectbox("请选择一个监测站点：", list(stations.keys()))

current_lat = stations[selected_station]["lat"]
current_lon = stations[selected_station]["lon"]

# ==========================================
# 页面布局：地图与可视化
# ==========================================
col1, col2 = st.columns([1, 2.5])

with col1:
    st.subheader("站点地理位置")
    m = folium.Map(location=[current_lat, current_lon], zoom_start=10, tiles="CartoDB positron")

    for name, coords in stations.items():
        color = "red" if name == selected_station else "cadetblue"
        folium.Marker(
            location=[coords["lat"], coords["lon"]],
            tooltip=name,
            icon=folium.Icon(color=color, icon="info-sign")
        ).add_to(m)

    st_folium(m, width=400, height=600)

with col2:
    st.subheader(f"{selected_station} 预测数据")

    df = load_and_merge_data(selected_station)

    if df is not None and not df.empty:
        # === 创建 3 行 1 列的子图 (共享 X 轴) ===
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("径流量预测与采样点", "降雨量预测 (mm)", "气温预测 (℃)"),
            row_heights=[0.4, 0.3, 0.3]
        )

        # 1. 径流量 (折线图) - 第一行
        df_stream = df.dropna(subset=['streamflow_m3s'])
        fig.add_trace(
            go.Scatter(x=df_stream['time'], y=df_stream['streamflow_m3s'], name="流量", mode='lines',
                       line=dict(color='#1F77B4', width=3, shape='spline')),
            row=1, col=1
        )

        # 1.5 叠加采样点 (散点图) - 第一行
        if 'state' in df.columns:
            # 筛选出需要采样的点，且流量不为空
            df_sample_on = df[df['state'] == 'on'].dropna(subset=['streamflow_m3s'])
            if not df_sample_on.empty:
                fig.add_trace(
                    go.Scatter(
                        x=df_sample_on['time'],
                        y=df_sample_on['streamflow_m3s'],
                        name="采样触发点",
                        mode='markers',
                        marker=dict(color='red', symbol='star', size=12, line=dict(width=1, color='darkred')),
                        hoverinfo='x+y+name' # 鼠标悬停显示详细信息
                    ),
                    row=1, col=1
                )

        # 2. 降雨量 (柱状图) - 第二行
        df_precip = df.dropna(subset=['precip_mm'])
        fig.add_trace(
            go.Bar(x=df_precip['time'], y=df_precip['precip_mm'], name="降雨量", marker_color='#87CEEB'),
            row=2, col=1
        )

        # 3. 气温 (折线图) - 第三行
        df_temp = df.dropna(subset=['temp_C'])
        fig.add_trace(
            go.Scatter(x=df_temp['time'], y=df_temp['temp_C'], name="气温", mode='lines',
                       line=dict(color='#FF7F0E', width=2, shape='spline')),
            row=3, col=1
        )

        # 整体布局优化
        fig.update_layout(
            hovermode="x unified",
            showlegend=False,
            height=650,
            margin=dict(l=0, r=0, t=40, b=0)
        )

        st.plotly_chart(fig, use_container_width=True)

        with st.expander("查看合并后的底层数据表 (已转为北京时间)"):
            st.dataframe(df.style.highlight_max(axis=0, color='#FFF2CC'))

    else:
        st.warning(f"未能找到 {selected_station} 的本地数据，请先运行后端抓取脚本。")
