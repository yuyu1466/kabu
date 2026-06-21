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
# 銘柄一覧をJPXから動的取得（24時間キャッシュ）
# ===================================================================
@st.cache_data(ttl=86400, show_spinner=False)  # 24時間キャッシュ
def load_stock_list():
    """JPXから全上場銘柄リストを取得"""
    try:
        url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
        df = pd.read_excel(url)
        # 列名は「コード」「銘柄名」「市場・商品区分」「33業種区分」など
        # ETF・REITは除外して、通常の株式のみに絞る
        df = df[df['市場・商品区分'].str.contains('内国株式', na=False)]
        # コードを文字列に統一
        df['コード'] = df['コード'].astype(str).str.zfill(4)
        return df[['コード', '銘柄名', '市場・商品区分', '33業種区分']].reset_index(drop=True)
    except Exception as e:
        st.error(f"銘柄一覧の取得に失敗しました: {e}")
        return pd.DataFrame(columns=['コード', '銘柄名', '市場・商品区分', '33業種区分'])

# 銘柄一覧をロード
with st.spinner("銘柄リスト読込中..."):
    STOCK_LIST = load_stock_list()

if STOCK_LIST.empty:
    st.warning("⚠️ 銘柄一覧が取得できませんでした。手動で銘柄コード（4桁）を入力してください。")
    STOCK_DICT = {}
else:
    STOCK_DICT = dict(zip(STOCK_LIST['コード'], STOCK_LIST['銘柄名']))

# 注目銘柄スキャン用の主要銘柄（プライム市場の代表）
NIKKEI_MAJOR_CODES = [
    "7203", "6758", "9984", "7974", "8306", "8316", "8411", "9433", "9432",
    "9983", "6861", "4063", "6098", "9022", "8001", "8058", "8053", "8031",
    "7267", "6501", "6503", "6902", "4502", "4503", "4452", "2914", "4661",
    "9020", "9101", "5401", "1605", "6981", "6594", "7741", "4543", "6273",
    "8035", "6920", "6857", "4519",
]
NIKKEI_MAJOR = {c: STOCK_DICT.get(c, c) for c in NIKKEI_MAJOR_CODES if c in STOCK_DICT or True}

# ===================================================================
# ヘルパー関数
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

def search_stock(query):
    """銘柄コードまたは名前で検索"""
    query = query.strip()
    if not query:
        return []
    if query.isdigit():
        if query in STOCK_DICT:
            return [(query, STOCK_DICT[query])]
        if len(query) == 4:
            return [(query, "（一覧未登録だが試行可能）")]
        return []
    # 文字検索（部分一致）
    matches = []
    q_lower = query.lower()
    for code, name in STOCK_DICT.items():
        if query in name or q_lower in name.lower():
            matches.append((code, name))
    return matches[:15]  # 最大15件

def find_resistance_levels(df, n_levels=3):
    highs = df['High'].values
    resistances = []
    for i in range(5, len(highs) - 5):
        if highs[i] == max(highs[i-5:i+6]):
            resistances.append((df.index[i], highs[i]))
    resistances.sort(key=lambda x: x[1], reverse=True)
    return resistances[:n_levels]

def find_support_levels(df, n_levels=3):
    lows = df['Low'].values
    supports = []
    for i in range(5, len(lows) - 5):
        if lows[i] == min(lows[i-5:i+6]):
            supports.append((df.index[i], lows[i]))
    supports.sort(key=lambda x: x[1], reverse=True)
    return supports[:n_levels]

def calculate_sell_targets(df, info, price):
    targets = []
    high_20 = df['High'].tail(20).max()
    high_60 = df['High'].tail(60).max()
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
        candidates.append({'price': bb_upper_3, 'label': 'BB+3σ', 'category': '過熱警戒', 'desc': '極端な過熱'})
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

