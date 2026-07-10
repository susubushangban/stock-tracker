"""
股市每日追踪报告
每天早上7:30自动抓取A股、美股、日韩市场数据，分析后发送邮件
"""
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

# ============================================================
# 配置区（GitHub Actions中通过环境变量/Secrets设置）
# ============================================================

EMAIL_FROM = "972548750@qq.com"       # 发件邮箱
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "972548750@qq.com")

# DeepSeek API（可选，不配置则使用规则分析）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# ============================================================
# 追踪标的定义
# ============================================================

# A股主要指数
A_SHARE_INDICES = {
    "上证指数": "000001",
    "深证成指": "399001",
    "沪深300":  "000300",
    "创业板指": "399006",
}

# 美股主要指数（yfinance代码）
US_INDICES = {
    "道琼斯工业": "^DJI",
    "纳斯达克":   "^IXIC",
    "标普500":    "^GSPC",
}

# 日韩指数
ASIA_INDICES = {
    "日经225": "^N225",
    "韩国KOSPI": "^KS11",
    "韩国KOSDAQ": "^KQ11",
}

# 关注的行业板块（美股ETF作为风向标）
SECTOR_ETFS = {
    "科技":     "XLK",
    "金融":     "XLF",
    "能源":     "XLE",
    "医疗健康": "XLV",
    "消费":     "XLP",
    "工业":     "XLI",
    "半导体":   "SMH",
    "房地产":   "XLRE",
}


def fetch_a_share_sina() -> dict:
    """通过新浪接口获取A股指数数据（稳定、免费、无需akshare）"""
    results = {}
    codes_str = ",".join([f"sh{v}" if v.startswith("0") else f"sz{v}" for v in A_SHARE_INDICES.values()])
    url = f"https://hq.sinajs.cn/list={codes_str}"

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        resp = urllib.request.urlopen(req, timeout=15)
        text = resp.read().decode("gbk")

        name_to_code = {v: k for k, v in A_SHARE_INDICES.items()}
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split('"')
            if len(parts) < 2:
                continue
            data = parts[1].split(",")
            if len(data) < 4:
                continue
            name = data[0]
            if name in name_to_code:
                results[name] = {
                    "name": name,
                    "price": float(data[1]) if data[1] else 0,
                    "change": float(data[2]) if data[2] else 0,
                    "change_pct": float(data[3]) if data[3] else 0,
                    "volume": data[4] if len(data) > 4 else "",
                }
    except Exception as e:
        print(f"[A股] 新浪接口获取失败: {e}")

    return results


def fetch_yfinance_data(symbols: dict) -> dict:
    """通过yfinance获取美股/日韩数据"""
    results = {}
    for name, code in symbols.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            if hist.empty:
                print(f"[警告] {name}({code}) 无数据")
                continue

            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest

            change = latest["Close"] - prev["Close"]
            change_pct = (change / prev["Close"]) * 100

            results[name] = {
                "name": name,
                "code": code,
                "price": round(float(latest["Close"]), 2),
                "change": round(float(change), 2),
                "change_pct": round(float(change_pct), 2),
                "volume": int(latest["Volume"]) if "Volume" in latest else 0,
                "high": round(float(latest["High"]), 2),
                "low": round(float(latest["Low"]), 2),
            }
        except Exception as e:
            print(f"[错误] {name}({code}): {e}")

    return results


def fetch_sector_data() -> dict:
    """获取美股板块ETF数据"""
    return fetch_yfinance_data(SECTOR_ETFS)


