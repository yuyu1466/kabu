# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import feedparser
import re
import time
from urllib.parse import quote
from collections import Counter

st.set_page_config(page_title="株価分析", page_icon="📈", layout="wide")
st.title("📈 日本株 分析ツール")

# ===================================================================
# 共通ヘルパー
# ===================================================================
@st.cache_data(ttl=900, show_spinner=False)
def fetch_stock_data(code, period="1y"):
    for attempt in range(3):
        try:
            ticker = yf.Ticker(f"{code}.T")
            df = ticker.history(period=period)
            info = {}
            try:
                info = ticker.info
            except Exception:
                pass
            if not df.empty:
                return df, info
        except Exception as e:
            if "rate" in str(e).lower() or "limit" in str(e).lower():
                time.sleep(2 + attempt * 2)
                continue
            else:
                break
    return pd.DataFrame(), {}

def find_resistance_levels(df, n_levels=3):
    highs = df['High'].values
    resistances = []
    for i in range(5, len(highs) - 5):
        if highs[i] == max(highs[i-5:i+6]):
            resistances.append((df.index[i], highs[i]))
    resistances.sort(key=lambda x: x[1], reverse=True)
    return resistances[:n_levels]

def calculate_sell_targets(df, info, price):
    targets = []
    high_20  = df['High'].tail(20).max()
    high_60  = df['High'].tail(60).max()
    high_52w = df['High'].max()
    resistances = find_resistance_levels(df, 3)
    recent_low  = df['Low'].tail(120).min()
    recent_high = df['High'].tail(120).max()
    fib_range = recent_high - recent_low
    fib_618 = recent_low + fib_range * 0.618
    fib_786 = recent_low + fib_range * 0.786
    fib_1272 = recent_low + fib_range * 1.272
    bb_mid = df['Close'].rolling(25).mean().iloc[-1]
    bb_std = df['Close'].rolling(25).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_upper_3 = bb_mid + 3 * bb_std
    ma25 = df['Close'].rolling(25).mean().iloc[-1]
    ma25_high = ma25 * 1.15
    eps = info.get('trailingEps')
    fair_price_per20 = eps * 20 if eps and eps > 0 else None

    candidates = []
    if price < high_20:
        candidates.append({'price': high_20, 'label': '20日高値', 'category': '近場の壁', 'desc': '直近1ヶ月の最高値'})
    if high_60 > high_20 and price < high_60:
        candidates.append({'price': high_60, 'label': '60日高値', 'category': '近場の壁', 'desc': '直近3ヶ月の最高値'})
    if price < fib_618:
        candidates.append({'price': fib_618, 'label': 'フィボ61.8%', 'category': '中期目標', 'desc': '黄金比の節目'})
    if price < fib_786 and fib_786 > fib_618:
        candidates.append({'price': fib_786, 'label': 'フィボ78.6%', 'category': '中期目標', 'desc': '強めの戻し目標'})
    if price < high_52w:
        candidates.append({'price': high_52w, 'label': '52週高値', 'category': '大きな壁', 'desc': '過去1年の最高値'})
    if price < fib_1272:
        candidates.append({'price': fib_1272, 'label': 'フィボ127.2%', 'category': '楽観シナリオ', 'desc': '52週高値突破時の目標'})
    if price < bb_upper:
        candidates.append({'price': bb_upper, 'label': 'BB+2σ', 'category': '過熱警戒', 'desc': '短期天井になりやすい'})
    if price < bb_upper_3:
        candidates.append({'price': bb_upper_3, 'label': 'BB+3σ', 'category': '過熱警戒', 'desc': '極端な過熱、調整必至'})
    if price < ma25_high:
        candidates.append({'price': ma25_high, 'label': '25日線+15%', 'category': '過熱警戒', 'desc': '移動平均から乖離過大'})
    if fair_price_per20 and price < fair_price_per20:
        candidates.append({'price': fair_price_per20, 'label': 'PER20倍水準', 'category': 'バリュエーション', 'desc': '一般的な割高ライン'})
    for i, (date, res_price) in enumerate(resistances):
        if price < res_price:
            candidates.append({'price': res_price, 'label': f'過去高値#{i+1}', 'category': '抵抗線',
                              'desc': f'{date.strftime("%Y-%m-%d")}の高値'})
    for c in candidates:
        c['distance_pct'] = (c['price'] / price - 1) * 100
    candidates.sort(key=lambda x: x['price'])
    return candidates

