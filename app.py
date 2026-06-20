# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
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
# 共通ヘルパー：キャッシュ付き・リトライ付きデータ取得
# ===================================================================
@st.cache_data(ttl=900, show_spinner=False)  # 15分キャッシュ
def fetch_stock_data(code, period="1y"):
    """株価データをキャッシュ付き＆リトライ付きで取得"""
    for attempt in range(3):
        try:
            ticker = yf.Ticker(f"{code}.T")
            df = ticker.history(period=period)
            info = {}
            try:
                info = ticker.info
            except Exception:
                pass  # info取得失敗してもdfがあればOK
            if not df.empty:
                return df, info
        except Exception as e:
            if "rate" in str(e).lower() or "limit" in str(e).lower():
                time.sleep(2 + attempt * 2)  # 2秒, 4秒, 6秒と待つ
                continue
            else:
                break
    return pd.DataFrame(), {}

# === サイドバー ===
mode = st.sidebar.radio("モード", [
    "🔍 個別銘柄分析",
    "🔥 注目銘柄を探す",
    "📰 ニュースで話題の銘柄",
])

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

    if st.button("📊 分析する", type="primary"):
        with st.spinner("データ取得中..."):
            df, info = fetch_stock_data(code, period)

        if df.empty:
            st.error("⚠️ データが取得できませんでした。")
            st.info("考えられる原因：\n"
                    "- 銘柄コードが間違っている\n"
                    "- Yahoo Finance のレート制限（10〜30分待って再試行）\n"
                    "- 一時的なネットワーク不調")
            st.stop()

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

        tab1, tab2, tab3, tab4 = st.tabs(["📊 チャート", "⚡ 短期判断", "🏛 長期判断", "🌐 外部情報"])

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
            score = 0; msgs = []
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
            st.write("この銘柄について外部サイトで最新情報をチェック")
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                st.link_button("📋 Yahoo掲示板", f"https://finance.yahoo.co.jp/quote/{code}.T/bbs")
            with cc2:
                st.link_button("📰 株探", f"https://kabutan.jp/stock/?code={code}")
            with cc3:
                st.link_button("🐦 Xで検索", f"https://twitter.com/search?q={code}&f=live")

