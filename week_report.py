"""
股市周度汇总报告
每周日晚上7:00自动生成，汇总本周各市场表现
"""
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
import requests as _requests

# ============================================================
# 配置
# ============================================================
EMAIL_FROM = "972548750@qq.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "972548750@qq.com")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# ============================================================
# 自选股（从 GitHub Secret 读取，和日报共用）
# ============================================================
def _auto_market(code: str) -> str:
    code = code.strip()
    if code.startswith("6"):
        return f"1.{code}"
    elif code.startswith("0") or code.startswith("3"):
        return f"0.{code}"
    return code

def _parse_watchlist() -> dict:
    config = os.environ.get("WATCHLIST_CONFIG", "")
    if config.strip():
        result = {}
        for item in config.split(","):
            item = item.strip()
            if ":" in item:
                name, code = item.split(":", 1)
                result[name.strip()] = _auto_market(code)
        if result:
            return result
    return {
        "贵州茅台": "1.600519",
        "宁德时代": "0.300750",
        "比亚迪":   "0.002594",
    }

WATCHLIST = _parse_watchlist()

# ============================================================
# 追踪标的（yfinance代码）
# ============================================================
A_SHARE_WEEKLY = {
    "上证指数": "000001.SS",
    "深证成指": "399001.SZ",
    "沪深300":  "000300.SS",
    "创业板指": "399006.SZ",
}

US_WEEKLY = {
    "道琼斯": "^DJI",
    "纳斯达克": "^IXIC",
    "标普500": "^GSPC",
}

ASIA_WEEKLY = {
    "日经225": "^N225",
    "韩国KOSPI": "^KS11",
}

# A股板块（东方财富）
A_SECTORS_WEEKLY = {
    "半导体":   "90.BK1036",
    "人工智能": "90.BK0800",
    "航天航空": "90.BK0488",
    "芯片概念": "90.BK0893",
    "机器人":   "90.BK0609",
    "新能源":   "90.BK0493",
    "消费电子": "90.BK0447",
    "创新药":   "90.BK0444",
}

# A股板块对应的行业ETF（yfinance可获取历史数据）
SECTOR_ETFS_WEEKLY = {
    "半导体":   "512480.SS",
    "芯片":     "159995.SZ",
    "人工智能": "515070.SS",
    "军工航天": "512660.SS",
    "机器人":   "562500.SS",
    "新能源":   "516160.SS",
    "消费电子": "159732.SZ",
    "创新药":   "159992.SZ",
}


def _secid_to_yfinance(secid: str) -> str:
    """将东方财富格式(1.600519)转为yfinance格式(600519.SS)"""
    if "." in secid:
        market, code = secid.split(".", 1)
        suffix = "SS" if market == "1" else "SZ"
        return f"{code}.{suffix}"
    return secid


def fetch_watchlist_weekly() -> dict:
    """获取自选股本周累计涨跌"""
    results = {}
    for name, secid in WATCHLIST.items():
        yf_code = _secid_to_yfinance(secid)
        try:
            ticker = yf.Ticker(yf_code)
            hist = ticker.history(period="5d")
            if len(hist) < 2:
                continue
            first_close = hist.iloc[0]["Close"]
            last_close = hist.iloc[-1]["Close"]
            week_change = last_close - first_close
            week_change_pct = (week_change / first_close) * 100
            results[name] = {
                "name": name,
                "start": round(float(first_close), 2),
                "end": round(float(last_close), 2),
                "change": round(float(week_change), 2),
                "change_pct": round(float(week_change_pct), 2),
                "high": round(float(hist["High"].max()), 2),
                "low": round(float(hist["Low"].min()), 2),
            }
            print(f"  ✓ 自选股 {name}: 周{results[name]['change_pct']:+.2f}%")
        except Exception as e:
            print(f"  ✗ 自选股 {name}: {e}")
    return results


def fetch_sector_weekly_data() -> dict:
    """通过yfinance获取A股行业ETF本周累计涨跌"""
    results = {}
    for name, code in SECTOR_ETFS_WEEKLY.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            if len(hist) < 2:
                continue

            first_close = hist.iloc[0]["Close"]
            last_close = hist.iloc[-1]["Close"]
            week_change = last_close - first_close
            week_change_pct = (week_change / first_close) * 100

            results[name] = {
                "name": name,
                "start": round(float(first_close), 2),
                "end": round(float(last_close), 2),
                "change_pct": round(float(week_change_pct), 2),
            }
            print(f"  ✓ 板块ETF {name}: 周{results[name]['change_pct']:+.2f}%")
        except Exception as e:
            print(f"  ✗ 板块ETF {name}: {e}")

    return results


