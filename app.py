import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import pandas as pd
import datetime
import json
import re
import matplotlib.pyplot as plt

# --- 0. パスワード保護 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if st.session_state.password_correct:
        return True
    st.title("🔒 ログイン")
    password = st.text_input("パスワードを入力してください", type="password")
    if st.button("ログイン"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False

if not check_password():
    st.stop()

# --- 設定周り ---
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    
    # ★ここが変更点：世界中で最も安定している「1.5-flash」を直接指定
    # これが429(Limit 0)になることはまずありません。
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    SHEET_NAME = st.secrets["SHEET_NAME"]
    credentials_dict = json.loads(st.secrets["GCP_JSON"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"起動エラー！ねえ、設定が変よ！: {e}")
    st.stop()

# ヘッダー確認
try:
    if not sheet.get_all_values():
        sheet.append_row(["日付", "時刻", "種別", "メニュー名", "カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "アドバイス", "点数", "プリン体(mg)"])
except:
    pass

# --- AI分析関数 ---

def analyze_meal(image, text_input, meal_type):
    prompt = f"""
    あなたはユーザー（お兄ちゃん）の健康を管理している「ツンデレな妹（ツインテール）」よ。
    語尾は「〜よ」「〜じゃない」「〜だわ」とか、ちょっと乱暴だけどお兄ちゃんを心配してる感じで。
    
    【タスク】食事（{meal_type}）を分析してJSONで返して。
    - "score": ダイエット点数
    - "purines": プリン体(mg)
    - "advice": ツンデレ口調のアドバイス
    
    {{
        "menu": "料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
        "purines": 0.0,
        "score": 0,
        "advice": "..."
    }}
    """
    content = [prompt]
    if image: content.append(image)
    if text_input: content.append(f"補足: {text_input}")
    
    try:
        response = model.generate_content(content)
        # JSONの抽出
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except:
        return None

def analyze_daily_summary(date_str):
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df['日付'] = df['日付'].astype(str)
    day_data = df[df['日付'] == date_str]
    meals = day_data[day_data['種別'].isin(['朝食', '昼食', '夕食', '間食'])]
    
    summary_text = meals.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', '点数'], index=False)
    prompt = f"""
    お兄ちゃんの今日の記録よ！
    {summary_text}
    
    JSONで総合評価を出して。
    {{ "daily_score": 0, "daily_advice": "最初は厳しく、最後はデレるアドバイス" }}
    """
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group()), "OK"
    except:
        return None, "エラーだわ！"

# --- PFCグラフ ---
def plot_pfc(p, f, c):
    p_cal, f_cal, c_cal = p*4, f*9, c*4
    total = p_cal + f_cal + c_cal
    if total == 0: return None
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.pie([p_cal, f_cal, c_cal], labels=['P', 'F', 'C'], autopct='%1.1f%%', colors=['#ff9999','#66b3ff','#99ff99'])
    return fig

# --- UI ---
st.title("👧 AI食事管理 (Stable)")

selected_date = st.sidebar.date_input("日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

if is_today:
    with st.expander("📝 記録しなさいよ！", expanded=True):
        meal_type = st.selectbox("種別", ["朝食", "昼食", "夕食", "間食"])
        is_skipped = st.checkbox("欠食")
        image = None
        text_input = st.text_input("メニュー/補足")
        img_file = st.file_uploader("写真(任意)", type=["jpg", "png"])
        if img_file: 
            image = Image.open(img_file)
            st.image(image, width=200)

        if st.button("診断する"):
            with st.spinner("待ってなさいよ..."):
                data = analyze_meal(image, text_input, meal_type)
                if data:
                    row = [selected_date_str, datetime.datetime.now(JST).strftime('%H:%M'), meal_type, data['menu'], data['calories'], data['protein'], data['fat'], data['carbs'], data['advice'], data['score'], data.get('purines', 0)]
                    sheet.append_row(row)
                    st.success(f"記録したわ！({data['score']}点)")
                    st.write(f"💬 {data['advice']}")
                    st.rerun()

st.divider()
try:
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df['日付'] = df['日付'].astype(str)
    day_data = df[df['日付'] == selected_date_str]
    
    if not day_data.empty:
        meals = day_data[day_data['種別'] != '日次評価']
        st.dataframe(meals[['時刻', '種別', 'メニュー名', 'カロリー(kcal)', '点数']], hide_index=True)
        
        # 集計
        for c in ['カロリー(kcal)', 'タンパク質(g)', '脂質(g)', '炭水化物(g)', 'プリン体(mg)']:
            meals[c] = pd.to_numeric(meals[c], errors='coerce').fillna(0)
        
        t_cal = meals['カロリー(kcal)'].sum()
        t_purine = meals['プリン体(mg)'].sum()
        
        st.metric("総カロリー", f"{int(t_cal)} kcal")
        st.metric("総プリン体", f"{int(t_purine)} mg")
        
        fig = plot_pfc(meals['タンパク質(g)'].sum(), meals['脂質(g)'].sum(), meals['炭水化物(g)'].sum())
        if fig: st.pyplot(fig)
        
        if st.button("🏆 今日の評価を出しなさい！"):
            res, _ = analyze_daily_summary(selected_date_str)
            if res:
                sheet.append_row([selected_date_str, "", "日次評価", "まとめ", "", "", "", "", res['daily_advice'], res['daily_score'], ""])
                st.rerun()
        
        evals = day_data[day_data['種別'] == '日次評価']
        if not evals.empty:
            st.info(f"🏆 {evals.iloc[-1]['点数']}点\n\n{evals.iloc[-1]['アドバイス']}")
except:
    st.write("データがないわよ")
