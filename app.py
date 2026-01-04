import streamlit as st
import google.generativeai as genai

# --- 簡易モデル診断ツール ---

st.title("🤖 AIモデル診断")

try:
    # APIキーの設定
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    
    st.write("現在、この環境で使用可能なモデル一覧を取得しています...")
    
    # モデル一覧を取得して表示
    available_models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            available_models.append(m.name)
            
    if available_models:
        st.success("✅ 以下のモデルが見つかりました！")
        for model_name in available_models:
            st.code(model_name)
        st.write("---")
        st.write("※この中にある名前（例: models/gemini-pro）を使えば確実に動きます。")
    else:
        st.error("❌ 使用可能なモデルが見つかりませんでした。APIキーや権限を確認してください。")

except Exception as e:
    st.error(f"診断エラー: {e}")
