# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="株価分析", page_icon="📈", layout="wide")
st.title("📈 日本株 分析ツール")

# === サイドバー：モード選択 ===
mode = st.sidebar.radio("モード", ["🔍 個別銘柄分析", "🔥 熱い銘柄ランキング"])

# === 主要銘柄リスト ===
NIKKEI_MAJOR = {
    "7203": "トヨタ自動車", "6758": "ソニーG", "9984": "ソフトバンクG",
    "7974": "任天堂", "8306": "三菱UFJ", "8316": "三井住友FG",
    "8411": "みずほFG", "9433": "KDDI", "9432": "NTT",
    "9983": "ファーストリテイリング", "6861": "キーエンス", "4063": "信越化学",
    "6098": "リクルート", "9022": "JR東海", "8001": "伊藤忠商事",
    "8058": "三菱商事", "8053": "住友商事", "8031": "三井物産",
    "7267": "ホンダ", "6501": "日立製作所", "6503": "三菱電機",
    "6902": "デンソー", "4502": "武田薬品", "4503": "アステラス製薬",
    "4452": "花王", "2914": "JT", "4661": "オリエンタルランド",
    "9020": "JR東日本", "9101": "日本郵船", "5401": "日本製鉄",
    "1605": "INPEX", "6981": "村田製作所", "6594": "ニデック",
    "7741": "HOYA", "4543": "テルモ", "6273": "SMC",
}

# ===================================================================
# 個別銘柄分析モード
# ===================================================================
if mode == "🔍 個別銘柄分析":
    col1, col2 = st.columns([2, 1])
    with col1:
        code = st.text_input("銘柄コード（例: 7203）", "7203")
    with col2:
        period = st.selectbox("期間", 
            [("3ヶ月","3mo"),("6ヶ月","6mo"),("1年","1y"),("2年","2y"),("5年","5y")],
            index=2, format_func=lambda x: x[0])[1]

    if st.button("📊 分析する", type="primary"):
        with st.spinner("データ取得中..."):
            ticker = yf.Ticker(f"{code}.T")
            df = ticker.history(period=period)
            info = ticker.info

        if df.empty:
            st.error("データが取得できませんでした。銘柄コードを確認してください。")
            st.stop()

        # 指標計算
        df['MA5']   = df['Close'].rolling(5).mean()
        df['MA25']  = df['Close'].rolling(25).mean()
        df['MA75']  = df['Close'].rolling(75).mean()
        df['MA200'] = df['Close'].rolling(200).mean()
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        df['RSI'] = 100 - (100 / (1 + gain/loss))
        df['BB_mid']   = df['Close'].rolling(25).mean()
        df['BB_std']   = df['Close'].rolling(25).std()
        df['BB_upper'] = df['BB_mid'] + 2*df['BB_std']
        df['BB_lower'] = df['BB_mid'] - 2*df['BB_std']
        ema12 = df['Close'].ewm(span=12).mean()
        ema26 = df['Close'].ewm(span=26).mean()
        df['MACD']        = ema12 - ema26
        df['MACD_signal'] = df['MACD'].ewm(span=9).mean()

        latest = df.iloc[-1]
        price  = latest['Close']

        st.subheader(f"{info.get('longName', code)} ({code}.T)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現在値", f"{price:,.0f} 円")
        c2.metric("PER", f"{info.get('trailingPE'):.1f}" if info.get('trailingPE') else "—")
        c3.metric("PBR", f"{info.get('priceToBook'):.2f}" if info.get('priceToBook') else "—")
        c4.metric("RSI", f"{latest['RSI']:.1f}")

        tab1, tab2, tab3 = st.tabs(["📊 チャート", "⚡ 短期判断", "🏛 長期判断"])

        with tab1:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'],
                                         low=df['Low'], close=df['Close'], name="株価"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA25'], name="MA25", line=dict(color='orange')), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA75'], name="MA75", line=dict(color='purple')), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_upper'], name="BB上", line=dict(color='gray', dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['BB_lower'], name="BB下", line=dict(color='gray', dash='dot')), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], name="RSI", line=dict(color='blue')), row=2, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], name="MACD", line=dict(color='blue')), row=3, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD_signal'], name="Signal", line=dict(color='red')), row=3, col=1)
            fig.update_layout(height=700, xaxis_rangeslider_visible=False, showlegend=True)
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            score = 0
            msgs = []
            if latest['MA5'] > latest['MA25']:
                score += 1; msgs.append("✅ MA5 > MA25（短期上昇）")
            else:
                msgs.append("❌ MA5 < MA25（短期下落）")
            if latest['RSI'] < 30:
                score += 1; msgs.append(f"✅ RSI={latest['RSI']:.1f}（売られすぎ＝買い）")
            elif latest['RSI'] > 70:
                score -= 1; msgs.append(f"⚠️ RSI={latest['RSI']:.1f}（買われすぎ）")
            else:
                msgs.append(f"➖ RSI={latest['RSI']:.1f}（中立）")
            if latest['MACD'] > latest['MACD_signal']:
                score += 1; msgs.append("✅ MACD買い優勢")
            else:
                msgs.append("❌ MACD売り優勢")

            st.metric("短期スコア", f"{score} / 3")
            for m in msgs: st.write(m)
            st.info(f"💰 押し目買い目安（BB下限）: **{latest['BB_lower']:,.0f} 円** "
                    f"（現値比 {(latest['BB_lower']/price-1)*100:+.1f}%）")

        with tab3:
            score = 0
            msgs = []
            per = info.get('trailingPE'); pbr = info.get('priceToBook')
            roe = info.get('returnOnEquity'); div = info.get('dividendYield')
            if per and per < 15:
                score += 1; msgs.append(f"✅ PER={per:.1f}（割安）")
            elif per:
                msgs.append(f"➖ PER={per:.1f}")
            if pbr and pbr < 1.5:
                score += 1; msgs.append(f"✅ PBR={pbr:.2f}（割安）")
            elif pbr:
                msgs.append(f"➖ PBR={pbr:.2f}")
            if roe and roe > 0.1:
                score += 1; msgs.append(f"✅ ROE={roe*100:.1f}%（収益性良好）")
            if pd.notna(latest['MA200']) and price > latest['MA200']:
                score += 1; msgs.append("✅ 200日線より上（長期上昇）")
            if div: msgs.append(f"💰 配当利回り: {div*100:.2f}%")

            st.metric("長期スコア", f"{score} / 4")
            for m in msgs: st.write(m)
            low60 = df['Low'].tail(60).min()
            st.info(f"💰 長期買値目安（60日安値）: **{low60:,.0f} 円** "
                    f"（現値比 {(low60/price-1)*100:+.1f}%）")

