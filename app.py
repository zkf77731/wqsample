import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 网页基本设置
# ==========================================
st.set_page_config(page_title="水文气象数据看板", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

st.title("水质监测断面流量与气象")


# ==========================================
# 2. 连接 Google Sheets 并读取数据
# ==========================================
# 这里不再读取本地的 google_key.json，而是读取 Streamlit 云端配置好的机密(Secrets)
@st.cache_resource
def init_connection():
    # 解析 Streamlit 云端配置的 JSON 字符串
    key_dict = json.loads(st.secrets["google_json_key"])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(key_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client


gc = init_connection()

SHEET_NAME = 'streamlit_wqsample'

@st.cache_data(ttl=600)  # 缓存 10 分钟，避免频繁请求 API
def load_cloud_data():
    sh = gc.open(SHEET_NAME)

    # 读取降雨和径流表
    ws_precip = sh.worksheet("Precipitation")
    ws_stream = sh.worksheet("Streamflow")

    # 转换为 DataFrame
    df_p = pd.DataFrame(ws_precip.get_all_records())
    df_s = pd.DataFrame(ws_stream.get_all_records())

    # 转换时间格式并指定时区为 UTC（因为之前你抓取下来存进云端的是 UTC）
    if not df_p.empty:
        df_p['time'] = pd.to_datetime(df_p['time']).dt.tz_localize('UTC').dt.tz_convert('Asia/Shanghai')
    if not df_s.empty:
        df_s['time'] = pd.to_datetime(df_s['time']).dt.tz_localize('UTC').dt.tz_convert('Asia/Shanghai')

    return df_p, df_s


df_precip_all, df_streamflow_all = load_cloud_data()

# ==========================================
# 3. 读取站点坐标配置
# ==========================================
STATION_FILE = 'station.xlsx'


@st.cache_data
def load_stations():
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


stations = load_stations()

# ==========================================
# 4. 侧边栏及地图控制逻辑
# ==========================================
st.sidebar.header("控制面板")

if not stations:
    st.error(f"未找到站点数据，请确保 {STATION_FILE} 和 app.py 在同一目录下。")
    st.stop()

selected_station = st.sidebar.selectbox("请选择一个监测站点：", list(stations.keys()))

current_lat = stations[selected_station]["lat"]
current_lon = stations[selected_station]["lon"]

# ==========================================
# 5. 页面布局：地图与可视化
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

    df_p_filtered = df_precip_all[
        df_precip_all['station'] == selected_station] if not df_precip_all.empty else pd.DataFrame()
    df_s_filtered = df_streamflow_all[
        df_streamflow_all['station'] == selected_station] if not df_streamflow_all.empty else pd.DataFrame()

    if not df_p_filtered.empty and not df_s_filtered.empty:
        df_merged = pd.merge(df_s_filtered, df_p_filtered, on=['station', 'time'], how='outer').sort_values('time')

        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("径流量预测 (m³/s)", "降雨量预测 (mm)", "气温预测 (℃)"),
            row_heights=[0.4, 0.3, 0.3]
        )

        df_stream = df_merged.dropna(subset=['streamflow_m3s'])
        fig.add_trace(go.Scatter(x=df_stream['time'], y=df_stream['streamflow_m3s'], name="流量", mode='lines',
                                 line=dict(color='#1F77B4', width=3)), row=1, col=1)

        df_precip = df_merged.dropna(subset=['precip_mm'])
        fig.add_trace(go.Bar(x=df_precip['time'], y=df_precip['precip_mm'], name="降雨量", marker_color='#87CEEB'),
                      row=2, col=1)

        df_temp = df_merged.dropna(subset=['temp_C'])
        fig.add_trace(go.Scatter(x=df_temp['time'], y=df_temp['temp_C'], name="气温", mode='lines',
                                 line=dict(color='#FF7F0E', width=2)), row=3, col=1)

        fig.update_layout(hovermode="x unified", showlegend=False, height=650, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning(f"云端数据库中暂无 {selected_station} 的数据。")