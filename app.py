streamlit
google-generativeai>=0.8.3
gspread
oauth2client
pandas
Pillow、import streamlit as st
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
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    SHEET_NAME = st.secrets["SHEET_NAME"]
    credentials_dict = json.loads(st.secrets["GCP_JSON"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
except Exception as e:
    st.error(f"設定エラー: {e}")
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
    この料理（{meal_type}）の栄養素を推測し、以下のJSON形式のみを出力してください。
    Markdownは不要です。
    "score"には、ダイエットの観点から見たこの食事の点数（0〜100点）を入れてください。
    
    {{
        "menu": "料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
        "score": 0,
        "advice": "短いアドバイス"
    }}
    """
    response = model.generate_content([prompt, image])
    text = re.sub(r"```json|```", "", response.text).strip()
    return json.loads(text)

def get_next_meal_advice(todays_df):
    """今の栄養摂取状況から、次の食事のアドバイスをする"""
    # データの整理
    summary_text = todays_df.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)'], index=False)
    
    prompt = f"""
    あなたは専属の管理栄養士です。ユーザーの「今日のこれまでの食事」は以下の通りです。
    
    {summary_text}
    
    これを踏まえて、「次の食事で何を食べるべきか」のアドバイスを150文字以内で具体的に提案してください。
    （例：タンパク質が足りないので鶏肉を、カロリーオーバー気味なのでサラダを、など）
    """
    response = model.generate_content(prompt)
    return response.text

def analyze_daily_summary(date_str, force=False):
    """その日の総合評価を行う（force=Trueなら3食揃ってなくても実行）"""
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    if df.empty or '日付' not in df.columns:
        return None, "データがありません"
    
    df['日付'] = df['日付'].astype(str)
    todays_df = df[df['日付'] == date_str]
    
    # 通常の食事だけ抽出
    meals = todays_df[todays_df['種別'].isin(['朝食', '昼食', '夕食', '間食'])]
    
    if meals.empty:
        return None, "食事データがありません"

    # AIへのプロンプト
    summary_text = meals.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)', '点数'], index=False)
    
    prompt = f"""
    ユーザーの今日の食事記録です。
    
    {summary_text}
    
    以下のJSON形式で「1日の総合評価」を出力してください。
    Markdownは不要です。
    
    {{
        "daily_score": 0,
        "daily_advice": "1日を通した総評と、明日に向けたアドバイス（厳しめでOK）"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        text = re.sub(r"```json|```", "", response.text).strip()
        result = json.loads(text)
        return result, "OK"
    except Exception as e:
        return None, str(e)

# --- UI構築 ---

st.title("🍽️ AI食事管理トレーナー Pro")

# 1. カレンダー
st.sidebar.header("📅 カレンダー")
selected_date = st.sidebar.date_input("表示する日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

# --- 2. 記録エリア（今日のみ） ---
if is_today:
    st.subheader("📝 今日の食事を記録")
    with st.expander("入力を開く", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            meal_type = st.selectbox("食事のタイミング", ["朝食", "昼食", "夕食", "間食"])
        with col2:
            is_skipped = st.checkbox("この食事は食べなかった")

        image = None
        if not is_skipped:
            img_source = st.radio("入力", ["カメラ", "アルバム"], horizontal=True, label_visibility="collapsed")
            if img_source == "カメラ":
                img_file = st.camera_input("料理を撮影")
            else:
                img_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])
            
            if img_file:
                image = Image.open(img_file)
                st.image(image, width=200)

        if st.button("記録する"):
            with st.spinner("分析中..."):
                try:
                    now_time = datetime.datetime.now(JST).strftime('%H:%M')
                    if is_skipped:
                        row = [selected_date_str, now_time, meal_type, "なし（欠食）", 0, 0, 0, 0, "欠食", 0]
                        sheet.append_row(row)
                        st.info(f"{meal_type}をスキップしました。")
                    elif image:
                        data = analyze_meal(image, meal_type)
                        row = [selected_date_str, now_time, meal_type, data['menu'], data['calories'], data['protein'], data['fat'], data['carbs'], data['advice'], data['score']]
                        sheet.append_row(row)
                        st.success(f"記録完了！ {data['menu']} ({data['score']}点)")
                    else:
                        st.error("画像かチェックボックスが必要です")
                        st.stop()
                except Exception as e:
                    st.error(f"エラー: {e}")

# --- 3. 履歴＆アドバイスエリア ---
st.divider()
st.subheader(f"📊 {selected_date_str} の記録")

try:
    all_data = sheet.get_all_records()
    df = pd.DataFrame(all_data)
    
    if not df.empty and '日付' in df.columns:
        df['日付'] = df['日付'].astype(str)
        day_data = df[df['日付'] == selected_date_str]
        
        if not day_data.empty:
            # === データ表示 ===
            # 数値変換と計算
            numeric_cols = ["カロリー(kcal)", "タンパク質(g)"]
            for col in numeric_cols:
                day_data[col] = pd.to_numeric(day_data[col], errors='coerce').fillna(0)
            
            # 通常の食事データのみ抽出（評価行を除く）
            meals_only = day_data[day_data['種別'] != '日次評価']
            
            # テーブル表示
            display_cols = ["時刻", "種別", "メニュー名", "カロリー(kcal)", "点数", "アドバイス"]
            st.dataframe(meals_only[[c for c in display_cols if c in meals_only.columns]], hide_index=True)
            
            # 合計表示
            total_cal = meals_only["カロリー(kcal)"].sum()
            total_pro = meals_only["タンパク質(g)"].sum()
            st.markdown(f"**合計: {int(total_cal)} kcal / タンパク質 {total_pro:.1f} g**")
            
            # === 新機能エリア ===
            st.write("---")
            c1, c2 = st.columns(2)
            
            # 機能1: 次の食事のアドバイス（今日の場合のみ）
            if is_today:
                with c1:
                    if st.button("🍎 次は何食べる？"):
                        with st.spinner("AI管理栄養士が考え中..."):
                            advice = get_next_meal_advice(meals_only)
                            st.info(f"**次の食事へのアドバイス:**\n\n{advice}")

            # 機能2: 総合評価の手動実行
            with c2:
                if st.button("🏆 総合評価を出す"):
                    with st.spinner("1日を採点中..."):
                        res, msg = analyze_daily_summary(selected_date_str, force=True)
                        if res:
                            # 既存の評価があれば消して上書きしたいが、簡易的に追記にする
                            # (厳密な重複排除は複雑になるため)
                            now_time = datetime.datetime.now(JST).strftime('%H:%M')
                            eval_row = [selected_date_str, now_time, "日次評価", "総合評価", "", "", "", "", res['daily_advice'], res['daily_score']]
                            sheet.append_row(eval_row)
                            st.balloons()
                            st.success(f"評価完了！ スコア: {res['daily_score']}点")
                            st.rerun() # 画面更新して表に反映
                        else:
                            st.warning(f"評価できませんでした: {msg}")

            # 既に評価がある場合の表示
            daily_summary = day_data[day_data['種別'] == '日次評価']
            if not daily_summary.empty:
                # 最新の評価を取得
                last_eval = daily_summary.iloc[-1]
                st.success(f"🏆 **今日の総合評価: {last_eval['点数']}点**\n\n{last_eval['アドバイス']}")

        else:
            st.write("記録はまだありません。")
    else:
        st.write("データがありません。")

except Exception as e:
    st.error(f"読み込みエラー: {e}")で完璧に動いた！！！
