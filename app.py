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
    
    # ★安定稼働の 1.5-flash を採用
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
    
    SHEET_NAME = st.secrets["SHEET_NAME"]
    credentials_dict = json.loads(st.secrets["GCP_JSON"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"設定エラーだわ！確認しなさいよ！: {e}")
    st.stop()

# ヘッダー確認（プリン体対応）
try:
    if not sheet.get_all_values():
        sheet.append_row(["日付", "時刻", "種別", "メニュー名", "カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "アドバイス", "点数", "プリン体(mg)"])
except:
    pass

# --- グラフ描画関数 ---
def plot_pfc(p, f, c):
    """PFCバランスをカロリーベースで円グラフ化"""
    p_cal, f_cal, c_cal = p * 4, f * 9, c * 4
    total = p_cal + f_cal + c_cal
    if total == 0: return None
    
    fig, ax = plt.subplots(figsize=(5, 5))
    labels = [f'P: {p_cal/total*100:.1f}%', f'F: {f_cal/total*100:.1f}%', f'C: {c_cal/total*100:.1f}%']
    ax.pie([p_cal, f_cal, c_cal], labels=labels, startangle=90, counterclock=False, colors=['#ff9999','#66b3ff','#99ff99'])
    ax.set_title("PFC Balance (kcal ratio)")
    return fig

# --- AI分析関数（ツンデレ妹Ver.） ---

def analyze_meal(image, text_input, meal_type):
    """食事を分析。ツンデレ妹の人格を注入"""
    prompt = f"""
    あなたはユーザー（お兄ちゃん）の健康を管理する、ツインテールのツンデレ妹よ。
    語尾は「〜よ」「〜じゃない」「〜だわ」で、口調は乱暴だけどお兄ちゃんを心から心配してる感じにして。
    
    【タスク】
    食事（{meal_type}）を分析して以下のJSONのみを出力して。Markdown不要。
    補足情報：{text_input if text_input else "なし"}
    
    - "score": 健康点数（0〜100）
    - "purine": プリン体(mg)の推測値
    - "advice": ツンデレ口調のアドバイス。最初は厳しく、最後はデレて（褒めるか励ます）。
    
    {{
        "menu": "料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
        "purine": 0.0,
        "score": 0,
        "advice": "アドバイス"
    }}
    """
    content = [prompt]
    if image: content.append(image)
    if text_input: content.append(f"ユーザーの補足: {text_input}")
    
    try:
        response = model.generate_content(content)
        # JSON部分だけを抽出するガード
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        st.error(f"AIが反抗期だわ！: {e}")
        return None

def get_next_meal_advice(todays_df):
    """次の食事アドバイス（ツンデレ妹）"""
    summary = todays_df.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)'], index=False)
    prompt = f"お兄ちゃんの今日の記録よ。これを踏まえて次は何を食べればいいかツンデレ妹口調で教えて。\n{summary}"
    response = model.generate_content(prompt)
    return response.text

def analyze_daily_summary(date_str):
    """1日の総評（ツンデレ妹）"""
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df['日付'] = df['日付'].astype(str)
    day_data = df[df['日付'] == date_str]
    meals = day_data[day_data['種別'].isin(['朝食', '昼食', '夕食', '間食'])]
    
    summary = meals.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', '点数'], index=False)
    prompt = f"今日の記録よ！総合評価をJSONで。{{'daily_score':0, 'daily_advice':''}}\nアドバイスはツンデレ妹風にね！\n{summary}"
    
    try:
        response = model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(match.group())
    except:
        return None

# --- UI構築 ---

st.title("👧 AI食事管理トレーナー Pro")

# サイドバー
selected_date = st.sidebar.date_input("日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

# 記録エリア
if is_today:
    st.subheader("📝 食べたもの、早く記録しなさいよ！")
    with st.expander("入力を開く", expanded=True):
        col1, col2 = st.columns(2)
        meal_type = col1.selectbox("種別", ["朝食", "昼食", "夕食", "間食"])
        is_skipped = col2.checkbox("食べなかった")

        image = None
        text_input = ""
        if not is_skipped:
            text_input = st.text_input("メニュー/補足（例：ごはん半分）")
            img_source = st.radio("写真", ["カメラ", "アルバム", "なし"], horizontal=True)
            if img_source == "カメラ":
                img_file = st.camera_input("撮影")
                if img_file: image = Image.open(img_file)
            elif img_source == "アルバム":
                img_file = st.file_uploader("アップロード", type=["jpg", "png"])
                if img_file: 
                    image = Image.open(img_file)
                    st.image(image, width=200)

        if st.button("お兄ちゃんを診断！"):
            with st.spinner("分析してあげるから待ってなさい..."):
                data = analyze_meal(image, text_input, meal_type)
                if data:
                    now_time = datetime.datetime.now(JST).strftime('%H:%M')
                    row = [selected_date_str, now_time, meal_type, data['menu'], data['calories'], data['protein'], data['fat'], data['carbs'], data['advice'], data['score'], data.get('purine', 0)]
                    sheet.append_row(row)
                    st.success(f"記録完了！ {data['score']}点なんだからね！")
                    st.write(f"💬 **妹のアドバイス:** {data['advice']}")
                    st.rerun()

# 履歴表示エリア
st.divider()
st.subheader(f"📊 {selected_date_str} の記録")

try:
    all_records = sheet.get_all_records()
    df = pd.DataFrame(all_records)
    if not df.empty:
        df['日付'] = df['日付'].astype(str)
        day_data = df[df['日付'] == selected_date_str]
        
        if not day_data.empty:
            # 数値変換
            for c in ["カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "プリン体(mg)"]:
                if c in day_data.columns:
                    day_data[c] = pd.to_numeric(day_data[c], errors='coerce').fillna(0)
            
            meals = day_data[day_data['種別'] != '日次評価']
            st.dataframe(meals[['時刻', '種別', 'メニュー名', 'カロリー(kcal)', '点数', 'アドバイス']], hide_index=True)
            
            # 合計と可視化
            t_cal = meals['カロリー(kcal)'].sum()
            t_pro = meals['タンパク質(g)'].sum()
            t_fat = meals['脂質(g)'].sum()
            t_carb = meals['炭水化物(g)'].sum()
            t_purine = meals['プリン体(mg)'].sum() if 'プリン体(mg)' in meals.columns else 0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("総カロリー", f"{int(t_cal)} kcal")
            c2.metric("タンパク質", f"{t_pro:.1f} g")
            c3.metric("プリン体", f"{int(t_purine)} mg")
            
            # PFCグラフ
            fig = plot_pfc(t_pro, t_fat, t_carb)
            if fig: st.pyplot(fig)
            
            # アドバイスボタン
            st.write("---")
            if is_today and st.button("🍎 次は何食べればいい？"):
                st.info(get_next_meal_advice(meals))
            
            if st.button("🏆 今日の総合採点"):
                res = analyze_daily_summary(selected_date_str)
                if res:
                    sheet.append_row([selected_date_str, "", "日次評価", "総合評価", "", "", "", "", res['daily_advice'], res['daily_score'], ""])
                    st.balloons()
                    st.rerun()
            
            # 評価表示
            evals = day_data[day_data['種別'] == '日次評価']
            if not evals.empty:
                last = evals.iloc[-1]
                st.success(f"🏆 総合評価: {last['点数']}点\n\n{last['アドバイス']}")
        else:
            st.write("記録がまだないわよ。サボらないで！")
except Exception as e:
    st.error(f"読み込みエラーだわ！: {e}")