# ===================================================================
# サイドバー
# ===================================================================
mode = st.sidebar.radio("モード", [
    "🔍 個別銘柄分析",
    "🔥 注目銘柄を探す",
    "📰 ニュースで話題の銘柄",
])

# --- 詳細設定（折りたたみ）---
with st.sidebar.expander("⚙️ 詳細設定（上級者向け）", expanded=False):
    st.caption("デフォルトのままでもOKです")
    rsi_overbought = st.slider("RSI 買われすぎ閾値", 60, 90, 70)
    rsi_oversold   = st.slider("RSI 売られすぎ閾値", 10, 40, 30)
    vol_spike      = st.slider("出来高急増の判定倍率", 1.2, 3.0, 1.5, 0.1)
    hot_threshold_default = st.slider("注目度のデフォルト閾値", 1, 10, 4)
    show_ma75  = st.checkbox("75日移動平均を表示", value=True)
    show_ma200 = st.checkbox("200日移動平均を表示", value=False)
    show_bb    = st.checkbox("ボリンジャーバンドを表示", value=True)

# 設定を session_state に保存
st.session_state['rsi_overbought'] = rsi_overbought
st.session_state['rsi_oversold']   = rsi_oversold
st.session_state['vol_spike']      = vol_spike
st.session_state['show_ma75']      = show_ma75
st.session_state['show_ma200']     = show_ma200
st.session_state['show_bb']        = show_bb

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
# 個別銘柄分析
# ===================================================================
if mode == "🔍 個別銘柄分析":
    col1, col2 = st.columns([2, 1])
    with col1:
        code = st.text_input("銘柄コード（例: 7203）", "7203")
    with col2:
        period = st.selectbox("期間",
            [("3ヶ月", "3mo"), ("6ヶ月", "6mo"), ("1年", "1y"), ("2年", "2y"), ("5年", "5y")],
            index=2, format_func=lambda x: x[0])[1]

    analyze_clicked = st.button("📊 分析する", type="primary")

    # session_stateに結果を保存
    if analyze_clicked:
        with st.spinner("データ取得中..."):
            df, info = fetch_stock_data(code, period)
        if df.empty:
            st.error("⚠️ データが取得できませんでした。")
            st.info("銘柄コードを確認するか、10〜30分待って再試行してください。")
            st.stop()
        st.session_state['analyze_df'] = df
        st.session_state['analyze_info'] = info
        st.session_state['analyze_code'] = code

    # 保存された結果があれば表示
    if 'analyze_df' in st.session_state:
        df = st.session_state['analyze_df'].copy()
        info = st.session_state['analyze_info']
        code = st.session_state['analyze_code']

        # 指標計算
        df['MA5']   = df['Close'].rolling(5).mean()
        df['MA25']  = df['Close'].rolling(25).mean()
        df['MA75']  = df['Close'].rolling(75).mean()
        df['MA200'] = df['Close'].rolling(200).mean()
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        df['RSI'] = 100 - (100 / (1 + gain / loss))
        df['BB_mid']   = df['Close'].rolling(25).mean()
        df['BB_std']   = df['Close'].rolling(25).std()
        df['BB_upper'] = df['BB_mid'] + 2 * df['BB_std']
        df['BB_lower'] = df['BB_mid'] - 2 * df['BB_std']
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

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📊 チャート", "⚡ 短期判断", "🏛 長期判断", "🎯 売り目標", "🌐 外部情報"
        ])

        # ============ チャートタブ（大幅改善） ============
        with tab1:
            # チャート表示モード切替
            cc1, cc2 = st.columns([1, 1])
            with cc1:
                sub_indicator = st.radio("下部に表示する指標", ["RSI", "MACD", "出来高"], horizontal=True)
            with cc2:
                chart_period = st.radio("期間",
                    ["全期間", "直近3ヶ月", "直近1ヶ月", "直近2週間"], horizontal=True)

            # 期間でデータを絞る
            df_chart = df.copy()
            if chart_period == "直近3ヶ月":
                df_chart = df_chart.tail(60)
            elif chart_period == "直近1ヶ月":
                df_chart = df_chart.tail(20)
            elif chart_period == "直近2週間":
                df_chart = df_chart.tail(10)

            # メインチャート（大きく）+ サブ1つ
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.75, 0.25], vertical_spacing=0.03)

            # ローソク足
            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
                low=df_chart['Low'], close=df_chart['Close'], name="株価",
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
            ), row=1, col=1)

            # 移動平均（設定で表示切替）
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA25'],
                name="MA25", line=dict(color='orange', width=2)), row=1, col=1)
            if st.session_state.get('show_ma75'):
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA75'],
                    name="MA75", line=dict(color='purple', width=1.5)), row=1, col=1)
            if st.session_state.get('show_ma200'):
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA200'],
                    name="MA200", line=dict(color='gray', width=1.5)), row=1, col=1)
            if st.session_state.get('show_bb'):
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['BB_upper'],
                    name="BB上", line=dict(color='lightblue', dash='dot', width=1)), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['BB_lower'],
                    name="BB下", line=dict(color='lightblue', dash='dot', width=1),
                    fill='tonexty', fillcolor='rgba(173,216,230,0.1)'), row=1, col=1)

            # 売り目標ラインを重ねて表示
            targets = calculate_sell_targets(df, info, price)
            if targets:
                near_targets = [t for t in targets if t['distance_pct'] < 10]
                mid_targets  = [t for t in targets if 10 <= t['distance_pct'] < 25]
                if near_targets:
                    t = min(near_targets, key=lambda x: x['distance_pct'])
                    fig.add_hline(y=t['price'], line_dash="dash", line_color="green",
                                  annotation_text=f"🥉 {t['label']} {t['price']:,.0f}",
                                  annotation_position="right", row=1, col=1)
                if mid_targets:
                    t = min(mid_targets, key=lambda x: x['distance_pct'])
                    fig.add_hline(y=t['price'], line_dash="dash", line_color="orange",
                                  annotation_text=f"🥈 {t['label']} {t['price']:,.0f}",
                                  annotation_position="right", row=1, col=1)

            # サブ指標
            if sub_indicator == "RSI":
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['RSI'],
                    name="RSI", line=dict(color='blue', width=1.5)), row=2, col=1)
                fig.add_hline(y=st.session_state.get('rsi_overbought', 70),
                              line_dash="dash", line_color="red", row=2, col=1)
                fig.add_hline(y=st.session_state.get('rsi_oversold', 30),
                              line_dash="dash", line_color="green", row=2, col=1)
                fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
            elif sub_indicator == "MACD":
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MACD'],
                    name="MACD", line=dict(color='blue', width=1.5)), row=2, col=1)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MACD_signal'],
                    name="Signal", line=dict(color='red', width=1.5)), row=2, col=1)
                fig.update_yaxes(title_text="MACD", row=2, col=1)
            else:  # 出来高
                colors = ['#ef5350' if c >= o else '#26a69a'
                          for c, o in zip(df_chart['Close'], df_chart['Open'])]
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'],
                    name="出来高", marker_color=colors), row=2, col=1)
                fig.update_yaxes(title_text="出来高", row=2, col=1)

            fig.update_layout(
                height=750,  # 高さ大きく
                xaxis_rangeslider_visible=False,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(l=10, r=10, t=30, b=10),
                font=dict(size=11),
            )
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])  # 土日を詰める
            st.plotly_chart(fig, use_container_width=True)

            st.caption("💡 緑線=第1売り目標、橙線=第2売り目標。チャート上で目標位置が一目でわかります。")

        with tab2:
            score = 0; msgs = []
            rsi_high = st.session_state.get('rsi_overbought', 70)
            rsi_low  = st.session_state.get('rsi_oversold', 30)
            if latest['MA5'] > latest['MA25']:
                score += 1; msgs.append("✅ MA5 > MA25（短期上昇）")
            else:
                msgs.append("❌ MA5 < MA25（短期下落）")
            if latest['RSI'] < rsi_low:
                score += 1; msgs.append(f"✅ RSI={latest['RSI']:.1f}（売られすぎ＝買い）")
            elif latest['RSI'] > rsi_high:
                score -= 1; msgs.append(f"⚠️ RSI={latest['RSI']:.1f}（買われすぎ）")
            else:
                msgs.append(f"➖ RSI={latest['RSI']:.1f}（中立）")
            if latest['MACD'] > latest['MACD_signal']:
                score += 1; msgs.append("✅ MACD買い優勢")
            else:
                msgs.append("❌ MACD売り優勢")

            st.metric("短期スコア", f"{score} / 3")
            for m in msgs:
                st.write(m)
            st.info(f"💰 押し目買い目安（BB下限）: **{latest['BB_lower']:,.0f} 円** "
                    f"（現値比 {(latest['BB_lower']/price-1)*100:+.1f}%）")

        with tab3:
            score = 0; msgs = []
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
            if div:
                msgs.append(f"💰 配当利回り: {div*100:.2f}%")

            st.metric("長期スコア", f"{score} / 4")
            for m in msgs:
                st.write(m)
            low60 = df['Low'].tail(60).min()
            st.info(f"💰 長期買値目安（60日安値）: **{low60:,.0f} 円** "
                    f"（現値比 {(low60/price-1)*100:+.1f}%）")

        with tab4:
            st.subheader("🎯 売り目標価格の分析")
            st.caption("複数の手法で「売り圧力が出やすい価格帯」を算出します")
            targets = calculate_sell_targets(df, info, price)
            if not targets:
                st.warning("現在値が既に分析対象の上限を超えています。利確を検討するタイミングかも。")
            else:
                st.markdown("### 📌 利確の3段階プラン")
                near_targets = [t for t in targets if t['distance_pct'] < 10]
                mid_targets  = [t for t in targets if 10 <= t['distance_pct'] < 25]
                far_targets  = [t for t in targets if t['distance_pct'] >= 25]

                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.markdown("**🥉 第1目標**")
                    if near_targets:
                        t = min(near_targets, key=lambda x: x['distance_pct'])
                        st.metric(t['label'], f"{t['price']:,.0f} 円", f"{t['distance_pct']:+.1f}%")
                        st.caption(t['desc'])
                    else:
                        st.info("近場の目標なし")
                with cc2:
                    st.markdown("**🥈 第2目標**")
                    if mid_targets:
                        t = min(mid_targets, key=lambda x: x['distance_pct'])
                        st.metric(t['label'], f"{t['price']:,.0f} 円", f"{t['distance_pct']:+.1f}%")
                        st.caption(t['desc'])
                    else:
                        st.info("中距離の目標なし")
                with cc3:
                    st.markdown("**🥇 第3目標**")
                    if far_targets:
                        t = min(far_targets, key=lambda x: x['distance_pct'])
                        st.metric(t['label'], f"{t['price']:,.0f} 円", f"{t['distance_pct']:+.1f}%")
                        st.caption(t['desc'])
                    else:
                        st.info("遠距離の目標なし")

                warning_targets = [t for t in targets if t['category'] == '過熱警戒']
                if warning_targets:
                    st.markdown("### ⚠️ 警戒ライン")
                    nw = min(warning_targets, key=lambda x: x['distance_pct'])
                    st.error(f"**{nw['label']}: {nw['price']:,.0f} 円** ({nw['distance_pct']:+.1f}%) — {nw['desc']}")

                st.markdown("### 📋 全ての売り目標")
                df_t = pd.DataFrame([{
                    '価格': f"{t['price']:,.0f}", 'ラベル': t['label'],
                    '種別': t['category'], '距離': f"{t['distance_pct']:+.1f}%",
                    '説明': t['desc']} for t in targets])
                st.dataframe(df_t, use_container_width=True, hide_index=True)

                st.markdown("### 💡 おすすめ利確戦略")
                st.info(
                    "**分割利確が王道**：\n\n"
                    "・第1目標で **1/3を利確**\n"
                    "・第2目標で **さらに1/3を利確**\n"
                    "・残り 1/3 は **第3目標 or 警戒ライン**まで保有\n\n"
                    "全部を最高値で売るのは不可能。分割なら売り遅れリスクを大幅減。"
                )
                st.warning("⚠️ 過去データからの統計的な目安です。決算やニュースで簡単に突き抜けるので参考程度に。")

        with tab5:
            st.write("外部サイトで最新情報をチェック")
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.link_button("📋 Yahoo掲示板", f"https://finance.yahoo.co.jp/quote/{code}.T/bbs")
            with cc2:
                st.link_button("📰 株探", f"https://kabutan.jp/stock/?code={code}")
            with cc3:
                st.link_button("🐦 Xで検索", f"https://twitter.com/search?q={code}&f=live")

