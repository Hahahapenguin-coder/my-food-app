import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import pandas as pd
import datetime
import json
import re

# --- 0. パスワード保護機能 ---
def check_password():
    """パスワード認証を行う関数"""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.title("🔒 ログイン")
    password = st.text_input("パスワードを入力してください", type="password")
    
    # ★重要：ここの "my_secret_pass" がパスワードになります。必要なら変えてください。
    if st.button("ログイン"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False

if not check_password():
    st.stop()

# --- 認証成功後のアプリ本体 ---

# 1. AIの設定 (クラウドの金庫からキーを取り出す)
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error("APIキーの設定が読み込めません。Streamlit Secretsを確認してください。")
    st.stop()

# 2. スプレッドシートの設定 (クラウドの金庫からJSONを取り出す)
try:
    SHEET_NAME = st.secrets["SHEET_NAME"]
    # secretsから辞書データとして読み込む
    credentials_dict = dict(st.secrets["gcp_service_account"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"スプレッドシート接続エラー: {e}")
    st.stop()

# 初期化：ヘッダー行がなければ作成
if not sheet.get_all_values():
    sheet.append_row(["日付", "時刻", "種別", "メニュー名", "カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "アドバイス"])

# --- 関数たち ---

def get_food_info(image):
    prompt = """
    この料理の栄養素を推測し、以下のJSON形式のみを出力してください。
    Markdownのバッククォートは不要です。数値は概算で構いません。
    {
        "menu": "料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0
    }
    """
    response = model.generate_content([prompt, image])
    text = response.text
    text = re.sub(r"```json|```", "", text).strip()
    return json.loads(text)

def get_todays_advice(current_data):
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    if df.empty or 'カロリー(kcal)' not in df.columns:
        total_cal = current_data['calories']
        total_pro = current_data['protein']
    else:
        today = datetime.date.today().strftime('%Y-%m-%d')
        if '日付' in df.columns:
            df['日付'] = df['日付'].astype(str)
            todays_df = df[df['日付'] == today]
        else:
            todays_df = pd.DataFrame()

        current_cal = pd.to_numeric(todays_df['カロリー(kcal)'], errors='coerce').sum()
        current_pro = pd.to_numeric(todays_df['タンパク質(g)'], errors='coerce').sum()
        
        total_cal = current_cal + current_data['calories']
        total_pro = current_pro + current_data['protein']
    
    prompt = f"""
    あなたはプロの管理栄養士です。ユーザーはダイエット中で、今日以下の食事を摂りました。
    
    【今日のこれまでの食事（今回含む）】
    ・総カロリー: {total_cal} kcal
    ・総タンパク質: {total_pro} g
    ・今回の食事: {current_data['menu']} ({current_data['calories']} kcal)
    
    以下の2点を短く出力してください。
    1. 今日の食事点数（100点満点中）
    2. 次の食事への具体的なアドバイス（例：「脂質が多いので夜は野菜中心で」など）
    """
    response = model.generate_content(prompt)
    return response.text

# --- アプリの画面 (UI) ---

st.title("🍽️ AI食事管理トレーナー (Cloud)")

col1, col2 = st.columns(2)
with col1:
    meal_type = st.selectbox("食事のタイミング", ["朝食", "昼食", "夕食", "間食"])
with col2:
    img_source = st.radio("画像の入力方法", ["カメラで撮影", "アルバムから選択"])

image = None
if img_source == "カメラで撮影":
    img_file = st.camera_input("料理を撮影")
else:
    img_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])

if img_file:
    image = Image.open(img_file)
    st.image(image, caption="分析中...", use_container_width=True)
    
    if st.button("記録してアドバイスをもらう"):
        with st.spinner("AIが考え中..."):
            try:
                food_data = get_food_info(image)
                st.success(f"解析完了！: {food_data['menu']}")
                advice = get_todays_advice(food_data)
                
                now = datetime.datetime.now()
                row = [
                    now.strftime('%Y-%m-%d'),
                    now.strftime('%H:%M'),
                    meal_type,
                    food_data['menu'],
                    food_data['calories'],
                    food_data['protein'],
                    food_data['fat'],
                    food_data['carbs'],
                    advice
                ]
                sheet.append_row(row)
                
                st.balloons()
                st.markdown(f"### 📊 診断結果\n{advice}")
                
                st.write("---")
                st.write("今日の記録一覧:")
                latest_data = sheet.get_all_records()
                df_show = pd.DataFrame(latest_data)
                if not df_show.empty and '日付' in df_show.columns:
                     st.dataframe(df_show[df_show['日付'] == now.strftime('%Y-%m-%d')])

            except Exception as e:
                st.error(f"エラー: {e}")