# ===================================================================
# 注目銘柄を探す
# ===================================================================
elif mode == "🔥 注目銘柄を探す":
    st.write("📡 市場データから「今、買いが集まり始めている銘柄」を検知します。")
    st.caption("出来高急増・値動き拡大・トレンド転換などを総合スコア化")

    col_a, col_b = st.columns(2)
    with col_a:
        threshold = st.slider("注目度の閾値", 1, 10, 4)
    with col_b:
        sort_mode = st.selectbox("並び順", ["注目度", "出来高急増率", "1週間リターン"])

    if st.button("🔥 注目銘柄を探す", type="primary"):
        results = []
        errors = 0
        progress = st.progress(0)
        status = st.empty()
        total = len(NIKKEI_MAJOR)

        for i, (code, name) in enumerate(NIKKEI_MAJOR.items(), 1):
            status.text(f"分析中 [{i}/{total}] {code} {name}（エラー: {errors}）")
            progress.progress(i / total)
            
            df, info = fetch_stock_data(code, "6mo")
            if df.empty or len(df) < 60:
                errors += 1
                time.sleep(0.3)  # レート制限緩和のための小休止
                continue

            try:
                df['MA5']  = df['Close'].rolling(5).mean()
                df['MA25'] = df['Close'].rolling(25).mean()
                df['MA75'] = df['Close'].rolling(75).mean()

                high_low   = df['High'] - df['Low']
                high_close = (df['High'] - df['Close'].shift()).abs()
                low_close  = (df['Low']  - df['Close'].shift()).abs()
                tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                df['ATR'] = tr.rolling(14).mean()

                delta = df['Close'].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = -delta.where(delta < 0, 0).rolling(14).mean()
                df['RSI'] = 100 - (100 / (1 + gain / loss))

                latest = df.iloc[-1]; prev = df.iloc[-2]; price = latest['Close']
                score = 0; reasons = []

                vol_today_ratio = latest['Volume'] / df['Volume'].tail(25).mean()
                vol_5d_ratio    = df['Volume'].tail(5).mean() / df['Volume'].tail(25).mean()

                if vol_today_ratio > 2.5:
                    score += 3; reasons.append(f"🔥当日出来高{vol_today_ratio:.1f}倍")
                elif vol_today_ratio > 1.8:
                    score += 2; reasons.append(f"🔥当日出来高{vol_today_ratio:.1f}倍")
                elif vol_today_ratio > 1.3:
                    score += 1; reasons.append(f"🔥当日出来高{vol_today_ratio:.1f}倍")
                if vol_5d_ratio > 1.5:
                    score += 1; reasons.append(f"📊5日平均{vol_5d_ratio:.1f}倍")

                today_range = latest['High'] - latest['Low']
                range_ratio = today_range / latest['ATR'] if latest['ATR'] > 0 else 1
                if range_ratio > 2.0:
                    score += 2; reasons.append(f"💥値幅{range_ratio:.1f}倍")
                elif range_ratio > 1.5:
                    score += 1; reasons.append(f"💥値幅{range_ratio:.1f}倍")

                ret_1w = (price / df['Close'].iloc[-5] - 1) * 100
                ret_1m = (price / df['Close'].iloc[-20] - 1) * 100
                if ret_1w > 10:
                    score += 2; reasons.append(f"📈1週+{ret_1w:.1f}%")
                elif ret_1w > 5:
                    score += 1; reasons.append(f"📈1週+{ret_1w:.1f}%")
                if ret_1m > 15:
                    score += 1; reasons.append(f"📈1月+{ret_1m:.1f}%")

                high_20 = df['High'].iloc[-21:-1].max()
                if price > high_20:
                    score += 2; reasons.append("🚀20日高値更新")
                if prev['Close'] <= prev['MA25'] and price > latest['MA25']:
                    score += 1; reasons.append("✨25日線上抜け")

                high_52w = df['High'].max()
                dist_high = (price / high_52w - 1) * 100
                if dist_high > -3:
                    score += 1; reasons.append(f"🎯高値圏({dist_high:+.1f}%)")

                if latest['RSI'] > 80:
                    score -= 2; reasons.append(f"⚠️RSI={latest['RSI']:.0f}過熱")
                elif latest['RSI'] > 75:
                    score -= 1; reasons.append(f"⚠️RSI={latest['RSI']:.0f}やや過熱")

                results.append({
                    'コード': code, '銘柄名': name,
                    '現在値': f"{price:,.0f}",
                    '注目度': score,
                    '出来高比': f"{vol_today_ratio:.1f}x",
                    '1週': f"{ret_1w:+.1f}%",
                    '1月': f"{ret_1m:+.1f}%",
                    'RSI': f"{latest['RSI']:.0f}",
                    'シグナル': " / ".join(reasons) if reasons else "—",
                    '_vol': vol_today_ratio,
                    '_ret1w': ret_1w,
                })
            except Exception:
                errors += 1
                continue

        progress.empty(); status.empty()

        if not results:
            st.error("⚠️ データ取得に失敗しました。Yahoo Finance のレート制限の可能性があります。")
            st.info("10〜30分待ってから再試行してください。")
            st.stop()

        if errors > 0:
            st.warning(f"ℹ️ {errors}銘柄はデータ取得に失敗しました（取得できた{len(results)}銘柄で表示）")

        df_result = pd.DataFrame(results)
        if sort_mode == "注目度":
            df_result = df_result.sort_values('注目度', ascending=False)
        elif sort_mode == "出来高急増率":
            df_result = df_result.sort_values('_vol', ascending=False)
        else:
            df_result = df_result.sort_values('_ret1w', ascending=False)
        df_result = df_result.drop(columns=['_vol', '_ret1w']).reset_index(drop=True)
        hot = df_result[df_result['注目度'] >= threshold]

        st.success(f"✅ {len(hot)}銘柄が注目度 {threshold} 以上に該当しました")

        if len(hot) > 0:
            st.dataframe(hot, use_container_width=True, hide_index=True)
            st.markdown("### 🌐 上位銘柄の詳細を外部サイトで確認")
            for _, row in hot.head(3).iterrows():
                c = row['コード']
                with st.expander(f"{c} {row['銘柄名']} （注目度 {row['注目度']}）"):
                    cc1, cc2, cc3 = st.columns(3)
                    with cc1:
                        st.link_button("📋 Yahoo掲示板", f"https://finance.yahoo.co.jp/quote/{c}.T/bbs")
                    with cc2:
                        st.link_button("📰 株探", f"https://kabutan.jp/stock/?code={c}")
                    with cc3:
                        st.link_button("🐦 Xで検索", f"https://twitter.com/search?q={c}&f=live")
                    st.write(f"**シグナル**: {row['シグナル']}")
        else:
            st.warning("該当なし。閾値を下げてみてください。")
            st.write("### 参考：上位10銘柄")
            st.dataframe(df_result.head(10), use_container_width=True, hide_index=True)