def calculate_stop_loss(df, info, price):
    candidates = []
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low']  - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    atr_stop_15 = price - atr * 1.5
    atr_stop_2  = price - atr * 2.0
    if atr_stop_15 < price:
        candidates.append({'price': atr_stop_15, 'label': 'ATR×1.5', 'category': '逃げ場（標準）',
                          'desc': '普段の値動き1.5倍下', 'urgency': '中'})
    if atr_stop_2 < price:
        candidates.append({'price': atr_stop_2, 'label': 'ATR×2.0', 'category': '逃げ場（余裕）',
                          'desc': '普段の値動き2倍下', 'urgency': '中'})
    ma25 = df['Close'].rolling(25).mean().iloc[-1]
    ma75 = df['Close'].rolling(75).mean().iloc[-1]
    ma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) >= 200 else None
    if pd.notna(ma25) and ma25 < price:
        candidates.append({'price': ma25, 'label': '25日線', 'category': 'トレンド転換',
                          'desc': '短期トレンドの分岐点', 'urgency': '高'})
    if pd.notna(ma75) and ma75 < price:
        candidates.append({'price': ma75, 'label': '75日線', 'category': 'トレンド転換',
                          'desc': '中期トレンドの分岐点', 'urgency': '高'})
    if ma200 and pd.notna(ma200) and ma200 < price:
        candidates.append({'price': ma200, 'label': '200日線', 'category': 'トレンド転換',
                          'desc': '長期トレンドの分岐点', 'urgency': '最高'})
    supports = find_support_levels(df, 3)
    for i, (date, sup_price) in enumerate(supports):
        if sup_price < price:
            candidates.append({'price': sup_price, 'label': f'過去安値#{i+1}', 'category': 'サポート',
                              'desc': f'{date.strftime("%Y-%m-%d")}の安値', 'urgency': '中'})
    bb_mid = df['Close'].rolling(25).mean().iloc[-1]
    bb_std = df['Close'].rolling(25).std().iloc[-1]
    bb_lower = bb_mid - 2 * bb_std
    if bb_lower < price:
        candidates.append({'price': bb_lower, 'label': 'BB-2σ', 'category': 'ボラ下限',
                          'desc': '統計的下限', 'urgency': '低'})
    low_20 = df['Low'].tail(20).min()
    low_60 = df['Low'].tail(60).min()
    if low_20 < price:
        candidates.append({'price': low_20, 'label': '20日安値', 'category': 'サポート',
                          'desc': '直近1ヶ月の最安値', 'urgency': '高'})
    if low_60 < low_20 and low_60 < price:
        candidates.append({'price': low_60, 'label': '60日安値', 'category': 'サポート',
                          'desc': '直近3ヶ月の最安値', 'urgency': '高'})
    candidates.append({'price': price * 0.95, 'label': '-5%（タイト）', 'category': '機械的損切り',
                      'desc': '短期トレード向け', 'urgency': '中'})
    candidates.append({'price': price * 0.92, 'label': '-8%（標準）', 'category': '機械的損切り',
                      'desc': '一般的な損切り幅', 'urgency': '中'})
    candidates.append({'price': price * 0.90, 'label': '-10%（余裕）', 'category': '機械的損切り',
                      'desc': '中長期投資向け', 'urgency': '低'})
    for c in candidates:
        c['distance_pct'] = (c['price'] / price - 1) * 100
    candidates.sort(key=lambda x: x['price'], reverse=True)
    return candidates

# ===================================================================
# サイドバー
# ===================================================================
mode = st.sidebar.radio("モード", [
    "🔍 個別銘柄分析",
    "🔥 注目銘柄を探す",
    "📰 ニュースで話題の銘柄",
])

st.sidebar.markdown(f"📚 登録銘柄数: **{len(STOCK_DICT):,}社**")
st.sidebar.caption("（JPX公式データから自動取得）")

with st.sidebar.expander("⚙️ 詳細設定（上級者向け）", expanded=False):
    rsi_overbought = st.slider("RSI 買われすぎ閾値", 60, 90, 70)
    rsi_oversold   = st.slider("RSI 売られすぎ閾値", 10, 40, 30)
    vol_spike      = st.slider("出来高急増の判定倍率", 1.2, 3.0, 1.5, 0.1)
    hot_threshold_default = st.slider("注目度のデフォルト閾値", 1, 10, 4)
    show_ma75  = st.checkbox("75日移動平均を表示", value=True)
    show_ma200 = st.checkbox("200日移動平均を表示", value=False)
    show_bb    = st.checkbox("ボリンジャーバンドを表示", value=True)

st.session_state['rsi_overbought'] = rsi_overbought
st.session_state['rsi_oversold']   = rsi_oversold
st.session_state['vol_spike']      = vol_spike
st.session_state['show_ma75']      = show_ma75
st.session_state['show_ma200']     = show_ma200
st.session_state['show_bb']        = show_bb