def rule_analysis(a_share: dict, us_data: dict, asia_data: dict, sectors: dict) -> str:
    """基于规则的数据分析（不依赖外部AI API）"""
    lines = []
    lines.append("【📊 市场概览】\n")

    # A股分析
    if a_share:
        lines.append("▎A股市场：")
        up_count = sum(1 for v in a_share.values() if v["change_pct"] > 0)
        down_count = sum(1 for v in a_share.values() if v["change_pct"] < 0)
        for name, d in a_share.items():
            emoji = "🔴" if d["change_pct"] > 0 else ("🟢" if d["change_pct"] < 0 else "⚪")
            lines.append(f"  {emoji} {name}: {d['price']:.2f}  ({d['change_pct']:+.2f}%)")
        if up_count > down_count:
            lines.append("  → 整体偏强，多数指数上涨")
        elif down_count > up_count:
            lines.append("  → 整体偏弱，多数指数下跌")
        else:
            lines.append("  → 涨跌互现，市场分歧")
        lines.append("")

    # 美股分析
    if us_data:
        lines.append("▎美股市场：")
        for name, d in us_data.items():
            emoji = "🔴" if d["change_pct"] > 0 else ("🟢" if d["change_pct"] < 0 else "⚪")
            lines.append(f"  {emoji} {name}: {d['price']:.2f}  ({d['change_pct']:+.2f}%)")
        lines.append("")

    # 日韩分析
    if asia_data:
        lines.append("▎日韩市场：")
        for name, d in asia_data.items():
            emoji = "🔴" if d["change_pct"] > 0 else ("🟢" if d["change_pct"] < 0 else "⚪")
            lines.append(f"  {emoji} {name}: {d['price']:.2f}  ({d['change_pct']:+.2f}%)")
        lines.append("")

    # 板块分析
    if sectors:
        lines.append("【🏭 行业板块风向】")
        sorted_sectors = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        top3 = sorted_sectors[:3]
        bottom3 = sorted_sectors[-3:]

        lines.append("  领涨板块：")
        for name, d in top3:
            lines.append(f"    🔥 {name}: {d['change_pct']:+.2f}%")

        lines.append("  领跌板块：")
        for name, d in reversed(bottom3):
            lines.append(f"    ❄️ {name}: {d['change_pct']:+.2f}%")

        # 行业影响推断
        lines.append("")
        lines.append("【💡 影响推断】")
        for name, d in top3:
            if d["change_pct"] > 1:
                if name == "科技":
                    lines.append(f"  • 科技板块走强 → 利好A股人工智能、半导体、软件板块")
                elif name == "半导体":
                    lines.append(f"  • 半导体走强 → 利好芯片产业链、消费电子板块")
                elif name == "能源":
                    lines.append(f"  • 能源板块走强 → 利好石油、煤炭、新能源板块；需关注大宗商品价格")
                elif name == "金融":
                    lines.append(f"  • 金融板块走强 → 利好银行、保险、券商板块；市场风险偏好上升")
                elif name == "医疗健康":
                    lines.append(f"  • 医药板块走强 → 利好创新药、医疗器械板块")
                elif name == "消费":
                    lines.append(f"  • 消费板块走强 → 利好食品饮料、零售、电商板块")
        for name, d in bottom3:
            if d["change_pct"] < -1:
                if name == "科技":
                    lines.append(f"  • 科技板块走弱 → A股科技板块可能承压，注意回避高估值标的")
                elif name == "能源":
                    lines.append(f"  • 能源板块走弱 → 可能拖累资源类板块，对新能源或是利好（替代效应）")

    return "\n".join(lines)


def ai_deep_analysis(a_share: dict, us_data: dict, asia_data: dict, sectors: dict) -> Optional[str]:
    """使用DeepSeek API进行深度AI分析（需要配置DEEPSEEK_API_KEY）"""
    if not DEEPSEEK_API_KEY:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        # 构建数据摘要
        data_summary = json.dumps({
            "A股": {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in a_share.items()},
            "美股": {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in us_data.items()},
            "日韩": {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in asia_data.items()},
            "板块": {k: f"{v['change_pct']:+.2f}%" for k, v in sectors.items()},
        }, ensure_ascii=False, indent=2)

        prompt = f"""你是资深股市分析师。以下是今日全球市场数据（JSON格式）：

{data_summary}

请用300字以内，简明扼要地：
1. 总结各市场整体表现
2. 分析可能对A股相关行业/板块产生的影响
3. 标注1-2个值得关注的风险点或机会

要求：语言通俗易懂，适合非专业投资者阅读。"""

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=600,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[AI分析] 调用失败: {e}")
        return None


