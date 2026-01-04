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

# フォント設定（日本語豆腐文字化け対策：Streamlit Cloud環境用）
# Cloud環境で日本語フォントがない場合、英語表記にするか、別途フォント設定が必要ですが
# ここでは簡易的にデフォルトフォントを使用します。

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    
    # ★ご指定の Gemini 2.5 Flash
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

# ヘッダー確認（プリン体列がない場合の安全策）
try:
    if not sheet.get_all_values():
        sheet.append_row(["日付", "時刻", "種別", "メニュー名", "カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "アドバイス", "点数", "プリン体(mg)"])
except:
    pass

# --- AI分析関数（ツンデレ妹Ver） ---

def analyze_meal(image, text_input, meal_type):
    """食事画像とテキストを分析"""
    
    prompt = f"""
    あなたはユーザー（お兄ちゃん）の健康を管理している「ツンデレな妹（ツインテール）」になりきってください。
    
    【キャラクター設定】
    - 一人称は「私」、相手のことは「お兄ちゃん」か「あんた」。
    - 基本的には厳しく、カロリーや栄養バランスにうるさい。「もう、またこんなの食べて！」と怒る。
    - でも最後は「...でも、あんたが病気になったら困るんだからね」や「ま、今回は許してあげる」のように、少しだけデレて（優しく）ください。
    - 口調は砕けたタメ口で。

    【タスク】
    食事（{meal_type}）を分析し、以下のJSON形式のみを出力してください。Markdown不要。
    補足テキスト：{text_input if text_input else "なし"}
    
    - "score": 0〜100点（厳しめにつけること）
    - "purines": プリン体（mg）の概算値（わからなければ一般的な値で推測）
    - "advice": キャラクター設定を守ったアドバイス（100文字程度）
    
    {{
        "menu": "料理名",
        "calories": 0,
        "protein": 0.0,
        "fat": 0.0,
        "carbs": 0.0,
        "purines": 0.0,
        "score": 0,
        "advice": "ツンデレ口調のアドバイス"
    }}
    """
    
    content_parts = [prompt]
    if image: content_parts.append(image)
    if text_input: content_parts.append(f"補足: {text_input}")

    try:
        response = model.generate_content(content_parts)
        text = re.sub(r"```json|```", "", response.text).strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"AI分析エラー: {e}")
        return None

def get_next_meal_advice(todays_df):
    """次の食事アドバイス（ツンデレ妹Ver）"""
    summary_text = todays_df.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'タンパク質(g)', 'プリン体(mg)'], index=False)
    
    prompt = f"""
    あなたは「ツンデレな妹」です。お兄ちゃんの今日の食事がこれよ。
    
    {summary_text}
    
    これを踏まえて、次の食事で何を食べるべきか教えてあげて。
    口調例：「ちょっと！タンパク質足りてないじゃない。夜は鶏むね肉にしなさいよ。べ、別にあんたの筋肉のためじゃないんだからね！」
    """
    response = model.generate_content(prompt)
    return response.text

def analyze_daily_summary(date_str):
    """1日の総合評価（ツンデレ妹Ver）"""
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    if df.empty or '日付' not in df.columns:
        return None, "データなし"
    
    df['日付'] = df['日付'].astype(str)
    todays_df = df[df['日付'] == date_str]
    meals = todays_df[todays_df['種別'].isin(['朝食', '昼食', '夕食', '間食'])]
    
    if meals.empty:
        return None, "食事データなし"

    summary_text = meals.to_string(columns=['種別', 'メニュー名', 'カロリー(kcal)', 'プリン体(mg)', '点数'], index=False)
    
    prompt = f"""
    お兄ちゃんの今日の食事記録よ。
    
    {summary_text}
    
    JSON形式で総合評価を出力して。Markdown不要。
    adviceは、最初は厳しく（点数が低ければ罵倒してもいい）、最後は「明日も頑張りなさいよ！」と励ますツンデレ口調で。
    
    {{
        "daily_score": 0,
        "daily_advice": "ツンデレ口調の総評"
    }}
    """
    try:
        response = model.generate_content(prompt)
        text = re.sub(r"```json|```", "", response.text).strip()
        return json.loads(text), "OK"
    except Exception as e:
        return None, str(e)

# --- グラフ描画関数 ---
def plot_pfc(protein, fat, carbs):
    # カロリーベースで計算 (P=4, F=9, C=4)
    p_cal = protein * 4
    f_cal = fat * 9
    c_cal = carbs * 4
    total = p_cal + f_cal + c_cal
    
    if total == 0: return None

    labels = ['Protein', 'Fat', 'Carbs']
    sizes = [p_cal, f_cal, c_cal]
    colors = ['#ff9999','#66b3ff','#99ff99']
    
    fig1, ax1 = plt.subplots()
    ax1.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    ax1.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
    return fig1

# --- UI構築 ---

st.title("👧 妹のAI食事管理 (PFC & プリン体対応)")

# 1. カレンダー
st.sidebar.header("📅 カレンダー")
selected_date = st.sidebar.date_input("日付", datetime.datetime.now(JST))
selected_date_str = selected_date.strftime('%Y-%m-%d')
is_today = (selected_date_str == datetime.datetime.now(JST).strftime('%Y-%m-%d'))

