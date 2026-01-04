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
# 日本時間の設定
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

# ヘッダー確認（点数列がない場合の安全策）
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
    "advice"には、この食事に対する短いコメントを入れてください。
    
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

def analyze_daily_summary(date_str):
    """その日の食事データ（朝昼夕）から、1日の総合評価を行う"""
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    # 対象日のデータを抽出
    if df.empty or '日付' not in df.columns:
        return None
    
    df['日付'] = df['日付'].astype(str)
    todays_df = df[df['日付'] == date_str]
    
    # 既に「日次評価」が記録されているかチェック（重複防止）
    if not todays_df[todays_df['種別'] == '日次評価'].empty:
        return None

    # 朝・昼・夕のデータがあるか確認
    meals = todays_df[todays_df['種別'].isin(['朝食', '昼食', '夕食'])]
    meal_types = meals['種別'].unique()
    
    # 3食揃っていないなら評価しない
    if not ({'朝食', '昼食', '夕食'} <= set(meal_types)):
        return None

    # AIに送るためのテキストを作成
    summary_text = meals.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)', '点数'], index=False)
    
    prompt = f"""
    あなたはプロの管理栄養士です。以下はユーザーの今日の3食の記録です。
    
    {summary_text}
    
    これらを踏まえて、以下のJSON形式で「1日の総合評価」を出力してください。
    Markdownは不要です。
    
    {{
        "daily_score": 0,
        "daily_advice": "1日を通した総評と、明日に向けたアドバイス（100文字程度）"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        text = re.sub(r"```json|```", "", response.text).strip()
        result = json.loads(text)
        return result
    except:
        return None

# --- UI構築 ---

st.title("🍽️ AI食事管理トレーナー Pro")

# 1. 日付選択エリア
st.sidebar.header("📅 カレンダー")
selected_date = st.sidebar.date_input("表示する日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')

# 今日かどうか判定
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

# --- メインエリア：記録フォーム（今日の場合のみ表示） ---
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
            img_source = st.radio("画像の入力方法", ["カメラで撮影", "アルバムから選択"], horizontal=True)
            if img_source == "カメラで撮影":
                img_file = st.camera_input("料理を撮影")
            else:
                img_file = st.file_uploader("画像をアップロード", type=["jpg", "png", "jpeg"])
            
            if img_file:
                image = Image.open(img_file)
                st.image(image, width=200)

        # 記録ボタン
        if st.button("記録する"):
            with st.spinner("AIが分析中..."):
                try:
                    now_time = datetime.datetime.now(JST).strftime('%H:%M')
                    
                    if is_skipped:
                        # 欠食として記録
                        row = [selected_date_str, now_time, meal_type, "なし（欠食）", 0, 0, 0, 0, "欠食として記録しました", 0]
                        sheet.append_row(row)
                        st.info(f"{meal_type}を「なし」として記録しました。")
                    
                    elif image:
                        # 画像分析
                        data = analyze_meal(image, meal_type)
                        row = [
                            selected_date_str,
                            now_time,
                            meal_type,
                            data['menu'],
                            data['calories'],
                            data['protein'],
                            data['fat'],
                            data['carbs'],
                            data['advice'],
                            data['score']
                        ]
                        sheet.append_row(row)
                        st.success(f"記録完了！ {data['menu']} ({data['score']}点)")
                    else:
                        st.error("画像を選択するか、「食べなかった」にチェックを入れてください。")
                        st.stop()
                    
                    # ★ここが新機能：3食揃ったら自動で「日次評価」を行う
                    daily_eval = analyze_daily_summary(selected_date_str)
                    if daily_eval:
                        # 日次評価を書き込み（カロリー等は空欄）
                        eval_row = [
                            selected_date_str, 
                            now_time, 
                            "日次評価", 
                            "1日のまとめ", 
                            "", "", "", "", 
                            daily_eval['daily_advice'], 
                            daily_eval['daily_score']
                        ]
                        sheet.append_row(eval_row)
                        st.balloons()
                        st.markdown(f"### 🏆 今日の合計スコア: {daily_eval['daily_score']}点！")
                        st.write(daily_eval['daily_advice'])
                        
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

# --- 履歴表示エリア ---
st.divider()
st.subheader(f"📊 {selected_date_str} の記録")

# データ取得と表示
try:
    all_data = sheet.get_all_records()
    df = pd.DataFrame(all_data)
    
    if not df.empty and '日付' in df.columns:
        df['日付'] = df['日付'].astype(str)
        day_data = df[df['日付'] == selected_date_str]
        
        if not day_data.empty:
            # 必要な列だけ表示
            display_cols = ["時刻", "種別", "メニュー名", "カロリー(kcal)", "点数", "アドバイス"]
            # カラムが存在するか確認してから表示
            available_cols = [c for c in display_cols if c in day_data.columns]
            st.dataframe(day_data[available_cols], hide_index=True)
            
            # 合計カロリー計算（日次評価の行や欠食は除外して計算）
            numeric_cols = ["カロリー(kcal)", "タンパク質(g)"]
            for col in numeric_cols:
                # ★ここが修正済みの行です
                day_data[col] = pd.to_numeric(day_data[col], errors='coerce').fillna(0)
            
            # 通常の食事のみ合計する
            meals_only = day_data[day_data['種別'] != '日次評価']
            total_cal = meals_only["カロリー(kcal)"].sum()
            total_pro = meals_only["タンパク質(g)"].sum()
            
            st.markdown(f"**合計: {int(total_cal)} kcal / タンパク質 {total_pro:.1f} g**")
            
            # 日次評価があれば目立たせて表示
            daily_summary = day_data[day_data['種別'] == '日次評価']
            if not daily_summary.empty:
                score = daily_summary.iloc[0]['点数']
                advice = daily_summary.iloc[0]['アドバイス']
                st.info(f"🏆 **この日の総合評価: {score}点**\n\n{advice}")
        else:
            st.write("この日の記録はありません。")
    else:
        st.write("データがまだありません。")
except Exception as e:
    st.error(f"データ読み込みエラー: {e}")