# ===================================================================
# 注目銘柄を探す（session_state対応）
# ===================================================================
elif mode == "🔥 注目銘柄を探す":
    st.write("📡 市場データから「今、買いが集まり始めている銘柄」を検知します。")

    col_a, col_b = st.columns(2)
    with col_a:
        threshold = st.slider("注目度の閾値", 1, 10, hot_threshold_default)
    with col_b:
        sort_mode = st.selectbox("並び順", ["注目度", "出来高急増率", "1週間リターン"])

    scan_clicked = st.button("🔥 注目銘柄を探す", type="primary")
    
    if scan_clicked:
        results = []
        errors = 0
        progress = st.progress(0)
        status = st.empty()
        total = len(NIKKEI_MAJOR)

        for i, (sc, name) in enumerate(NIKKEI_MAJOR.items(), 1):
            status.text(f"分析中 [{i}/{total}] {sc} {name}（エラー: {errors}）")
            progress.progress(i / total)
            df, info = fetch_stock_data(sc, "6mo")
            if df.empty or len(df) < 60:
                errors += 1; time.sleep(0.3); continue
            try:
                df['MA5']  = df['Close'].rolling(5).mean()
                df['MA25'] = df['Close'].rolling(25).mean()
                df['MA75'] = df['Close'].rolling(75).mean()
                hl = df['High'] - df['Low']
                hc = (df['High'] - df['Close'].shift()).abs()
                lc = (df['Low']  - df['Close'].shift()).abs()
                tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
                df['ATR'] = tr.rolling(14).mean()
                delta = df['Close'].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = -delta.where(delta < 0, 0).rolling(14).mean()
                df['RSI'] = 100 - (100 / (1 + gain / loss))
                latest = df.iloc[-1]; prev = df.iloc[-2]; price = latest['Close']
                score = 0; reasons = []

                vol_today_ratio = latest['Volume'] / df['Volume'].tail(25).mean()
                vol_5d_ratio    = df['Volume'].tail(5).mean() / df['Volume'].tail(25).mean()
                vs = st.session_state.get('vol_spike', 1.5)
                if vol_today_ratio > vs * 1.7:
                    score += 3; reasons.append(f"🔥出来高{vol_today_ratio:.1f}x")
                elif vol_today_ratio > vs * 1.2:
                    score += 2; reasons.append(f"🔥出来高{vol_today_ratio:.1f}x")
                elif vol_today_ratio > vs * 0.87:
                    score += 1; reasons.append(f"🔥出来高{vol_today_ratio:.1f}x")
                if vol_5d_ratio > vs:
                    score += 1; reasons.append(f"📊5日平均{vol_5d_ratio:.1f}x")

                today_range = latest['High'] - latest['Low']
                range_ratio = today_range / latest['ATR'] if latest['ATR'] > 0 else 1
                if range_ratio > 2.0:
                    score += 2; reasons.append(f"💥値幅{range_ratio:.1f}x")
                elif range_ratio > 1.5:
                    score += 1; reasons.append(f"💥値幅{range_ratio:.1f}x")

                ret_1w = (price / df['Close'].iloc[-5] - 1) * 100
                ret_1m = (price / df['Close'].iloc[-20] - 1) * 100
                if ret_1w > 10: score += 2; reasons.append(f"📈1週+{ret_1w:.1f}%")
                elif ret_1w > 5: score += 1; reasons.append(f"📈1週+{ret_1w:.1f}%")
                if ret_1m > 15: score += 1; reasons.append(f"📈1月+{ret_1m:.1f}%")

                high_20 = df['High'].iloc[-21:-1].max()
                if price > high_20:
                    score += 2; reasons.append("🚀20日高値更新")
                if prev['Close'] <= prev['MA25'] and price > latest['MA25']:
                    score += 1; reasons.append("✨25日線上抜け")

                high_52w = df['High'].max()
                dist_high = (price / high_52w - 1) * 100
                if dist_high > -3:
                    score += 1; reasons.append(f"🎯高値圏({dist_high:+.1f}%)")

                rsi_ob = st.session_state.get('rsi_overbought', 70)
                if latest['RSI'] > rsi_ob + 10:
                    score -= 2; reasons.append(f"⚠️RSI={latest['RSI']:.0f}過熱")
                elif latest['RSI'] > rsi_ob + 5:
                    score -= 1; reasons.append(f"⚠️RSI={latest['RSI']:.0f}やや過熱")

                results.append({
                    'コード': sc, '銘柄名': name, '現在値': f"{price:,.0f}",
                    '注目度': score, '出来高比': f"{vol_today_ratio:.1f}x",
                    '1週': f"{ret_1w:+.1f}%", '1月': f"{ret_1m:+.1f}%",
                    'RSI': f"{latest['RSI']:.0f}",
                    'シグナル': " / ".join(reasons) if reasons else "—",
                    '_vol': vol_today_ratio, '_ret1w': ret_1w,
                })
            except Exception:
                errors += 1; continue

        progress.empty(); status.empty()

        if not results:
            st.error("⚠️ データ取得失敗。10〜30分後に再試行してください。")
        else:
            st.session_state['scan_results'] = results
            st.session_state['scan_errors'] = errors

    # session_stateの結果を表示（並び順変更でも消えない）
    if 'scan_results' in st.session_state:
        results = st.session_state['scan_results']
        errors = st.session_state.get('scan_errors', 0)
        if errors > 0:
            st.warning(f"ℹ️ {errors}銘柄取得失敗（{len(results)}銘柄で表示）")

        df_result = pd.DataFrame(results)
        if sort_mode == "注目度":
            df_result = df_result.sort_values('注目度', ascending=False)
        elif sort_mode == "出来高急増率":
            df_result = df_result.sort_values('_vol', ascending=False)
        else:
            df_result = df_result.sort_values('_ret1w', ascending=False)
        df_result = df_result.drop(columns=['_vol', '_ret1w']).reset_index(drop=True)
        hot = df_result[df_result['注目度'] >= threshold]

        st.success(f"✅ {len(hot)}銘柄が注目度 {threshold} 以上に該当")

        if len(hot) > 0:
            st.dataframe(hot, use_container_width=True, hide_index=True)
            st.markdown("### 🌐 上位銘柄の詳細")
            for _, row in hot.head(3).iterrows():
                c = row['コード']
                with st.expander(f"{c} {row['銘柄名']} （注目度 {row['注目度']}）"):
                    cc1, cc2, cc3 = st.columns(3)
                    with cc1:
                        st.link_button("📋 掲示板", f"https://finance.yahoo.co.jp/quote/{c}.T/bbs")
                    with cc2:
                        st.link_button("📰 株探", f"https://kabutan.jp/stock/?code={c}")
                    with cc3:
                        st.link_button("🐦 X", f"https://twitter.com/search?q={c}&f=live")
                    st.write(f"**シグナル**: {row['シグナル']}")
        else:
            st.warning("該当なし。閾値を下げてください。")
            st.write("### 参考：上位10銘柄")
            st.dataframe(df_result.head(10), use_container_width=True, hide_index=True)