# ===================================================================
# 個別銘柄分析
# ===================================================================
if mode == "🔍 個別銘柄分析":
    st.markdown("### 🔎 銘柄を検索")
    st.caption(f"全{len(STOCK_DICT):,}銘柄から、コードまたは社名（部分一致OK）で検索できます")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        query = st.text_input("銘柄コード or 社名", "7203")
    with col2:
        period = st.selectbox("期間",
            [("3ヶ月", "3mo"), ("6ヶ月", "6mo"), ("1年", "1y"), ("2年", "2y"), ("5年", "5y")],
            index=2, format_func=lambda x: x[0])[1]

    matches = search_stock(query)
    selected_code = None
    if not matches:
        st.warning("該当銘柄なし。コード（4桁）か社名の一部を入力してください。")
    elif len(matches) == 1:
        selected_code = matches[0][0]
        st.info(f"📌 **{matches[0][0]}** {matches[0][1]}")
    else:
        options = [f"{c} - {n}" for c, n in matches]
        chosen = st.selectbox(f"候補 {len(matches)} 件。選択してください", options)
        selected_code = chosen.split(" - ")[0]

    analyze_clicked = st.button("📊 分析する", type="primary", disabled=(selected_code is None))

    if analyze_clicked and selected_code:
        with st.spinner("データ取得中..."):
            df, info = fetch_stock_data(selected_code, period)
        if df.empty:
            st.error("⚠️ データ取得失敗。10〜30分後に再試行を。")
            st.stop()
        st.session_state['analyze_df'] = df
        st.session_state['analyze_info'] = info
        st.session_state['analyze_code'] = selected_code

    if 'analyze_df' in st.session_state:
        df = st.session_state['analyze_df'].copy()
        info = st.session_state['analyze_info']
        code = st.session_state['analyze_code']

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

        display_name = info.get('longName', STOCK_DICT.get(code, code))
        st.subheader(f"{display_name} ({code}.T)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現在値", f"{price:,.0f} 円")
        c2.metric("PER", f"{info.get('trailingPE'):.1f}" if info.get('trailingPE') else "—")
        c3.metric("PBR", f"{info.get('priceToBook'):.2f}" if info.get('priceToBook') else "—")
        c4.metric("RSI", f"{latest['RSI']:.1f}")

        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📊 チャート", "⚡ 短期判断", "🏛 長期判断",
            "🎯 売り目標", "🛡 損切りライン", "🌐 外部情報"
        ])

        with tab1:
            cc1, cc2 = st.columns([1, 1])
            with cc1:
                sub_indicator = st.radio("下部指標", ["RSI", "MACD", "出来高"], horizontal=True)
            with cc2:
                chart_period = st.radio("期間",
                    ["全期間", "直近3ヶ月", "直近1ヶ月", "直近2週間"], horizontal=True)
            df_chart = df.copy()
            if chart_period == "直近3ヶ月":
                df_chart = df_chart.tail(60)
            elif chart_period == "直近1ヶ月":
                df_chart = df_chart.tail(20)
            elif chart_period == "直近2週間":
                df_chart = df_chart.tail(10)

            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                row_heights=[0.75, 0.25], vertical_spacing=0.03)
            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
                low=df_chart['Low'], close=df_chart['Close'], name="株価",
                increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
            ), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA25'],
                name="MA25", line=dict(color='orange', width=2)), row=1, col=1)
            if show_ma75:
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA75'],
                    name="MA75", line=dict(color='purple', width=1.5)), row=1, col=1)
            if show_ma200:
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA200'],
                    name="MA200", line=dict(color='gray', width=1.5)), row=1, col=1)
            if show_bb:
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['BB_upper'],
                    name="BB上", line=dict(color='lightblue', dash='dot', width=1)), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['BB_lower'],
                    name="BB下", line=dict(color='lightblue', dash='dot', width=1),
                    fill='tonexty', fillcolor='rgba(173,216,230,0.1)'), row=1, col=1)

            targets = calculate_sell_targets(df, info, price)
            if targets:
                near = [t for t in targets if t['distance_pct'] < 10]
                mid  = [t for t in targets if 10 <= t['distance_pct'] < 25]
                if near:
                    t = min(near, key=lambda x: x['distance_pct'])
                    fig.add_hline(y=t['price'], line_dash="dash", line_color="green",
                                  annotation_text=f"🥉売り1 {t['price']:,.0f}",
                                  annotation_position="right", row=1, col=1)
                if mid:
                    t = min(mid, key=lambda x: x['distance_pct'])
                    fig.add_hline(y=t['price'], line_dash="dash", line_color="orange",
                                  annotation_text=f"🥈売り2 {t['price']:,.0f}",
                                  annotation_position="right", row=1, col=1)

            stops = calculate_stop_loss(df, info, price)
            if stops:
                nearest = max([s for s in stops if s['distance_pct'] > -10],
                              key=lambda x: x['distance_pct'], default=None)
                if nearest:
                    fig.add_hline(y=nearest['price'], line_dash="dash", line_color="red",
                                  annotation_text=f"🛡損切り {nearest['price']:,.0f}",
                                  annotation_position="right", row=1, col=1)

            if sub_indicator == "RSI":
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['RSI'],
                    name="RSI", line=dict(color='blue', width=1.5)), row=2, col=1)
                fig.add_hline(y=rsi_overbought, line_dash="dash", line_color="red", row=2, col=1)
                fig.add_hline(y=rsi_oversold, line_dash="dash", line_color="green", row=2, col=1)
                fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)
            elif sub_indicator == "MACD":
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MACD'],
                    name="MACD", line=dict(color='blue', width=1.5)), row=2, col=1)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MACD_signal'],
                    name="Signal", line=dict(color='red', width=1.5)), row=2, col=1)
                fig.update_yaxes(title_text="MACD", row=2, col=1)
            else:
                colors = ['#ef5350' if c >= o else '#26a69a'
                          for c, o in zip(df_chart['Close'], df_chart['Open'])]
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'],
                    name="出来高", marker_color=colors), row=2, col=1)
                fig.update_yaxes(title_text="出来高", row=2, col=1)

            fig.update_layout(
                height=750, xaxis_rangeslider_visible=False, showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(l=10, r=10, t=30, b=10), font=dict(size=11),
            )
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
            st.plotly_chart(fig, use_container_width=True)
            st.caption("🟢=売り第1目標, 🟠=売り第2目標, 🔴=損切りライン")

        with tab2:
            score = 0; msgs = []
            if latest['MA5'] > latest['MA25']:
                score += 1; msgs.append("✅ MA5 > MA25（短期上昇）")
            else:
                msgs.append("❌ MA5 < MA25（短期下落）")
            if latest['RSI'] < rsi_oversold:
                score += 1; msgs.append(f"✅ RSI={latest['RSI']:.1f}（売られすぎ）")
            elif latest['RSI'] > rsi_overbought:
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
            st.info(f"💰 押し目買い目安: **{latest['BB_lower']:,.0f} 円** ({(latest['BB_lower']/price-1)*100:+.1f}%）")

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
                score += 1; msgs.append(f"✅ ROE={roe*100:.1f}%（良好）")
            if pd.notna(latest['MA200']) and price > latest['MA200']:
                score += 1; msgs.append("✅ 200日線より上（長期上昇）")
            if div:
                msgs.append(f"💰 配当: {div*100:.2f}%")
            st.metric("長期スコア", f"{score} / 4")
            for m in msgs:
                st.write(m)
            low60 = df['Low'].tail(60).min()
            st.info(f"💰 長期買値目安: **{low60:,.0f} 円** ({(low60/price-1)*100:+.1f}%）")

        with tab4:
            st.subheader("🎯 売り目標価格")
            targets = calculate_sell_targets(df, info, price)
            if not targets:
                st.warning("利確検討タイミング")
            else:
                near = [t for t in targets if t['distance_pct'] < 10]
                mid  = [t for t in targets if 10 <= t['distance_pct'] < 25]
                far  = [t for t in targets if t['distance_pct'] >= 25]
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.markdown("**🥉 第1目標**")
                    if near:
                        t = min(near, key=lambda x: x['distance_pct'])
                        st.metric(t['label'], f"{t['price']:,.0f} 円", f"{t['distance_pct']:+.1f}%")
                        st.caption(t['desc'])
                with cc2:
                    st.markdown("**🥈 第2目標**")
                    if mid:
                        t = min(mid, key=lambda x: x['distance_pct'])
                        st.metric(t['label'], f"{t['price']:,.0f} 円", f"{t['distance_pct']:+.1f}%")
                        st.caption(t['desc'])
                with cc3:
                    st.markdown("**🥇 第3目標**")
                    if far:
                        t = min(far, key=lambda x: x['distance_pct'])
                        st.metric(t['label'], f"{t['price']:,.0f} 円", f"{t['distance_pct']:+.1f}%")
                        st.caption(t['desc'])
                warn = [t for t in targets if t['category'] == '過熱警戒']
                if warn:
                    nw = min(warn, key=lambda x: x['distance_pct'])
                    st.error(f"⚠️ {nw['label']}: {nw['price']:,.0f} 円 ({nw['distance_pct']:+.1f}%)")
                df_t = pd.DataFrame([{'価格': f"{t['price']:,.0f}", 'ラベル': t['label'],
                    '種別': t['category'], '距離': f"{t['distance_pct']:+.1f}%",
                    '説明': t['desc']} for t in targets])
                st.dataframe(df_t, use_container_width=True, hide_index=True)

        with tab5:
            st.subheader("🛡 損切りライン（逃げ場）")
            stops = calculate_stop_loss(df, info, price)
            tight  = [s for s in stops if -5 <= s['distance_pct'] < 0]
            normal = [s for s in stops if -10 <= s['distance_pct'] < -5]
            loose  = [s for s in stops if s['distance_pct'] < -10]
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                st.markdown("**🚨 タイト（短期）**")
                if tight:
                    s = max(tight, key=lambda x: x['distance_pct'])
                    st.metric(s['label'], f"{s['price']:,.0f} 円", f"{s['distance_pct']:.1f}%")
                    st.caption(s['desc'])
            with sc2:
                st.markdown("**⚠️ 標準（中期）**")
                if normal:
                    s = max(normal, key=lambda x: x['distance_pct'])
                    st.metric(s['label'], f"{s['price']:,.0f} 円", f"{s['distance_pct']:.1f}%")
                    st.caption(s['desc'])
            with sc3:
                st.markdown("**🛡 余裕（長期）**")
                if loose:
                    s = max(loose, key=lambda x: x['distance_pct'])
                    st.metric(s['label'], f"{s['price']:,.0f} 円", f"{s['distance_pct']:.1f}%")
                    st.caption(s['desc'])
            critical = [s for s in stops if s.get('urgency') == '最高']
            if critical:
                c = critical[0]
                st.error(f"🚨 **{c['label']}: {c['price']:,.0f} 円** ({c['distance_pct']:+.1f}%)")

            targets = calculate_sell_targets(df, info, price)
            if targets and stops:
                near_target = min([t for t in targets if t['distance_pct'] > 0],
                                  key=lambda x: x['distance_pct'], default=None)
                rep_stop = None
                if normal:
                    rep_stop = max(normal, key=lambda x: x['distance_pct'])
                elif tight:
                    rep_stop = max(tight, key=lambda x: x['distance_pct'])
                if near_target and rep_stop:
                    upside = near_target['distance_pct']
                    downside = abs(rep_stop['distance_pct'])
                    ratio = upside / downside if downside > 0 else 0
                    st.markdown("### ⚖️ リスクリワード比")
                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("上昇余地", f"+{upside:.1f}%")
                    rc2.metric("下落リスク", f"-{downside:.1f}%")
                    rc3.metric("RR比", f"1 : {ratio:.1f}")
                    if ratio >= 2:
                        st.success(f"✅ リスクリワード良好（1:{ratio:.1f}）")
                    elif ratio >= 1:
                        st.warning(f"⚠️ やや微妙（1:{ratio:.1f}）")
                    else:
                        st.error(f"❌ 不利（1:{ratio:.1f}）。見送り推奨")
            df_s = pd.DataFrame([{'価格': f"{s['price']:,.0f}", 'ラベル': s['label'],
                '種別': s['category'], '距離': f"{s['distance_pct']:+.1f}%",
                '緊急度': s.get('urgency', '—'), '説明': s['desc']} for s in stops])
            st.dataframe(df_s, use_container_width=True, hide_index=True)
            st.info("💡 損切りは『負け』ではなく『次のチャンスのための資金確保』です。")

        with tab6:
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.link_button("📋 Yahoo掲示板", f"https://finance.yahoo.co.jp/quote/{code}.T/bbs")
            with cc2:
                st.link_button("📰 株探", f"https://kabutan.jp/stock/?code={code}")
            with cc3:
                st.link_button("🐦 X", f"https://twitter.com/search?q={code}&f=live")