def generate_html_report(date_str: str, a_share: dict, us_data: dict, asia_data: dict,
                          sectors: dict, rule_text: str, ai_text: Optional[str]) -> str:
    """生成HTML格式的邮件报告"""
    # 判断整体涨跌
    all_pct = []
    for d in list(a_share.values()) + list(us_data.values()) + list(asia_data.values()):
        if d.get("change_pct"):
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
.analysis-ai {{ line-height:1.8; white-space:pre-wrap; font-size:13px;
                background:#fef9e7; padding:12px; border-radius:8px; border-left:3px solid #f39c12; }}
.footer {{ text-align:center; color:#bbb; font-size:11px; margin-top:16px; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; margin:2px;
        background:#e8f4fd; color:#2980b9; }}
</style>
</head>
<body>
<div class="card">
  <div class="title">{mood} 全球股市日报</div>
  <div class="subtitle">{date_str} · 自动生成</div>
</div>
"""

    # A股
    if a_share:
        html += '<div class="card"><div class="section-title">🇨🇳 A股市场</div>'
        for name, d in a_share.items():
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><b>{d['price']:.2f}</b> <span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 美股
    if us_data:
        html += '<div class="card"><div class="section-title">🇺🇸 美股市场</div>'
        for name, d in us_data.items():
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><b>{d['price']:.2f}</b> <span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 日韩
    if asia_data:
        html += '<div class="card"><div class="section-title">🇯🇵🇰🇷 日韩市场</div>'
        for name, d in asia_data.items():
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><b>{d['price']:.2f}</b> <span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 板块风向
    if sectors:
        html += '<div class="card"><div class="section-title">🏭 板块风向标</div>'
        sorted_sec = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_sec:
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            if abs(d["change_pct"]) > 0.3:
                html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # AI分析或规则分析
    if ai_text:
        html += f'<div class="card"><div class="section-title">🤖 AI深度分析</div><div class="analysis-ai">{ai_text}</div></div>'
    elif rule_text:
        html += f'<div class="card"><div class="section-title">📋 智能分析</div><div class="analysis">{rule_text.replace(chr(10), "<br>")}</div></div>'

    html += '<div class="footer">🕖 每日 7:30 自动推送 · Powered by GitHub Actions</div></body></html>'
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
    print(f"[开始] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    today = datetime.now()
    date_str = today.strftime("%Y年%m月%d日")

    # 如果是周末，使用上周五的数据
    weekday = today.weekday()
    if weekday == 5:  # 周六
        date_str = (today - timedelta(days=1)).strftime("%Y年%m月%d日")
    elif weekday == 6:  # 周日
        date_str = (today - timedelta(days=2)).strftime("%Y年%m月%d日")

    # 1. 抓取A股数据
    print("[数据] 获取A股数据...")
    a_share = fetch_a_share_sina()
    print(f"  → 获取到 {len(a_share)} 个指数")

    # 2. 抓取美股数据
    print("[数据] 获取美股数据...")
    us_data = fetch_yfinance_data(US_INDICES)
    print(f"  → 获取到 {len(us_data)} 个指数")

    # 3. 抓取日韩数据
    print("[数据] 获取日韩数据...")
    asia_data = fetch_yfinance_data(ASIA_INDICES)
    print(f"  → 获取到 {len(asia_data)} 个指数")

    # 4. 抓取板块数据
    print("[数据] 获取板块数据...")
    sectors = fetch_sector_data()
    print(f"  → 获取到 {len(sectors)} 个板块")

    # 5. 规则分析
    print("[分析] 执行规则分析...")
    rule_text = rule_analysis(a_share, us_data, asia_data, sectors)

    # 6. AI深度分析（如果配置了API Key）
    ai_text = ai_deep_analysis(a_share, us_data, asia_data, sectors)
    if ai_text:
        print("[AI] DeepSeek分析完成")
    else:
        print("[AI] 未配置API Key，跳过AI分析")

    # 7. 生成HTML邮件
    print("[报告] 生成报告...")
    html = generate_html_report(date_str, a_share, us_data, asia_data, sectors, rule_text, ai_text)

    # 8. 发送邮件
    print("[邮件] 发送中...")
    subject = f"📊 全球股市日报 - {date_str}"
    send_email(html, subject)

    print("[完成] 全部任务执行完毕 ✓")


if __name__ == "__main__":
    main()
