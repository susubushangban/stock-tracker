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

# ============================================================
# 配置
# ============================================================
EMAIL_FROM = "972548750@qq.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "972548750@qq.com")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

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
    """获取A股板块当前快照"""
    results = {}
    import urllib.request

    for name, code in A_SECTORS_WEEKLY.items():
        url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={code}&fields=f43,f57,f58,f169,f170"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            d = data.get("data")
            if d and d.get("f57"):
                results[name] = {
                    "name": name,
                    "price": float(d.get("f43", 0)),
                    "change_pct": float(d.get("f170", 0)),
                    "change": float(d.get("f169", 0)),
                }
        except Exception as e:
            print(f"  ✗ 板块{name}: {e}")

    return results


def ai_weekly_outlook(a_share: dict, us_data: dict, asia_data: dict,
                       a_sectors: dict, sector_weekly: dict, week_range: str) -> Optional[str]:
    """使用DeepSeek API生成下周展望分析"""
    if not DEEPSEEK_API_KEY:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        # 构建数据摘要
        data_summary = json.dumps({
            "本周交易区间": week_range,
            "A股指数周涨跌": {k: f"{v['start']:.2f}→{v['end']:.2f}({v['change_pct']:+.2f}%)" for k, v in a_share.items()},
            "美股周涨跌": {k: f"{v['change_pct']:+.2f}%" for k, v in us_data.items()},
            "日韩周涨跌": {k: f"{v['change_pct']:+.2f}%" for k, v in asia_data.items()},
            "A股板块ETF周涨跌": {k: f"{v['change_pct']:+.2f}%" for k, v in sector_weekly.items()} if sector_weekly else {},
            "A股板块当日快照": {k: f"{v['change_pct']:+.2f}%" for k, v in a_sectors.items()},
        }, ensure_ascii=False, indent=2)

        prompt = f"""你是资深股市分析师。以下是本周全球市场数据（JSON格式）：

{data_summary}

请基于本周各市场表现，用400字以内分析下周A股可能的变动方向：
1. 结合本周全球市场走势，判断下周A股整体可能偏多还是偏空
2. 哪些板块下周可能延续强势或转弱，给出具体板块名称
3. 需要关注的潜在风险点或机会点（如政策面、外围市场、资金流向等）

要求：语言通俗易懂，观点明确，适合非专业投资者阅读。"""

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[AI分析] 下周展望调用失败: {e}")
        return None


def generate_weekly_analysis(a_share: dict, us_data: dict, asia_data: dict,
                              a_sectors: dict, week_range: str, sector_weekly: dict = None) -> str:
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

    # 下周展望（AI生成）
    lines.append("【🔮 下周展望】")
    ai_outlook = ai_weekly_outlook(a_share, us_data, asia_data, a_sectors, sector_weekly, week_range)
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
                          sector_weekly: dict = None) -> str:
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

    # 分析
    if analysis:
        html += f'<div class="card"><div class="section-title">📋 本周总结 & 下周展望</div><div class="analysis">{analysis.replace(chr(10), "<br>")}</div></div>'

    html += '<div class="footer">🕖 每周日 19:00 自动推送 · Powered by GitHub Actions</div></body></html>'
    return html


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

    # 5. 生成分析
    print("[分析] 生成周报...")
    analysis = generate_weekly_analysis(a_share, us_data, asia_data, a_sectors, week_range, sector_weekly)

    # 6. HTML邮件
    html = generate_html_weekly(date_str, week_range, a_share, us_data, asia_data, a_sectors, analysis, sector_weekly)

    # 7. 发送
    print("[邮件] 发送中...")
    subject = f"📊 全球股市周报 - {week_range}"
    send_email(html, subject)

    print("[完成] 周报生成完毕 ✓")


if __name__ == "__main__":
    main()