# ===================================================================
# 注目銘柄を探す
# ===================================================================
elif mode == "🔥 注目銘柄を探す":
    st.write("📡 市場データから注目銘柄を検知")
    col_a, col_b = st.columns(2)
    with col_a:
        threshold = st.slider("注目度の閾値", 1, 10, hot_threshold_default)
    with col_b:
        sort_mode = st.selectbox("並び順", ["注目度", "出来高急増率", "1週間リターン"])

    if st.button("🔥 注目銘柄を探す", type="primary"):
        results = []; errors = 0
        progress = st.progress(0); status = st.empty()
        total = len(NIKKEI_MAJOR)
        for i, (sc, name) in enumerate(NIKKEI_MAJOR.items(), 1):
            status.text(f"[{i}/{total}] {sc} {name}")
            progress.progress(i / total)
            df, info = fetch_stock_data(sc, "6mo")
            if df.empty or len(df) < 60:
                errors += 1; time.sleep(0.3); continue
            try:
                df['MA5']  = df['Close'].rolling(5).mean()
                df['MA25'] = df['Close'].rolling(25).mean()
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
                vol = latest['Volume'] / df['Volume'].tail(25).mean()
                vol5 = df['Volume'].tail(5).mean() / df['Volume'].tail(25).mean()
                if vol > vol_spike * 1.7: score += 3; reasons.append(f"🔥{vol:.1f}x")
                elif vol > vol_spike * 1.2: score += 2; reasons.append(f"🔥{vol:.1f}x")
                elif vol > vol_spike * 0.87: score += 1; reasons.append(f"🔥{vol:.1f}x")
                if vol5 > vol_spike: score += 1; reasons.append(f"📊5日{vol5:.1f}x")
                tr_t = latest['High'] - latest['Low']
                rr = tr_t / latest['ATR'] if latest['ATR'] > 0 else 1
                if rr > 2.0: score += 2; reasons.append(f"💥{rr:.1f}x")
                elif rr > 1.5: score += 1; reasons.append(f"💥{rr:.1f}x")
                r1w = (price / df['Close'].iloc[-5] - 1) * 100
                r1m = (price / df['Close'].iloc[-20] - 1) * 100
                if r1w > 10: score += 2; reasons.append(f"📈1週+{r1w:.1f}%")
                elif r1w > 5: score += 1; reasons.append(f"📈1週+{r1w:.1f}%")
                if r1m > 15: score += 1; reasons.append(f"📈1月+{r1m:.1f}%")
                h20 = df['High'].iloc[-21:-1].max()
                if price > h20: score += 2; reasons.append("🚀20日高値更新")
                if prev['Close'] <= prev['MA25'] and price > latest['MA25']:
                    score += 1; reasons.append("✨25日線上抜け")
                h52 = df['High'].max()
                dh = (price / h52 - 1) * 100
                if dh > -3: score += 1; reasons.append(f"🎯高値圏({dh:+.1f}%)")
                if latest['RSI'] > rsi_overbought + 10:
                    score -= 2; reasons.append(f"⚠️RSI={latest['RSI']:.0f}")
                elif latest['RSI'] > rsi_overbought + 5:
                    score -= 1; reasons.append(f"⚠️RSI={latest['RSI']:.0f}")
                results.append({
                    'コード': sc, '銘柄名': name, '現在値': f"{price:,.0f}",
                    '注目度': score, '出来高比': f"{vol:.1f}x",
                    '1週': f"{r1w:+.1f}%", '1月': f"{r1m:+.1f}%",
                    'RSI': f"{latest['RSI']:.0f}",
                    'シグナル': " / ".join(reasons) if reasons else "—",
                    '_vol': vol, '_ret1w': r1w,
                })
            except Exception:
                errors += 1; continue
        progress.empty(); status.empty()
        if results:
            st.session_state['scan_results'] = results
            st.session_state['scan_errors']  = errors
        else:
            st.error("⚠️ データ取得失敗")

    if 'scan_results' in st.session_state:
        results = st.session_state['scan_results']
        errors  = st.session_state.get('scan_errors', 0)
        if errors > 0:
            st.warning(f"ℹ️ {errors}銘柄取得失敗")
        df_r = pd.DataFrame(results)
        if sort_mode == "注目度":
            df_r = df_r.sort_values('注目度', ascending=False)
        elif sort_mode == "出来高急増率":
            df_r = df_r.sort_values('_vol', ascending=False)
        else:
            df_r = df_r.sort_values('_ret1w', ascending=False)
        df_r = df_r.drop(columns=['_vol', '_ret1w']).reset_index(drop=True)
        hot = df_r[df_r['注目度'] >= threshold]
        st.success(f"✅ {len(hot)}銘柄が注目度 {threshold} 以上")
        if len(hot) > 0:
            st.dataframe(hot, use_container_width=True, hide_index=True)
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
            st.warning("該当なし")
            st.dataframe(df_r.head(10), use_container_width=True, hide_index=True)

