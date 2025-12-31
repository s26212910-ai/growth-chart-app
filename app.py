import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from notion_client import Client
from datetime import datetime, date

# --- 設定頁面 ---
st.set_page_config(page_title="生長曲線管理系統", layout="wide")

# --- 讀取 Secrets (Notion金鑰與密碼) ---
try:
    NOTION_TOKEN = st.secrets["notion"]["TOKEN"]
    DATABASE_ID = st.secrets["notion"]["DATABASE_ID"]
    APP_PASSWORD = st.secrets["general"]["PASSWORD"]
except:
    st.error("設定檔 (Secrets) 遺失，請在 Streamlit Cloud 設定 Notion Token 與 Password。")
    st.stop()

# --- 登入系統 ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def check_password():
    if st.session_state.password_input == APP_PASSWORD:
        st.session_state.authenticated = True
        del st.session_state.password_input
    else:
        st.error("密碼錯誤")

if not st.session_state.authenticated:
    st.title("🔐 系統登入")
    st.text_input("請輸入密碼", type="password", key="password_input", on_change=check_password)
    st.stop()  # 停止執行後續程式碼

# --- 登入成功後的主程式 ---

# 初始化 Notion Client
notion = Client(auth=NOTION_TOKEN)

# --- 讀取 CSV 參考資料 (請確保 GitHub 有這四個檔) ---
@st.cache_data
def load_ref_data():
    try:
        # 注意：請確認 GitHub 上的檔名是小寫，或者在此修改
        ht_m = pd.read_csv("ht_m.csv") 
        ht_f = pd.read_csv("ht_f.csv")
        wt_m = pd.read_csv("wt_m.csv")
        wt_f = pd.read_csv("wt_f.csv")
        
        # 清理欄位空白
        for df in [ht_m, ht_f, wt_m, wt_f]:
            df.columns = df.columns.str.strip()
        return ht_m, ht_f, wt_m, wt_f
    except Exception as e:
        st.error(f"讀取 CSV 失敗，請確認檔案已上傳至 GitHub。錯誤: {e}")
        return None, None, None, None

ht_m_df, ht_f_df, wt_m_df, wt_f_df = load_ref_data()

# --- Notion 資料處理函數 ---
def fetch_notion_data():
    """從 Notion 資料庫撈取所有資料"""
    try:
        results = []
        has_more = True
        start_cursor = None

        while has_more:
            response = notion.databases.query(
                database_id=DATABASE_ID,
                start_cursor=start_cursor
            )
            results.extend(response['results'])
            has_more = response['has_more']
            start_cursor = response['next_cursor']
        
        # 解析 Notion JSON 為 DataFrame
        parsed_rows = []
        for page in results:
            props = page['properties']
            try:
                # 取得各欄位值，需依照 Notion API 結構解析
                name_list = props['Name']['title']
                name = name_list[0]['plain_text'] if name_list else "Unknown"
                
                gender = props['Gender']['select']['name'] if props['Gender']['select'] else "male"
                dob = props['DOB']['date']['start'] if props['DOB']['date'] else None
                rec_date = props['RecordDate']['date']['start'] if props['RecordDate']['date'] else None
                
                height = props['Height']['number']
                weight = props['Weight']['number']
                source = props['Source']['select']['name'] if props['Source']['select'] else "doctor"
                
                f_ht = props['FatherHeight']['number']
                m_ht = props['MotherHeight']['number']
                
                parsed_rows.append({
                    "id": page['id'],
                    "Name": name,
                    "Gender": gender,
                    "DOB": dob,
                    "RecordDate": rec_date,
                    "Height": height,
                    "Weight": weight,
                    "Source": source,
                    "FatherHeight": f_ht,
                    "MotherHeight": m_ht
                })
            except Exception:
                continue # 跳過格式錯誤的行

        if not parsed_rows:
            return pd.DataFrame()
        
        return pd.DataFrame(parsed_rows)

    except Exception as e:
        st.error(f"連線 Notion 失敗: {e}")
        return pd.DataFrame()

def save_to_notion(data_dict):
    """將新資料寫入 Notion"""
    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": data_dict['Name']}}]},
                "Gender": {"select": {"name": data_dict['Gender']}},
                "DOB": {"date": {"start": data_dict['DOB']}},
                "RecordDate": {"date": {"start": data_dict['RecordDate']}},
                "Height": {"number": data_dict['Height']},
                "Weight": {"number": data_dict['Weight']},
                "Source": {"select": {"name": data_dict['Source']}},
                "FatherHeight": {"number": data_dict['FatherHeight']},
                "MotherHeight": {"number": data_dict['MotherHeight']},
            }
        )
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 計算邏輯 ---
def calculate_age_months(dob_str, rec_date_str):
    if not dob_str or not rec_date_str: return 0, "N/A"
    dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    rec = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
    
    diff_days = (rec - dob).days
    total_months = diff_days / 30.4375
    
    years = rec.year - dob.year
    months = rec.month - dob.month
    if rec.day < dob.day: months -= 1
    if months < 0:
        years -= 1
        months += 12
        
    return total_months, f"{years}歲 {months}個月"