def fetch_weekly_data(symbols: dict) -> dict:
    """获取本周累计涨跌幅（使用5日数据）"""
    results = {}
    for name, code in symbols.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            if len(hist) < 2:
                continue

            first_close = hist.iloc[0]["Close"]
            last_close = hist.iloc[-1]["Close"]
            week_change = last_close - first_close
            week_change_pct = (week_change / first_close) * 100

            # 最高最低
            week_high = float(hist["High"].max())
            week_low = float(hist["Low"].min())

            results[name] = {
                "name": name,
                "start": round(float(first_close), 2),
                "end": round(float(last_close), 2),
                "change": round(float(week_change), 2),
                "change_pct": round(float(week_change_pct), 2),
                "high": round(week_high, 2),
                "low": round(week_low, 2),
            }
            print(f"  ✓ {name}: {results[name]['start']:.2f} → {results[name]['end']:.2f} ({results[name]['change_pct']:+.2f}%)")
        except Exception as e:
            print(f"  ✗ {name}: {e}")

    return results


def fetch_a_sectors_snapshot() -> dict:
    """获取A股板块当前快照（东方财富API，带fltt=2和数据校验）"""
    results = {}
    import urllib.request

    for name, code in A_SECTORS_WEEKLY.items():
        url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={code}&fltt=2&fields=f43,f57,f58,f169,f170"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            d = data.get("data")
            if d and d.get("f57"):
                pct = float(d.get("f170", 0))
                if abs(pct) > 22:
                    print(f"  ⚠ 板块{name}: 涨跌幅异常({pct}%)，跳过")
                    continue
                results[name] = {
                    "name": name,
                    "price": float(d.get("f43", 0)),
                    "change_pct": pct,
                    "change": float(d.get("f169", 0)),
                }
        except Exception as e:
            print(f"  ✗ 板块{name}: {e}")

    return results