# ===================================================================
# 熱い銘柄ランキングモード
# ===================================================================
else:
    st.write("主要40銘柄をスキャンして、勢いのある銘柄をランキング表示します。")
    threshold = st.slider("熱さ閾値（高いほど厳しい）", 1, 7, 3)
    
    if st.button("🔥 熱い銘柄を探す", type="primary"):
        results = []
        progress = st.progress(0)
        status = st.empty()
        total = len(NIKKEI_MAJOR)
        
        for i, (code, name) in enumerate(NIKKEI_MAJOR.items(), 1):
            status.text(f"分析中 [{i}/{total}] {code} {name}")
            progress.progress(i / total)
            try:
                ticker = yf.Ticker(f"{code}.T")
                df = ticker.history(period="6mo")
                info = ticker.info
                if df.empty or len(df) < 60: continue
                
                df['MA5']  = df['Close'].rolling(5).mean()
                df['MA25'] = df['Close'].rolling(25).mean()
                df['MA75'] = df['Close'].rolling(75).mean()
                delta = df['Close'].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = -delta.where(delta < 0, 0).rolling(14).mean()
                df['RSI'] = 100 - (100 / (1 + gain/loss))
                latest = df.iloc[-1]
                price = latest['Close']
                
                score = 0; reasons = []
                ret_1m = (price / df['Close'].iloc[-20] - 1) * 100
                if ret_1m > 10: score += 2; reasons.append(f"📈+{ret_1m:.1f}%")
                elif ret_1m > 5: score += 1; reasons.append(f"📈+{ret_1m:.1f}%")
                
                vol_ratio = df['Volume'].tail(5).mean() / df['Volume'].tail(25).mean()
                if vol_ratio > 1.5: score += 2; reasons.append(f"🔥{vol_ratio:.1f}x")
                elif vol_ratio > 1.2: score += 1; reasons.append(f"🔥{vol_ratio:.1f}x")
                
                if latest['MA5'] > latest['MA25'] > latest['MA75']:
                    score += 2; reasons.append("✨完全上昇配列")
                elif latest['MA5'] > latest['MA25']:
                    score += 1; reasons.append("↗️短期上昇")
                
                high_52w = df['High'].max()
                if price / high_52w > 0.95:
                    score += 1; reasons.append("🎯高値圏")
                
                if latest['RSI'] > 75:
                    score -= 1; reasons.append(f"⚠️RSI{latest['RSI']:.0f}")
                
                per = info.get('trailingPE')
                if per and per < 15 and ret_1m > 0:
                    score += 1; reasons.append(f"💎PER{per:.1f}")
                
                results.append({
                    'コード': code, '銘柄名': name,
                    '現在値': f"{price:,.0f}",
                    '1ヶ月': f"{ret_1m:+.1f}%",
                    '出来高比': f"{vol_ratio:.1f}x",
                    'RSI': f"{latest['RSI']:.0f}",
                    'PER': f"{per:.1f}" if per else "—",
                    '熱さ': score,
                    '理由': " / ".join(reasons) if reasons else "—"
                })
            except: continue
        
        progress.empty(); status.empty()
        
        df_result = pd.DataFrame(results).sort_values('熱さ', ascending=False).reset_index(drop=True)
        hot = df_result[df_result['熱さ'] >= threshold]
        
        st.success(f"✅ {len(hot)}銘柄が熱さ {threshold} 以上に該当しました")
        if len(hot) > 0:
            st.dataframe(hot, use_container_width=True, hide_index=True)
        else:
            st.warning("該当なし。閾値を下げてみてください。")
            st.write("参考：全銘柄の上位10")
            st.dataframe(df_result.head(10), use_container_width=True, hide_index=True)

st.sidebar.markdown("---")
st.sidebar.caption("⚠️ このツールは投資判断の参考情報を提供するもので、利益を保証するものではありません。投資は自己責任でお願いします。")