# --- 繪圖邏輯 (v6 彩虹版) ---
def plot_chart(df_ref, user_data, title, y_label, target_ht=None):
    fig = go.Figure()
    
    # 7色設定
    colors = ['#A93226', '#CA6F1E', '#B7950B', '#1E8449', '#117864', '#2471A3', '#5B2C6F']
    percentiles = [col for col in df_ref.columns if 'P' in col]
    # 確保 P3 -> P97 排序
    percentiles.sort(key=lambda x: int(x[1:]))
    
    # 畫參考線
    for i, p in enumerate(percentiles):
        line_width = 3 if p == 'P50' else 1.5
        color = colors[i % len(colors)]
        
        fig.add_trace(go.Scatter(
            x=df_ref['months'], y=df_ref[p],
            mode='lines', name=p,
            line=dict(color=color, width=line_width),
            hoverinfo='name+x+y'
        ))

    # 畫遺傳身高 (僅限身高圖)
    if target_ht:
        fig.add_trace(go.Scatter(
            x=[0, 240], y=[target_ht, target_ht],
            mode='lines', name='遺傳身高',
            line=dict(color='#FF9800', width=2, dash='dashdot')
        ))

    # 畫病患數據
    if not user_data.empty:
        # 分類來源
        doc_data = user_data[user_data['Source'] == 'doctor']
        parent_data = user_data[user_data['Source'] == 'parent']
        
        # 趨勢線 (連線)
        user_data_sorted = user_data.sort_values('TotalMonths')
        fig.add_trace(go.Scatter(
            x=user_data_sorted['TotalMonths'], y=user_data_sorted['Value'],
            mode='lines', name='趨勢',
            line=dict(color='#3DB5AC', width=2), showlegend=False
        ))
        
        # 診間點 (圓圈)
        if not doc_data.empty:
            fig.add_trace(go.Scatter(
                x=doc_data['TotalMonths'], y=doc_data['Value'],
                mode='markers', name='診間 (●)',
                marker=dict(symbol='circle', color='#3DB5AC', size=10, line=dict(color='white', width=1)),
                text=doc_data['AgeDisplay'], hovertemplate='%{y}<br>%{text}'
            ))
            
        # 居家點 (叉叉)
        if not parent_data.empty:
            fig.add_trace(go.Scatter(
                x=parent_data['TotalMonths'], y=parent_data['Value'],
                mode='markers', name='居家 (✖)',
                marker=dict(symbol='x', color='#e74c3c', size=10),
                text=parent_data['AgeDisplay'], hovertemplate='%{y}<br>%{text}'
            ))

    # X軸設定 (0-20歲, 月齡小刻度)
    tick_vals = [i*12 for i in range(21)]
    tick_text = [f"{i}歲" for i in range(21)]
    
    max_x = 240
    if not user_data.empty:
        max_x = max(240, user_data['TotalMonths'].max() + 10)

    fig.update_layout(
        title=title,
        yaxis_title=y_label,
        xaxis=dict(
            title="年齡",
            tickmode='array', tickvals=tick_vals, ticktext=tick_text,
            range=[0, max_x],
            minor=dict(dtick=1, gridcolor='rgba(200,200,200,0.2)', ticklen=3, showgrid=True)
        ),
        height=500,
        margin=dict(l=50, r=20, t=50, b=50),
        legend=dict(orientation="h", y=-0.2)
    )
    return fig

# --- App 介面佈局 ---
st.title("📊 兒童生長曲線系統 (Notion同步版)")

# 1. 讀取資料
with st.spinner("正在從 Notion 同步資料..."):
    df_all = fetch_notion_data()