def fetch_concept_sector_ranking_weekly(top_n: int = 6) -> dict:
    """获取A股概念板块涨幅榜和跌幅榜（东方财富API，和日报共用逻辑）"""
    import urllib.request
    results = {"top": [], "bottom": []}
    headers = {"User-Agent": "Mozilla/5.0"}

    # 概念板块涨幅榜
    url_top = (
        f"http://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=1&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:90+t:3"
        f"&fields=f2,f3,f4,f12,f14"
    )
    try:
        req = urllib.request.Request(url_top, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("diff", []):
            results["top"].append({
                "name": item.get("f14", ""),
                "change_pct": float(item.get("f3", 0)),
            })
        print(f"  ✓ 概念板块涨幅榜: {len(results['top'])} 个")
    except Exception as e:
        print(f"  ✗ 概念板块涨幅榜: {e}")

    # 概念板块跌幅榜
    url_bottom = (
        f"http://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=0&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:90+t:3"
        f"&fields=f2,f3,f4,f12,f14"
    )
    try:
        req = urllib.request.Request(url_bottom, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("diff", []):
            results["bottom"].append({
                "name": item.get("f14", ""),
                "change_pct": float(item.get("f3", 0)),
            })
        print(f"  ✓ 概念板块跌幅榜: {len(results['bottom'])} 个")
    except Exception as e:
        print(f"  ✗ 概念板块跌幅榜: {e}")

    return results


def fetch_top_movers_weekly(top_n: int = 6) -> tuple:
    """获取A股涨幅榜和跌幅榜（最近交易日数据，和日报共用逻辑）"""
    import urllib.request
    top_gainers = []
    top_losers = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # 涨幅榜
    url_gainers = (
        f"http://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n + 5}&po=1&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:0+t:6,m:0+t:80"
        f"&fields=f2,f3,f4,f12,f14"
    )
    try:
        req = urllib.request.Request(url_gainers, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("diff", []):
            name = item.get("f14", "")
            if "*ST" in name:
                continue
            top_gainers.append({
                "name": name,
                "code": item.get("f12", ""),
                "price": float(item.get("f2", 0)),
                "change_pct": float(item.get("f3", 0)),
            })
            if len(top_gainers) >= top_n:
                break
        print(f"  ✓ 涨幅榜: {len(top_gainers)} 只")
    except Exception as e:
        print(f"  ✗ 涨幅榜: {e}")

    # 跌幅榜
    url_losers = (
        f"http://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n + 5}&po=0&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:0+t:6,m:0+t:80"
        f"&fields=f2,f3,f4,f12,f14"
    )
    try:
        req = urllib.request.Request(url_losers, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("diff", []):
            name = item.get("f14", "")
            if "*ST" in name:
                continue
            top_losers.append({
                "name": name,
                "code": item.get("f12", ""),
                "price": float(item.get("f2", 0)),
                "change_pct": float(item.get("f3", 0)),
            })
            if len(top_losers) >= top_n:
                break
        print(f"  ✓ 跌幅榜: {len(top_losers)} 只")
    except Exception as e:
        print(f"  ✗ 跌幅榜: {e}")

    return top_gainers, top_losers


def analyze_weekly_strategy(symbols: dict) -> list:
    """基于周线数据计算技术指标（用yfinance日线重采样为周线）"""
    results = []
    for name, code in symbols.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="1y")
            if hist.empty or len(hist) < 20:
                continue

            # 日线重采样为周线
            weekly = hist.resample("W").agg({
                "Open": "first", "High": "max",
                "Low": "min", "Close": "last",
                "Volume": "sum",
            }).dropna()

            closes = weekly["Close"].tolist()
            volumes = weekly["Volume"].tolist()
            signals = []

            def ma(data, n):
                return sum(data[-n:]) / n if len(data) >= n else None

            ma5, ma10, ma20 = ma(closes, 5), ma(closes, 10), ma(closes, 20)
            if ma5 and ma10 and ma20:
                if ma5 > ma10 > ma20:
                    signals.append("📈 周线均线多头排列")
                elif ma5 < ma10 < ma20:
                    signals.append("📉 周线均线空头排列")
                if closes[-1] > ma5 > ma10:
                    signals.append("✅ 周线价格站上均线")
                elif closes[-1] < ma5 < ma10:
                    signals.append("⚠️ 周线价格跌破均线")

            # MACD（周线）
            if len(closes) >= 26:
                e12 = sum(closes[-12:]) / 12
                e26 = sum(closes[-26:]) / 26
                dif = e12 - e26
                e12_prev = sum(closes[-13:-1]) / 12
                e26_prev = sum(closes[-27:-1]) / 26
                dif_prev = e12_prev - e26_prev
                dea = (dif + dif_prev) / 2
                if dif > 0 and dif_prev <= 0:
                    signals.append("🔴 周线MACD金叉")
                elif dif < 0 and dif_prev >= 0:
                    signals.append("🟢 周线MACD死叉")
                elif dif > dea > 0:
                    signals.append("📈 周线MACD多头")
                elif dif < dea < 0:
                    signals.append("📉 周线MACD空头")

            # RSI（周线）
            if len(closes) >= 15:
                gains, losses = [], []
                for i in range(-14, 0):
                    diff = closes[i] - closes[i - 1]
                    gains.append(max(0, diff))
                    losses.append(max(0, -diff))
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
                if rsi > 70:
                    signals.append(f"⚠️ 周RSI超买({rsi:.0f})")
                elif rsi < 30:
                    signals.append(f"✅ 周RSI超卖({rsi:.0f})")
                else:
                    signals.append(f"📊 周RSI中性({rsi:.0f})")

            # 量能
            if len(volumes) >= 6:
                vol5 = sum(volumes[-5:]) / 5
                vol_prev5 = sum(volumes[-10:-5]) / 5
                if vol5 > vol_prev5 * 1.3:
                    signals.append("📈 周线明显放量")
                elif vol5 < vol_prev5 * 0.7:
                    signals.append("📉 周线明显缩量")

            if signals:
                results.append({"name": name, "signals": signals})
                print(f"  ✓ {name}: {len(signals)} 个信号")
        except Exception as e:
            print(f"  ✗ {name}技术分析失败: {e}")

    return results


def ai_weekly_outlook(a_share: dict, us_data: dict, asia_data: dict,
                       a_sectors: dict, sector_weekly: dict, week_range: str,
                       watchlist: dict = None, concept_weekly: dict = None,
                       top_movers: tuple = None) -> Optional[str]:
    """使用DeepSeek API生成下周展望分析"""
    if not DEEPSEEK_API_KEY:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        # 构建数据摘要
        data_parts = {
            "本周交易区间": week_range,
            "A股指数周涨跌": {k: f"{v['start']:.2f}→{v['end']:.2f}({v['change_pct']:+.2f}%)" for k, v in a_share.items()},
            "美股周涨跌": {k: f"{v['change_pct']:+.2f}%" for k, v in us_data.items()},
            "日韩周涨跌": {k: f"{v['change_pct']:+.2f}%" for k, v in asia_data.items()},
            "A股板块ETF周涨跌": {k: f"{v['change_pct']:+.2f}%" for k, v in sector_weekly.items()} if sector_weekly else {},
            "A股板块当日快照": {k: f"{v['change_pct']:+.2f}%" for k, v in a_sectors.items()},
        }
        if watchlist:
            data_parts["自选股周表现"] = {k: f"{v['start']:.2f}→{v['end']:.2f}(周{v['change_pct']:+.2f}%)" for k, v in watchlist.items()}
        if concept_weekly:
            data_parts["概念板块涨幅TOP"] = [f"{c['name']}({c['change_pct']:+.2f}%)" for c in concept_weekly.get("top", [])]
            data_parts["概念板块跌幅TOP"] = [f"{c['name']}({c['change_pct']:+.2f}%)" for c in concept_weekly.get("bottom", [])]
        if top_movers:
            gainers, losers = top_movers
            data_parts["涨幅榜"] = [f"{g['name']}({g['change_pct']:+.2f}%)" for g in gainers[:5]]
            data_parts["跌幅榜"] = [f"{l['name']}({l['change_pct']:+.2f}%)" for l in losers[:5]]
        data_summary = json.dumps(data_parts, ensure_ascii=False, indent=2)

        prompt = f"""你是资深股市分析师。以下是本周全球市场数据（JSON格式）：

{data_summary}

请基于本周各市场表现，用400字以内分析下周A股可能的变动方向：
1. 结合本周全球市场走势，判断下周A股整体可能偏多还是偏空
2. 哪些板块下周可能延续强势或转弱，给出具体板块名称
3. 需要关注的潜在风险点或机会点（如政策面、外围市场、资金流向等）

要求：语言通俗易懂，观点明确，适合非专业投资者阅读。"""
        if watchlist:
            prompt += "\n\n请额外对自选股持仓逐一给出下周展望（1-2句）。"

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[AI分析] 下周展望调用失败: {e}")
        return None


def generate_weekly_analysis(a_share: dict, us_data: dict, asia_data: dict,
                              a_sectors: dict, week_range: str, sector_weekly: dict = None,
                              watchlist: dict = None, concept_weekly: dict = None,
                              top_movers: tuple = None, tech_signals: list = None) -> str:
    """生成周报分析文本"""
    lines = []
    lines.append(f"📅 本周交易区间：{week_range}")
    lines.append("")

    # 整体判断
    all_pct = []
    for d in list(a_share.values()) + list(us_data.values()) + list(asia_data.values()):
        if d.get("change_pct") is not None:
            all_pct.append(d["change_pct"])

    avg_pct = sum(all_pct) / len(all_pct) if all_pct else 0
    if avg_pct > 1:
        lines.append("🟢 本周全球市场整体偏强")
    elif avg_pct < -1:
        lines.append("🔴 本周全球市场整体偏弱")
    else:
        lines.append("⚪ 本周全球市场震荡整理")
    lines.append("")

    # A股表现
    if a_share:
        lines.append("【🇨🇳 A股表现】")
        sorted_a = sorted(a_share.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_a:
            emoji = "🔴" if d["change_pct"] > 0 else "🟢"
            lines.append(f"  {emoji} {name}: {d['start']:.2f} → {d['end']:.2f}（周{d['change_pct']:+.2f}%）")

        # 最强和最弱
        best = sorted_a[0]
        worst = sorted_a[-1]
        lines.append(f"  最强：{best[0]}（{best[1]['change_pct']:+.2f}%）")
        lines.append(f"  最弱：{worst[0]}（{worst[1]['change_pct']:+.2f}%）")
        lines.append("")

    # 美股表现
    if us_data:
        lines.append("【🇺🇸 美股表现】")
        sorted_u = sorted(us_data.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_u:
            emoji = "🔴" if d["change_pct"] > 0 else "🟢"
            lines.append(f"  {emoji} {name}: 周{d['change_pct']:+.2f}%")
        lines.append("")

    # 日韩表现
    if asia_data:
        lines.append("【🇯🇵🇰🇷 日韩表现】")
        for name, d in asia_data.items():
            emoji = "🔴" if d["change_pct"] > 0 else "🟢"
            lines.append(f"  {emoji} {name}: 周{d['change_pct']:+.2f}%")
        lines.append("")

    # A股板块快照
    if a_sectors:
        lines.append("【🔥 A股板块周度风向】")
        sorted_sec = sorted(a_sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        top3 = sorted_sec[:3]
        bottom3 = sorted_sec[-3:]

        lines.append("  本周领涨：")
        for name, d in top3:
            lines.append(f"    🏆 {name}: {d['change_pct']:+.2f}%")

        lines.append("  本周领跌：")
        for name, d in reversed(bottom3):
            lines.append(f"    ⚠️ {name}: {d['change_pct']:+.2f}%")
        lines.append("")

    # 概念板块排行
    if concept_weekly:
        if concept_weekly.get("top"):
            lines.append("【💡 概念板块领涨】")
            for c in concept_weekly["top"]:
                lines.append(f"  🔥 {c['name']}: {c['change_pct']:+.2f}%")
            lines.append("")
        if concept_weekly.get("bottom"):
            lines.append("【💡 概念板块领跌】")
            for c in concept_weekly["bottom"]:
                lines.append(f"  ⚠️ {c['name']}: {c['change_pct']:+.2f}%")
            lines.append("")

    # 异动个股
    if top_movers:
        gainers, losers = top_movers
        if gainers:
            lines.append("【🚀 涨幅榜 TOP】")
            for g in gainers:
                lines.append(f"  🔴 {g['name']}: {g['change_pct']:+.2f}%（¥{g['price']:.2f}）")
            lines.append("")
        if losers:
            lines.append("【📉 跌幅榜 TOP】")
            for l in losers:
                lines.append(f"  🟢 {l['name']}: {l['change_pct']:+.2f}%（¥{l['price']:.2f}）")
            lines.append("")

    # 周线技术信号
    if tech_signals:
        lines.append("【📊 周线技术信号】")
        for t in tech_signals:
            lines.append(f"  {t['name']}：")
            for s in t["signals"]:
                lines.append(f"    {s}")
        lines.append("")

    # 下周展望（AI生成）
    lines.append("【🔮 下周展望】")
    ai_outlook = ai_weekly_outlook(a_share, us_data, asia_data, a_sectors, sector_weekly, week_range, watchlist, concept_weekly, top_movers)
    if ai_outlook:
        lines.append(ai_outlook)
    else:
        # 回退到规则分析
        if avg_pct > 1.5:
            lines.append("  本周全球市场表现强劲，A股情绪面偏暖。下周关注：")
            lines.append("  ① 强势板块能否延续（如半导体、AI等）")
            lines.append("  ② 外资流入/流出情况")
            lines.append("  ③ 周末政策消息面变化")
        elif avg_pct < -1.5:
            lines.append("  本周全球市场弱势调整，A股承压。下周关注：")
            lines.append("  ① 超跌板块是否存在反弹机会")
            lines.append("  ② 政策面是否有维稳信号")
            lines.append("  ③ 外围市场能否企稳")
        else:
            lines.append("  本周市场震荡，方向不明。下周关注：")
            lines.append("  ① 成交量能否放大（资金入场信号）")
            lines.append("  ② 热门板块轮动节奏")
            lines.append("  ③ 宏观经济数据公布情况")

    return "\n".join(lines)


def generate_html_weekly(date_str: str, week_range: str, a_share: dict, us_data: dict,
                          asia_data: dict, a_sectors: dict, analysis: str,
                          sector_weekly: dict = None, watchlist: dict = None,
                          concept_weekly: dict = None, top_movers: tuple = None,
                          tech_signals: list = None) -> str:
    """生成周报HTML邮件"""
    all_pct = []
    for d in list(a_share.values()) + list(us_data.values()):
        if d.get("change_pct") is not None:
            all_pct.append(d["change_pct"])
    avg_pct = sum(all_pct) / len(all_pct) if all_pct else 0
    mood = "📈" if avg_pct > 0.5 else ("📉" if avg_pct < -0.5 else "📊")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{ font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
       background: #f5f5f5; margin:0; padding:12px; font-size:14px; color:#333; }}
.card {{ background:#fff; border-radius:12px; padding:16px; margin-bottom:12px;
         box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.title {{ font-size:18px; font-weight:bold; margin-bottom:4px; }}
.subtitle {{ color:#888; font-size:12px; margin-bottom:12px; }}
.idx {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #f0f0f0; }}
.idx-name {{ font-weight:500; }}
.idx-price {{ text-align:right; }}
.red {{ color:#e74c3c; }}
.green {{ color:#27ae60; }}
.gray {{ color:#999; }}
.section-title {{ font-size:15px; font-weight:bold; color:#2c3e50; margin:12px 0 8px;
                  padding-left:8px; border-left:3px solid #3498db; }}
.analysis {{ line-height:1.8; white-space:pre-wrap; font-size:13px; }}
.footer {{ text-align:center; color:#bbb; font-size:11px; margin-top:16px; }}
.week-range {{ background:#f0f7ff; padding:8px 12px; border-radius:8px; font-size:13px;
               text-align:center; color:#2c3e50; margin-bottom:4px; }}
.bar-table {{ width:100%; border-collapse:collapse; margin:6px 0; }}
.bar-table td {{ padding:5px 6px; font-size:13px; border-bottom:1px solid #f5f5f5; }}
.bar-table .sector-name {{ font-weight:500; white-space:nowrap; width:65px; }}
.bar-cell {{ width:100%; }}
.bar-track {{ height:14px; background:#f0f0f0; border-radius:7px; position:relative; overflow:hidden; min-width:60px; }}
.bar-fill {{ height:100%; border-radius:7px; position:absolute; }}
.bar-fill.up {{ background:linear-gradient(90deg,#ff6b6b,#e74c3c); }}
.bar-fill.down {{ background:linear-gradient(90deg,#27ae60,#2ecc71); }}
.bar-pct {{ font-weight:bold; font-size:12px; padding-left:8px; white-space:nowrap; text-align:right; width:55px; }}
.bar-summary {{ display:flex; justify-content:space-around; padding:8px 0; font-size:12px; color:#888; }}
.bar-summary b {{ font-size:15px; }}
</style>
</head>
<body>
<div class="card">
  <div class="title">{mood} 全球股市周报</div>
  <div class="subtitle">{date_str} · 自动生成</div>
  <div class="week-range">{week_range}</div>
</div>
"""

    # A股指数
    if a_share:
        html += '<div class="card"><div class="section-title">🇨🇳 A股指数 · 本周涨跌</div>'
        sorted_a = sorted(a_share.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_a:
            cls = "red" if d["change_pct"] > 0 else "green"
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price">{d['start']:.0f} → <b>{d['end']:.0f}</b> <span class="{cls}">周{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # A股板块快照（东方财富当日数据+ETF周涨跌）
    if sector_weekly and len(sector_weekly) > 0:
        # 计算条形图最大绝对值用于比例
        max_abs = max(abs(d["change_pct"]) for d in sector_weekly.values())
        max_abs = max(max_abs, 0.5)  # 至少0.5%避免除零

        sorted_sec = sorted(sector_weekly.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        up_count = sum(1 for _, d in sorted_sec if d["change_pct"] > 0)
        down_count = sum(1 for _, d in sorted_sec if d["change_pct"] < 0)
        total = len(sorted_sec)

        html += '<div class="card"><div class="section-title">🔥 A股板块·本周涨跌</div>'

        # 汇总条
        html += f'<div class="bar-summary"><span>📈 上涨 <b class="red">{up_count}</b> 个</span><span>📉 下跌 <b class="green">{down_count}</b> 个</span><span>共 {total} 板块</span></div>'

        html += '<table class="bar-table">'
        for name, d in sorted_sec:
            pct = d["change_pct"]
            is_up = pct > 0
            cls = "red" if is_up else "green"
            emoji = "🔥" if pct > 3 else ("📈" if pct > 0 else ("📉" if pct < -3 else "⚪"))

            # 条形图宽度（百分比形式）
            bar_width = min(abs(pct) / max_abs * 100, 100)
            if is_up:
                bar_style = f"left:50%;width:{bar_width / 2}%;"
                bar_class = "up"
            else:
                bar_style = f"left:{50 - bar_width / 2}%;width:{bar_width / 2}%;"
                bar_class = "down"

            html += f"""<tr>
<td class="sector-name">{emoji} {name}</td>
<td class="bar-cell"><div class="bar-track"><div class="bar-fill {bar_class}" style="{bar_style}"></div></div></td>
<td class="bar-pct {cls}">{pct:+.2f}%</td>
</tr>"""
        html += "</table></div>"

    elif a_sectors:
        # 回退：东方财富快照
        html += '<div class="card"><div class="section-title">🔥 A股热门板块</div>'
        sorted_sec = sorted(a_sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_sec:
            cls = "red" if d["change_pct"] > 0 else "green"
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 美股
    if us_data:
        html += '<div class="card"><div class="section-title">🇺🇸 美股 · 本周涨跌</div>'
        sorted_u = sorted(us_data.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_u:
            cls = "red" if d["change_pct"] > 0 else "green"
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><span class="{cls}">周{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 日韩
    if asia_data:
        html += '<div class="card"><div class="section-title">🇯🇵🇰🇷 日韩 · 本周涨跌</div>'
        for name, d in asia_data.items():
            cls = "red" if d["change_pct"] > 0 else "green"
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><span class="{cls}">周{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 概念板块排行
    if concept_weekly and (concept_weekly.get("top") or concept_weekly.get("bottom")):
        html += '<div class="card"><div class="section-title">💡 概念板块排行</div>'
        if concept_weekly.get("top"):
            html += '<div style="margin-bottom:8px;"><span style="font-size:12px;color:#888;">领涨概念</span></div>'
            for c in concept_weekly["top"]:
                html += f"""<div class="idx">
  <span class="idx-name">🔥 {c['name']}</span>
  <span class="idx-price"><span class="red">{c['change_pct']:+.2f}%</span></span>
</div>"""
        if concept_weekly.get("bottom"):
            html += '<div style="margin:8px 0 4px;"><span style="font-size:12px;color:#888;">领跌概念</span></div>'
            for c in concept_weekly["bottom"]:
                html += f"""<div class="idx">
  <span class="idx-name">⚠️ {c['name']}</span>
  <span class="idx-price"><span class="green">{c['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 异动个股（涨幅榜 + 跌幅榜）
    if top_movers:
        gainers, losers = top_movers
        if gainers or losers:
            html += '<div class="card"><div class="section-title">🚀 异动个股 · 涨跌幅排行</div>'
            if gainers:
                html += '<div style="margin-bottom:4px;"><span style="font-size:12px;color:#888;">涨幅榜 TOP</span></div>'
                for g in gainers:
                    html += f"""<div class="idx">
  <span class="idx-name">🔴 {g['name']}</span>
  <span class="idx-price">¥{g['price']:.2f} <span class="red">{g['change_pct']:+.2f}%</span></span>
</div>"""
            if losers:
                html += '<div style="margin:8px 0 4px;"><span style="font-size:12px;color:#888;">跌幅榜 TOP</span></div>'
                for l in losers:
                    html += f"""<div class="idx">
  <span class="idx-name">🟢 {l['name']}</span>
  <span class="idx-price">¥{l['price']:.2f} <span class="green">{l['change_pct']:+.2f}%</span></span>
</div>"""
            html += "</div>"

    # 自选股周度回顾
    if watchlist:
        html += '<div class="card"><div class="section-title">💼 自选股 · 本周回顾</div>'
        sorted_w = sorted(watchlist.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_w:
            cls = "red" if d["change_pct"] > 0 else "green"
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price">{d['start']:.2f} → <b>{d['end']:.2f}</b> <span class="{cls}">周{d['change_pct']:+.2f}%</span></span>
</div>
<div class="idx" style="border:none;font-size:12px;color:#999;">
  <span>最高 {d['high']:.2f}</span><span>最低 {d['low']:.2f}</span>
</div>"""
        html += "</div>"

    # 周线技术信号
    if tech_signals:
        html += '<div class="card"><div class="section-title">📊 周线技术信号</div>'
        for t in tech_signals:
            html += f'<div style="margin:6px 0;"><b>{t["name"]}</b></div>'
            for s in t["signals"]:
                html += f'<div style="padding:2px 0 2px 12px;font-size:13px;line-height:1.6;">{s}</div>'
        html += "</div>"

    # 分析
    if analysis:
        html += f'<div class="card"><div class="section-title">📋 本周总结 & 下周展望</div><div class="analysis">{analysis.replace(chr(10), "<br>")}</div></div>'

    html += '<div class="footer">🕖 每周日 19:00 自动推送 · Powered by GitHub Actions</div></body></html>'
    return html


def send_webhook(a_share: dict, us_data: dict, asia_data: dict,
                 watchlist: dict = None, ai_text: str = None):
    """发送 Webhook 通知（企业微信/飞书）"""
    lines = ["📊 本周市场摘要"]
    if a_share:
        parts = [f"{n} {d['end']:.0f}({d['change_pct']:+.2f}%)" for n, d in a_share.items()]
        lines.append("A股：" + " | ".join(parts))
    if us_data:
        parts = [f"{n} {d['change_pct']:+.2f}%" for n, d in us_data.items()]
        lines.append("美股：" + " | ".join(parts))
    if asia_data:
        parts = [f"{n} {d['change_pct']:+.2f}%" for n, d in asia_data.items()]
        lines.append("日韩：" + " | ".join(parts))
    if watchlist:
        parts = [f"{n} {d['change_pct']:+.2f}%" for n, d in watchlist.items()]
        lines.append("自选股：" + " | ".join(parts))
    if ai_text:
        lines.append("")
        lines.append(ai_text[:300])
    msg = "\n".join(lines)

    # 企业微信
    wecom_url = os.environ.get("WECOM_WEBHOOK_URL", "")
    if wecom_url:
        try:
            payload = {"msgtype": "text", "text": {"content": msg}}
            r = _requests.post(wecom_url, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("errcode") == 0:
                print("[企微通知] 发送成功 ✓")
            else:
                print(f"[企微通知] 发送失败: {r.text}")
        except Exception as e:
            print(f"[企微通知] 发送失败: {e}")

    # 飞书
    feishu_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if feishu_url:
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "📊 全球股市周报"}},
                    "elements": [{"tag": "markdown", "content": msg}]
                }
            }
            r = _requests.post(feishu_url, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("code", -1) == 0:
                print("[飞书通知] 发送成功 ✓")
            else:
                print(f"[飞书通知] 发送失败: {r.text}")
        except Exception as e:
            print(f"[飞书通知] 发送失败: {e}")


def send_email(html_content: str, subject: str):
    """发送HTML邮件"""
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15)
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        server.quit()
        print("[邮件] 发送成功 ✓")
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")
        raise


def main():
    BJ_TZ = timezone(timedelta(hours=8))
    now = datetime.now(BJ_TZ)
    print(f"[周报] 开始生成 {now.strftime('%Y-%m-%d %H:%M:%S')} 北京时间")

    # 计算本周一和上周五
    weekday = now.weekday()
    monday = now - timedelta(days=weekday)
    friday = monday + timedelta(days=4)
    week_range = f"{monday.strftime('%m/%d')}（周一）- {friday.strftime('%m/%d')}（周五）"

    date_str = now.strftime("%Y年%m月%d日")

    # 1. A股周数据
    print("[数据] 获取A股本周数据...")
    a_share = fetch_weekly_data(A_SHARE_WEEKLY)
    print(f"  → 获取到 {len(a_share)} 个指数")

    # 2. 美股周数据
    print("[数据] 获取美股本周数据...")
    us_data = fetch_weekly_data(US_WEEKLY)
    print(f"  → 获取到 {len(us_data)} 个指数")

    # 3. 日韩周数据
    print("[数据] 获取日韩本周数据...")
    asia_data = fetch_weekly_data(ASIA_WEEKLY)
    print(f"  → 获取到 {len(asia_data)} 个指数")

    # 4. A股板块快照
    print("[数据] 获取A股板块快照...")
    a_sectors = fetch_a_sectors_snapshot()
    print(f"  → 获取到 {len(a_sectors)} 个板块")

    # 4.5 A股板块ETF周涨跌
    print("[数据] 获取A股板块ETF周涨跌...")
    sector_weekly = fetch_sector_weekly_data()
    print(f"  → 获取到 {len(sector_weekly)} 个板块周数据")

    # 4.8 自选股本周表现
    print("[数据] 获取自选股本周数据...")
    watchlist = fetch_watchlist_weekly()
    print(f"  → 获取到 {len(watchlist)} 只自选股")

    # 4.9 概念板块排行
    print("[数据] 获取概念板块排行...")
    concept_weekly = fetch_concept_sector_ranking_weekly()
    print(f"  → 涨幅 {len(concept_weekly.get('top', []))} / 跌幅 {len(concept_weekly.get('bottom', []))}")

    # 4.10 异动个股（涨幅榜/跌幅榜）
    print("[数据] 获取异动个股排行...")
    top_movers = fetch_top_movers_weekly()
    print(f"  → 涨幅榜 {len(top_movers[0])} / 跌幅榜 {len(top_movers[1])}")

    # 4.11 周线技术信号
    print("[数据] 计算周线技术信号...")
    tech_symbols = {**A_SHARE_WEEKLY}
    for name, secid in list(WATCHLIST.items())[:3]:
        tech_symbols[name] = _secid_to_yfinance(secid)
    tech_signals = analyze_weekly_strategy(tech_symbols)
    print(f"  → 获取到 {len(tech_signals)} 个标的信号")

    # 5. 生成分析
    print("[分析] 生成周报...")
    analysis = generate_weekly_analysis(a_share, us_data, asia_data, a_sectors, week_range,
                                        sector_weekly, watchlist, concept_weekly, top_movers, tech_signals)

    # 6. HTML邮件
    html = generate_html_weekly(date_str, week_range, a_share, us_data, asia_data, a_sectors, analysis,
                                sector_weekly, watchlist, concept_weekly, top_movers, tech_signals)

    # 7. 发送
    print("[邮件] 发送中...")
    subject = f"📊 全球股市周报 - {week_range}"
    send_email(html, subject)

    # 8. Webhook 通知
    print("[通知] 发送 Webhook 通知...")
    send_webhook(a_share, us_data, asia_data, watchlist, analysis[:300] if analysis else None)

    print("[完成] 周报生成完毕 ✓")


if __name__ == "__main__":
    main()
