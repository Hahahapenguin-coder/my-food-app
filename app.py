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
    password = st.text_input("パスワードを入力してよね！", type="password")
    if st.button("ログイン"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("は？パスワードが違うんだけど。")
    return False

if not check_password():
    st.stop()

# --- 1. 設定・初期化 ---
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

try:
    # APIキーとモデル設定 (ひろさんのリストにあった一番安定したモデルを使用)
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # スプレッドシート接続
    credentials_dict = json.loads(st.secrets["GCP_JSON"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(st.secrets["SHEET_NAME"]).sheet1
except Exception as e:
    st.error(f"起動エラーだわ！設定見直しなさいよ！: {e}")
    st.stop()

# --- 2. AI分析関数（ツンデレ妹Ver） ---

def analyze_meal(image, text_input, meal_type):
    prompt = f"""
    あなたはユーザー（お兄ちゃん）の健康を心配しすぎる「ツンデレなツインテール妹」よ。
    口調は「〜よ」「〜じゃない」「〜だわ」で、基本は厳しいけど最後にデレて。

    【依頼内容】食事（{meal_type}）を分析して以下のJSON形式のみを出力して。Markdownは絶対禁止。
    補足情報：{text_input if text_input else "特になし"}

    {{
        "menu": "料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
        "purine": 0.0,
        "score": 0,
        "advice": "妹からのツンデレアドバイス"
    }}
    """
    content = [prompt]
    if image: content.append(image)
    if text_input: content.append(f"お兄ちゃんからのメモ: {text_input}")
    
    try:
        response = model.generate_content(content)
        # JSON部分を安全に抽出
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        st.error(f"AIが反抗期みたい: {e}")
        return None

# --- 3. PFCバランス可視化 ---

def show_pfc_chart(p, f, c):
    p_cal, f_cal, c_cal = p * 4, f * 9, c * 4
    total = p_cal + f_cal + c_cal
    if total == 0: return
    
    fig, ax = plt.subplots(figsize=(5, 5))
    labels = ['Protein', 'Fat', 'Carbohydrate']
    colors = ['#ff9999','#66b3ff','#99ff99']
    ax.pie([p_cal, f_cal, c_cal], labels=labels, autopct='%1.1f%%', startangle=90, colors=colors)
    ax.set_title("Today's PFC Balance (kcal base)")
    st.pyplot(fig)

# --- 4. UI構築 ---

st.title("🍽️ 妹のAI食事管理トレーナー Pro")

# 日付選択
selected_date = st.sidebar.date_input("日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

if is_today:
    st.subheader("📝 食べたもの、さっさと記録しなさいよね！")
    with st.expander("記録画面を開く", expanded=True):
        col1, col2 = st.columns(2)
        meal_type = col1.selectbox("いつの食事？", ["朝食", "昼食", "夕食", "間食"])
        is_skipped = col2.checkbox("今日は食べないの？")
        
        image = None
        text_input = ""
        if not is_skipped:
            text_input = st.text_input("メニューとか言い訳（補足）があれば書きなさいよ")
            img_source = st.radio("写真", ["カメラ", "アルバム", "なし"], horizontal=True)
            if img_source == "カメラ":
                img_file = st.camera_input("撮影")
                if img_file: image = Image.open(img_file)
            elif img_source == "アルバム":
                img_file = st.file_uploader("アップロード", type=["jpg", "png"])
                if img_file: 
                    image = Image.open(img_file)
                    st.image(image, width=200)

        if st.button("お兄ちゃんの健康を診断！"):
            with st.spinner("分析中..."):
                if is_skipped:
                    sheet.append_row([selected_date_str, datetime.datetime.now(JST).strftime('%H:%M'), meal_type, "欠食", 0, 0, 0, 0, "ちゃんと食べなきゃダメでしょ！", 0, 0])
                    st.info("欠食を記録したわよ。")
                else:
                    data = analyze_meal(image, text_input, meal_type)
                    if data:
                        row = [selected_date_str, datetime.datetime.now(JST).strftime('%H:%M'), meal_type, 
                               data['menu'], data['calories'], data['protein'], data['fat'], 
                               data['carbs'], data['advice'], data['score'], data.get('purine', 0)]
                        sheet.append_row(row)
                        st.success(f"記録完了！ {data['score']}点なんだから！")
                        st.write(f"💬 {data['advice']}")
                        st.rerun()

# 履歴と分析
st.divider()
st.subheader(f"📊 {selected_date_str} の栄養レポート")

try:
    all_data = sheet.get_all_records()
    df = pd.DataFrame(all_data)
    if not df.empty:
        df['日付'] = df['日付'].astype(str)
        day_data = df[df['日付'] == selected_date_str]
        
        if not day_data.empty:
            # 数値変換
            for c in ["カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "プリン体(mg)"]:
                if c in day_data.columns:
                    day_data[c] = pd.to_numeric(day_data[c], errors='coerce').fillna(0)
            
            meals = day_data[day_data['種別'] != '日次評価']
            st.dataframe(meals[['時刻', '種別', 'メニュー名', 'カロリー(kcal)', '点数']], hide_index=True)
            
            # 統計
            t_cal = meals['カロリー(kcal)'].sum()
            t_pro = meals['タンパク質(g)'].sum()
            t_purine = meals['プリン体(mg)'].sum() if 'プリン体(mg)' in meals.columns else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("総カロリー", f"{int(t_cal)} kcal")
            col2.metric("タンパク質", f"{t_pro:.1f} g")
            col3.metric("プリン体", f"{int(t_purine)} mg")
            
            # PFCグラフ
            
            show_pfc_chart(meals['タンパク質(g)'].sum(), meals['脂質(g)'].sum(), meals['炭水化物(g)'].sum())
            
            # 総合評価
            if st.button("🏆 今日の総合評価を下しなさいよ！"):
                st.write("採点中...")
                # ...評価処理は上の記録と同じ要領で実装可能...
                st.balloons()
        else:
            st.write("まだ何も記録されてないわよ。サボり？")
except Exception as e:
    st.error(f"データが読み込めないわ！: {e}")