# ===================================================================
# ニュースで話題の銘柄
# ===================================================================
else:
    st.write("📰 Googleニュースから「今ニュースで話題の銘柄」を抽出してランキング表示します。")
    st.caption("ニュース言及数 × 市場の値動きで「話題＋実際に動いてる銘柄」を見つけます")

    if st.button("📰 話題の銘柄を集める", type="primary"):
        queries = [
            "株価 急騰", "ストップ高", "上方修正",
            "決算 サプライズ", "材料株", "新高値", "業績 好調",
        ]

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
                    for code in set(codes):
                        if 1000 <= int(code) <= 9999:
                            code_counts[code] += 1
                            if code not in code_articles:
                                code_articles[code] = []
                            if len(code_articles[code]) < 5:
                                code_articles[code].append({'title': title, 'link': entry.link})
            except Exception:
                continue

        progress.empty(); status.empty()

        if not code_counts:
            st.warning("ニュースから銘柄コードを抽出できませんでした。")
            st.stop()

        st.success(f"✅ {len(code_counts)}銘柄がニュースで言及されています")

        status2 = st.empty()
        status2.text("市場データと突き合わせ中...")
        top_codes = [c for c, _ in code_counts.most_common(15)]  # 20→15に削減
        enriched = []
        market_errors = 0

        for code in top_codes:
            df, info = fetch_stock_data(code, "3mo")
            if df.empty or len(df) < 25:
                market_errors += 1
                # 市場データ取れなくてもニュース情報だけは表示
                enriched.append({
                    'コード': code, '銘柄名': code,
                    '現在値': '—', '言及数': code_counts[code],
                    '出来高比': '—', '当日': '—', '1週': '—',
                    '話題度': code_counts[code],
                })
                time.sleep(0.3)
                continue

            try:
                latest = df.iloc[-1]
                price = latest['Close']
                vol_ratio = latest['Volume'] / df['Volume'].tail(25).mean()
                ret_1w = (price / df['Close'].iloc[-5] - 1) * 100 if len(df) >= 5 else 0
                ret_1d = (price / df['Close'].iloc[-2] - 1) * 100 if len(df) >= 2 else 0

                hot_score = code_counts[code]
                if vol_ratio > 1.5: hot_score += 2
                elif vol_ratio > 1.2: hot_score += 1
                if ret_1w > 5: hot_score += 1
                if ret_1d > 3: hot_score += 1

                name = info.get('longName', code)
                if len(name) > 15: name = name[:15] + "…"

                enriched.append({
                    'コード': code, '銘柄名': name,
                    '現在値': f"{price:,.0f}",
                    '言及数': code_counts[code],
                    '出来高比': f"{vol_ratio:.1f}x",
                    '当日': f"{ret_1d:+.1f}%",
                    '1週': f"{ret_1w:+.1f}%",
                    '話題度': hot_score,
                })
            except Exception:
                market_errors += 1
                continue

        status2.empty()

        if market_errors > 0:
            st.info(f"ℹ️ {market_errors}銘柄は市場データが取得できませんでした（ニュース情報のみ表示）")

        df_news = pd.DataFrame(enriched).sort_values('話題度', ascending=False).reset_index(drop=True)
        st.dataframe(df_news, use_container_width=True, hide_index=True)

        st.markdown("### 📑 上位銘柄のニュース見出し")
        for _, row in df_news.head(5).iterrows():
            code = row['コード']
            with st.expander(f"📌 {code} {row['銘柄名']} （話題度 {row['話題度']} / 言及 {row['言及数']}件）"):
                articles = code_articles.get(code, [])
                if articles:
                    st.write("**関連ニュース見出し**")
                    for a in articles:
                        st.markdown(f"- [{a['title']}]({a['link']})")
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.link_button("📊 株探で詳細", f"https://kabutan.jp/stock/?code={code}")
                with cc2:
                    st.link_button("📋 掲示板", f"https://finance.yahoo.co.jp/quote/{code}.T/bbs")
                with cc3:
                    st.link_button("🐦 Xで検索", f"https://twitter.com/search?q={code}&f=live")

        st.caption("💡「話題度」= ニュース言及数 + 出来高・値動きのボーナス。両方揃ってる銘柄が本物の可能性大。")

st.sidebar.markdown("---")
st.sidebar.caption("⚠️ このツールは投資判断の参考情報を提供するもので、利益を保証するものではありません。投資は自己責任でお願いします。")