# ===================================================================
# ニュースで話題の銘柄
# ===================================================================
else:
    st.write("📰 Googleニュースから話題の銘柄を抽出")
    if st.button("📰 話題の銘柄を集める", type="primary"):
        queries = ["株価 急騰", "ストップ高", "上方修正", "決算 サプライズ",
                   "材料株", "新高値", "業績 好調"]
        code_counts = Counter(); code_articles = {}
        progress = st.progress(0); status = st.empty()
        for idx, q in enumerate(queries, 1):
            status.text(f"[{idx}/{len(queries)}] 「{q}」")
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
            st.warning("抽出失敗")
        else:
            status2 = st.empty()
            status2.text("市場データ突き合わせ中...")
            top_codes = [c for c, _ in code_counts.most_common(15)]
            enriched = []
            for c in top_codes:
                df, info = fetch_stock_data(c, "3mo")
                if df.empty or len(df) < 25:
                    enriched.append({'コード': c, '銘柄名': STOCK_DICT.get(c, c),
                        '現在値': '—', '言及数': code_counts[c],
                        '出来高比': '—', '当日': '—', '1週': '—',
                        '話題度': code_counts[c]})
                    time.sleep(0.3); continue
                try:
                    latest = df.iloc[-1]; price = latest['Close']
                    vol = latest['Volume'] / df['Volume'].tail(25).mean()
                    r1w = (price / df['Close'].iloc[-5] - 1) * 100 if len(df) >= 5 else 0
                    r1d = (price / df['Close'].iloc[-2] - 1) * 100 if len(df) >= 2 else 0
                    hs = code_counts[c]
                    if vol > 1.5: hs += 2
                    elif vol > 1.2: hs += 1
                    if r1w > 5: hs += 1
                    if r1d > 3: hs += 1
                    name = info.get('longName', STOCK_DICT.get(c, c))
                    if len(name) > 15: name = name[:15] + "…"
                    enriched.append({'コード': c, '銘柄名': name,
                        '現在値': f"{price:,.0f}", '言及数': code_counts[c],
                        '出来高比': f"{vol:.1f}x", '当日': f"{r1d:+.1f}%",
                        '1週': f"{r1w:+.1f}%", '話題度': hs})
                except Exception:
                    continue
            status2.empty()
            st.session_state['news_results'] = enriched
            st.session_state['news_articles'] = code_articles

    if 'news_results' in st.session_state:
        enriched = st.session_state['news_results']
        code_articles = st.session_state['news_articles']
        df_n = pd.DataFrame(enriched).sort_values('話題度', ascending=False).reset_index(drop=True)
        st.success(f"✅ {len(df_n)}銘柄")
        st.dataframe(df_n, use_container_width=True, hide_index=True)
        for _, row in df_n.head(5).iterrows():
            c = row['コード']
            with st.expander(f"📌 {c} {row['銘柄名']} （話題度 {row['話題度']}）"):
                for a in code_articles.get(c, []):
                    st.markdown(f"- [{a['title']}]({a['link']})")
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.link_button("📊 株探", f"https://kabutan.jp/stock/?code={c}")
                with cc2:
                    st.link_button("📋 掲示板", f"https://finance.yahoo.co.jp/quote/{c}.T/bbs")
                with cc3:
                    st.link_button("🐦 X", f"https://twitter.com/search?q={c}&f=live")

st.sidebar.markdown("---")
st.sidebar.caption("⚠️ 投資判断の参考情報です。投資は自己責任で。")