# ===================================================================
# ニュースで話題の銘柄（session_state対応）
# ===================================================================
else:
    st.write("📰 Googleニュースから「今ニュースで話題の銘柄」を抽出します。")

    news_clicked = st.button("📰 話題の銘柄を集める", type="primary")
    
    if news_clicked:
        queries = ["株価 急騰", "ストップ高", "上方修正", "決算 サプライズ", "材料株", "新高値", "業績 好調"]
        code_counts = Counter()
        code_articles = {}
        progress = st.progress(0)
        status = st.empty()

        for idx, q in enumerate(queries, 1):
            status.text(f"ニュース取得中 [{idx}/{len(queries)}] 「{q}」")
            progress.progress(idx / len(queries))
            try:
                url = f"https://news.google.com/rss/search?q={quote(q)}&hl=ja&gl=JP&ceid=JP:ja"
                feed = feedparser.parse(url)
                for entry in feed.entries[:30]:
                    title = entry.title
                    codes = re.findall(r'[<\(（【「\s](\d{4})[>\)）】」\s]', title)
                    for c in set(codes):
                        if 1000 <= int(c) <= 9999:
                            code_counts[c] += 1
                            if c not in code_articles:
                                code_articles[c] = []
                            if len(code_articles[c]) < 5:
                                code_articles[c].append({'title': title, 'link': entry.link})
            except Exception:
                continue

        progress.empty(); status.empty()

        if not code_counts:
            st.warning("銘柄コードを抽出できませんでした。")
        else:
            status2 = st.empty()
            status2.text("市場データと突き合わせ中...")
            top_codes = [c for c, _ in code_counts.most_common(15)]
            enriched = []
            for c in top_codes:
                df, info = fetch_stock_data(c, "3mo")
                if df.empty or len(df) < 25:
                    enriched.append({
                        'コード': c, '銘柄名': c, '現在値': '—',
                        '言及数': code_counts[c], '出来高比': '—',
                        '当日': '—', '1週': '—', '話題度': code_counts[c],
                    })
                    time.sleep(0.3); continue
                try:
                    latest = df.iloc[-1]; price = latest['Close']
                    vol_ratio = latest['Volume'] / df['Volume'].tail(25).mean()
                    ret_1w = (price / df['Close'].iloc[-5] - 1) * 100 if len(df) >= 5 else 0
                    ret_1d = (price / df['Close'].iloc[-2] - 1) * 100 if len(df) >= 2 else 0
                    hot_score = code_counts[c]
                    if vol_ratio > 1.5: hot_score += 2
                    elif vol_ratio > 1.2: hot_score += 1
                    if ret_1w > 5: hot_score += 1
                    if ret_1d > 3: hot_score += 1
                    name = info.get('longName', c)
                    if len(name) > 15: name = name[:15] + "…"
                    enriched.append({
                        'コード': c, '銘柄名': name, '現在値': f"{price:,.0f}",
                        '言及数': code_counts[c], '出来高比': f"{vol_ratio:.1f}x",
                        '当日': f"{ret_1d:+.1f}%", '1週': f"{ret_1w:+.1f}%",
                        '話題度': hot_score,
                    })
                except Exception:
                    continue
            status2.empty()
            st.session_state['news_results'] = enriched
            st.session_state['news_articles'] = code_articles

    # session_state結果表示
    if 'news_results' in st.session_state:
        enriched = st.session_state['news_results']
        code_articles = st.session_state['news_articles']
        df_news = pd.DataFrame(enriched).sort_values('話題度', ascending=False).reset_index(drop=True)
        st.success(f"✅ {len(df_news)}銘柄を表示")
        st.dataframe(df_news, use_container_width=True, hide_index=True)

        st.markdown("### 📑 上位銘柄のニュース見出し")
        for _, row in df_news.head(5).iterrows():
            c = row['コード']
            with st.expander(f"📌 {c} {row['銘柄名']} （話題度 {row['話題度']} / 言及 {row['言及数']}件）"):
                articles = code_articles.get(c, [])
                if articles:
                    for a in articles:
                        st.markdown(f"- [{a['title']}]({a['link']})")
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.link_button("📊 株探", f"https://kabutan.jp/stock/?code={c}")
                with cc2:
                    st.link_button("📋 掲示板", f"https://finance.yahoo.co.jp/quote/{c}.T/bbs")
                with cc3:
                    st.link_button("🐦 X", f"https://twitter.com/search?q={c}&f=live")

st.sidebar.markdown("---")
st.sidebar.caption("⚠️ 投資判断の参考情報です。利益保証なし。投資は自己責任で。")