# --- 2. 記録エリア ---
if is_today:
    st.subheader("📝 何食べたの？早く記録しなさいよ！")
    with st.expander("記録画面を開く", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            meal_type = st.selectbox("いつ食べたの？", ["朝食", "昼食", "夕食", "間食"])
        with col2:
            is_skipped = st.checkbox("食べてない（欠食）")

        image = None
        text_input = ""

        if not is_skipped:
            text_input = st.text_input("メニュー名・言い訳（補足情報）")
            img_source = st.radio("写真はある？", ["カメラ", "アルバム", "ない"], horizontal=True)
            
            if img_source == "カメラ":
                img_file = st.camera_input("撮影")
                if img_file: image = Image.open(img_file)
            elif img_source == "アルバム":
                img_file = st.file_uploader("アップロード", type=["jpg", "png", "jpeg"])
                if img_file: 
                    image = Image.open(img_file)
                    st.image(image, width=200)

        if st.button("これでお兄ちゃんを診断する！"):
            with st.spinner("ふん、計算してあげるから待ってなさい..."):
                try:
                    now_time = datetime.datetime.now(JST).strftime('%H:%M')
                    if is_skipped:
                        row = [selected_date_str, now_time, meal_type, "なし", 0, 0, 0, 0, "ちゃんと食べなさいよバカ！", 0, 0]
                        sheet.append_row(row)
                        st.info("欠食を記録したわ。体壊しても知らないからね！")
                    elif image or text_input:
                        data = analyze_meal(image, text_input, meal_type)
                        if data:
                            # プリン体がない場合のガード
                            purines = data.get('purines', 0)
                            
                            row = [
                                selected_date_str, now_time, meal_type, data['menu'], 
                                data['calories'], data['protein'], data['fat'], data['carbs'], 
                                data['advice'], data['score'], purines
                            ]
                            sheet.append_row(row)
                            st.success(f"記録したわよ。 {data['menu']} ... {data['score']}点なんだから！")
                            st.write(f"💬 **妹からのコメント:** {data['advice']}")
                    else:
                        st.error("写真か文字くらい入れなさいよ！")
                        st.stop()
                except Exception as e:
                    st.error(f"エラー発生！もう、何やってんのよ: {e}")

# --- 3. 履歴＆分析エリア ---
st.divider()
st.subheader(f"📊 {selected_date_str} の栄養状況")

try:
    all_data = sheet.get_all_records()
    df = pd.DataFrame(all_data)
    
    if not df.empty and '日付' in df.columns:
        df['日付'] = df['日付'].astype(str)
        day_data = df[df['日付'] == selected_date_str]
        
        if not day_data.empty:
            # 数値変換
            num_cols = ["カロリー(kcal)", "タンパク質(g)", "脂質(g)", "炭水化物(g)", "プリン体(mg)"]
            for col in num_cols:
                if col in day_data.columns:
                    day_data[col] = pd.to_numeric(day_data[col], errors='coerce').fillna(0)
            
            meals_only = day_data[day_data['種別'] != '日次評価']
            
            # 1. 食べたものリスト
            display_cols = ["時刻", "種別", "メニュー名", "カロリー(kcal)", "プリン体(mg)", "点数", "アドバイス"]
            valid_cols = [c for c in display_cols if c in meals_only.columns]
            st.dataframe(meals_only[valid_cols], hide_index=True)
            
            # 2. 合計値計算
            total_cal = meals_only["カロリー(kcal)"].sum()
            total_pro = meals_only["タンパク質(g)"].sum()
            total_fat = meals_only["脂質(g)"].sum()
            total_carb = meals_only["炭水化物(g)"].sum()
            total_purine = meals_only["プリン体(mg)"].sum()
            
            # 3. 数値表示
            col1, col2, col3 = st.columns(3)
            col1.metric("総カロリー", f"{int(total_cal)} kcal")
            col2.metric("総タンパク質", f"{total_pro:.1f} g")
            col3.metric("総プリン体", f"{int(total_purine)} mg", delta_color="inverse")

            # 4. PFCバランスグラフ
            st.write("##### 🍰 PFCバランス（カロリー比率）")
            fig = plot_pfc(total_pro, total_fat, total_carb)
            if fig:
                st.pyplot(fig)
            else:
                st.caption("データがまだないわよ。")

            st.write("---")
            
            # 5. アクションボタン
            c1, c2 = st.columns(2)
            if is_today:
                with c1:
                    if st.button("🍎 次は何食べればいい？"):
                        with st.spinner("ちょっと待ってて..."):
                            advice = get_next_meal_advice(meals_only)
                            st.info(f"**妹のアドバイス:**\n\n{advice}")

            with c2:
                if st.button("🏆 今日の通信簿をつける"):
                    with st.spinner("採点中...覚悟しなさいよ！"):
                        res, msg = analyze_daily_summary(selected_date_str)
                        if res:
                            now_time = datetime.datetime.now(JST).strftime('%H:%M')
                            eval_row = [selected_date_str, now_time, "日次評価", "総合評価", "", "", "", "", res['daily_advice'], res['daily_score'], ""]
                            sheet.append_row(eval_row)
                            st.balloons()
                            st.success(f"点数は... {res['daily_score']}点よ！")
                            st.rerun()

            # 6. 最新の評価表示
            daily_summary = day_data[day_data['種別'] == '日次評価']
            if not daily_summary.empty:
                last_eval = daily_summary.iloc[-1]
                st.success(f"🏆 **今日の評価: {last_eval['点数']}点**\n\n{last_eval['アドバイス']}")

        else:
            st.info("まだ何も食べてないの？記録しなさいよ！")
    else:
        st.write("データがないわ。")

except Exception as e:
    st.error(f"ちょっとエラー出てるわよ！確認して！: {e}")
