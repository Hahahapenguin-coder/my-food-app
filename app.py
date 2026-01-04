import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import pandas as pd
import datetime
import json
import re

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
    # APIキー設定
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    
    # ★ここが決定版：最新の「Gemini 1.5 Flash」を使用
    # このモデルは画像もテキストも両方理解できます
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # スプレッドシート設定
    SHEET_NAME = st.secrets["SHEET_NAME"]
    credentials_dict = json.loads(st.secrets["GCP_JSON"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"起動エラー: 設定を確認してください。\n詳細: {e}")
    st.stop()

# ヘッダー確認
try:
    if not sheet.get_all_values():
        sheet.append_row(["日付", "時刻", "種別", "メニュー名", "カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "アドバイス", "点数"])
except:
    pass

# --- AI分析関数 ---

def analyze_meal(image, meal_type):
    """食事画像を分析して栄養素と点数を出す"""
    prompt = f"""
    あなたはプロの管理栄養士です。
    この料理画像（{meal_type}）を見て、栄養素を推測し、JSON形式のみを出力してください。
    Markdownのバッククォートは不要です。
    "score"には、ダイエットの観点から見た点数（0〜100点）を入れてください。
    
    {{
        "menu": "具体的な料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
        "score": 0,
        "advice": "短く的確なアドバイス"
    }}
    """
    try:
        response = model.generate_content([prompt, image])
        text = re.sub(r"```json|```", "", response.text).strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"AI分析エラー: {e}")
        return None

def get_next_meal_advice(todays_df):
    """次の食事のアドバイス"""
    summary_text = todays_df.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)'], index=False)
    prompt = f"""
    ユーザーの今日の食事記録：
    {summary_text}
    
    これを踏まえて、次の食事で摂るべきもの、控えるべきものを150文字以内でアドバイスしてください。
    """
    response = model.generate_content(prompt)
    return response.text

def analyze_daily_summary(date_str):
    """1日の総合評価"""
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    if df.empty or '日付' not in df.columns:
        return None, "データなし"
    
    df['日付'] = df['日付'].astype(str)
    todays_df = df[df['日付'] == date_str]
    meals = todays_df[todays_df['種別'].isin(['朝食', '昼食', '夕食', '間食'])]
    
    if meals.empty:
        return None, "食事データなし"

    summary_text = meals.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)', '点数'], index=False)
    
    prompt = f"""
    今日の食事記録：
    {summary_text}
    
    以下JSON形式で総合評価を出力してください。Markdown不要。
    {{
        "daily_score": 0,
        "daily_advice": "総評と明日へのアドバイス"
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = re.sub(r"```json|```", "", response.text).strip()
        return json.loads(text), "OK"
    except Exception as e:
        return None, str(e)

# --- UI構築 ---

st.title("🍽️ AI食事管理トレーナー (Reborn)")

# カレンダー
st.sidebar.header("📅 カレンダー")
selected_date = st.sidebar.date_input("日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

# 記録エリア
if is_today:
    st.subheader("📝 食事記録")
    with st.expander("入力を開く", expanded=True):
        c1, c2 = st.columns(2)
        meal_type = c1.selectbox("種別", ["朝食", "昼食", "夕食", "間食"])
        is_skipped = c2.checkbox("食べなかった")

        image = None
        if not is_skipped:
            img_source = st.radio("画像", ["カメラ", "アルバム"], horizontal=True)
            if img_source == "カメラ":
                img_file = st.camera_input("撮影")
            else:
                img_file = st.file_uploader("アップロード", type=["jpg", "png"])
            
            if img_file:
                image = Image.open(img_file)
                st.image(image, width=200)

        if st.button("記録する"):
            with st.spinner("AI分析中..."):
                try:
                    now_time = datetime.datetime.now(JST).strftime('%H:%M')
                    if is_skipped:
                        row = [selected_date_str, now_time, meal_type, "なし", 0, 0, 0, 0, "欠食", 0]
                        sheet.append_row(row)
                        st.info("欠食を記録しました")
                    elif image:
                        data = analyze_meal(image, meal_type)
                        if data:
                            row = [selected_date_str, now_time, meal_type, data['menu'], data['calories'], data['protein'], data['fat'], data['carbs'], data['advice'], data['score']]
                            sheet.append_row(row)
                            st.success(f"記録完了: {data['menu']} ({data['score']}点)")
                    else:
                        st.error("画像が必要です")
                except Exception as e:
                    st.error(f"エラー: {e}")

# 履歴エリア
st.divider()
st.subheader(f"📊 {selected_date_str}")

try:
    all_data = sheet.get_all_records()
    df = pd.DataFrame(all_data)
    
    if not df.empty and '日付' in df.columns:
        df['日付'] = df['日付'].astype(str)
        day_data = df[df['日付'] == selected_date_str]
        
        if not day_data.empty:
            # 数値変換
            for col in ["カロリー(kcal)", "タンパク質(g)"]:
                day_data[col] = pd.to_numeric(day_data[col], errors='coerce').fillna(0)
            
            meals_only = day_data[day_data['種別'] != '日次評価']
            
            # 表示
            cols = ["時刻", "種別", "メニュー名", "カロリー(kcal)", "点数", "アドバイス"]
            st.dataframe(meals_only[[c for c in cols if c in meals_only.columns]], hide_index=True)
            
            total_cal = meals_only["カロリー(kcal)"].sum()
            total_pro = meals_only["タンパク質(g)"].sum()
            st.markdown(f"**合計: {int(total_cal)} kcal / タンパク質 {total_pro:.1f} g**")
            
            st.write("---")
            c1, c2 = st.columns(2)
            if is_today and st.button("🍎 次のアドバイス"):
                with st.spinner("思考中..."):
                    st.info(get_next_meal_advice(meals_only))
            
            if st.button("🏆 今日の評価"):
                with st.spinner("採点中..."):
                    res, msg = analyze_daily_summary(selected_date_str)
                    if res:
                        sheet.append_row([selected_date_str, datetime.datetime.now(JST).strftime('%H:%M'), "日次評価", "まとめ", "", "", "", "", res['daily_advice'], res['daily_score']])
                        st.balloons()
                        st.success(f"スコア: {res['daily_score']}点")
                        st.rerun()
                    else:
                        st.warning(msg)
            
            # 評価表示
            evals = day_data[day_data['種別'] == '日次評価']
            if not evals.empty:
                last = evals.iloc[-1]
                st.success(f"🏆 総合評価: {last['点数']}点\n\n{last['アドバイス']}")
        else:
            st.write("記録なし")
except Exception as e:
    st.error(f"データ読込エラー: {e}")