# 2. 側邊欄：新增資料
with st.sidebar:
    st.header("📝 新增紀錄")
    
    # 姓名選擇/輸入 (若有舊資料，做成選單)
    if not df_all.empty:
        existing_names = df_all['Name'].unique().tolist()
        name_input = st.selectbox("選擇姓名 (或輸入新姓名)", ["-- 新增 --"] + existing_names)
    else:
        name_input = "-- 新增 --"
        
    if name_input == "-- 新增 --":
        s_name = st.text_input("姓名")
        s_gender = st.selectbox("性別", ["male", "female"])
        s_dob = st.date_input("生日", value=date(2018, 1, 1))
        s_f_ht = st.number_input("爸爸身高", value=175.0)
        s_m_ht = st.number_input("媽媽身高", value=160.0)
    else:
        # 自動帶入舊資料的基本屬性
        last_rec = df_all[df_all['Name'] == name_input].iloc[0]
        s_name = name_input
        s_gender = last_rec['Gender']
        try:
            s_dob = datetime.strptime(last_rec['DOB'], "%Y-%m-%d").date()
        except:
            s_dob = date.today()
        s_f_ht = float(last_rec['FatherHeight']) if pd.notnull(last_rec['FatherHeight']) else 0.0
        s_m_ht = float(last_rec['MotherHeight']) if pd.notnull(last_rec['MotherHeight']) else 0.0
        
        st.info(f"已選取: {s_name} ({'男' if s_gender=='male' else '女'})")

    st.markdown("---")
    s_rec_date = st.date_input("測量日期", value=date.today())
    s_source = st.radio("來源", ["doctor", "parent"], format_func=lambda x: "🏥 診間" if x=="doctor" else "🏠 居家")
    s_ht = st.number_input("身高 (cm)", value=0.0)
    s_wt = st.number_input("體重 (kg)", value=0.0)

    if st.button("上傳至 Notion"):
        if s_name and s_ht > 0 and s_wt > 0:
            new_data = {
                "Name": s_name, "Gender": s_gender, 
                "DOB": s_dob.strftime("%Y-%m-%d"), 
                "RecordDate": s_rec_date.strftime("%Y-%m-%d"),
                "Height": s_ht, "Weight": s_wt, "Source": s_source,
                "FatherHeight": s_f_ht, "MotherHeight": s_m_ht
            }
            if save_to_notion(new_data):
                st.success("成功！請重新整理頁面以查看更新。")
                st.cache_data.clear() # 清除快取以重讀
        else:
            st.error("請填寫完整資料")

# 3. 主畫面：顯示圖表
if df_all.empty:
    st.info("目前 Notion 資料庫中沒有資料，請從左側新增。")
else:
    # 選擇要查看的小孩
    view_name = st.selectbox("請選擇要查看的小孩", df_all['Name'].unique())
    
    if view_name:
        # 篩選資料
        person_df = df_all[df_all['Name'] == view_name].copy()
        
        # 取得基本資料 (取第一筆即可)
        p_info = person_df.iloc[0]
        gender = p_info['Gender']
        f_ht = p_info['FatherHeight']
        m_ht = p_info['MotherHeight']
        
        # 計算遺傳身高
        target_ht = None
        target_str = ""
        if f_ht > 0 and m_ht > 0:
            if gender == 'male':
                target_ht = (f_ht + m_ht + 13) / 2
            else:
                target_ht = (f_ht + m_ht - 13) / 2
            target_str = f" | 遺傳身高: {target_ht:.1f} cm"

        st.subheader(f"{view_name} ({'男' if gender=='male' else '女'}) {target_str}")
        
        # 計算所有紀錄的月齡
        person_df['TotalMonths'], person_df['AgeDisplay'] = zip(*person_df.apply(
            lambda x: calculate_age_months(x['DOB'], x['RecordDate']), axis=1
        ))
        
        # 準備繪圖資料
        ht_data = person_df[['TotalMonths', 'Height', 'Source', 'AgeDisplay']].rename(columns={'Height': 'Value'})
        wt_data = person_df[['TotalMonths', 'Weight', 'Source', 'AgeDisplay']].rename(columns={'Weight': 'Value'})
        
        # 選擇參考曲線
        if gender == 'male':
            ref_ht, ref_wt = ht_m_df, wt_m_df
        else:
            ref_ht, ref_wt = ht_f_df, wt_f_df
            
        if ref_ht is not None:
            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(plot_chart(ref_ht, ht_data, "身高曲線", "身高 (cm)", target_ht), use_container_width=True)
            with col2:
                st.plotly_chart(plot_chart(ref_wt, wt_data, "體重曲線", "體重 (kg)"), use_container_width=True)

        # 顯示歷史表格
        st.markdown("### 歷史紀錄")
        display_df = person_df[['RecordDate', 'AgeDisplay', 'Source', 'Height', 'Weight']].sort_values('RecordDate', ascending=False)
        display_df['Source'] = display_df['Source'].map({'doctor': '🏥 診間', 'parent': '🏠 居家'})
        st.dataframe(display_df, use_container_width=True)

# Footer
st.markdown("---")
st.markdown("""
<small>
資料來源：陳偉德，張美惠：Pediatr Neonatol 2010;51(2):69-79 | 黃奕清：九十二年度教育部台閩地區中小學生身體發展研究 | WHO child growth standards 2006 <br>
Made by 台大小兒內分泌科總醫師 葉晉銘 (2025/12/31)
</small>
""", unsafe_allow_html=True)
