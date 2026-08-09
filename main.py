"""
股市每日追踪报告
每天早上7:30自动抓取A股、美股、日韩市场数据，分析后发送邮件
"""
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests as _requests
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

# A股热门板块（东方财富板块代码，90.xxx格式）
# 已改为动态获取：fetch_a_share_sectors() 自动从东方财富获取当日行业板块排行 TOP10
# 不再需要硬编码列表

# 自选股/持仓列表
# 优先从 GitHub Secret WATCHLIST_CONFIG 读取
# 格式：名称:股票代码,名称:股票代码（市场前缀自动识别，无需手动填写）
# 示例：贵州茅台:600519,宁德时代:300750,比亚迪:002594
def _auto_market(code: str) -> str:
    """根据股票代码自动识别市场：6开头=上海(1)，0/3开头=深圳(0)"""
    code = code.strip()
    if code.startswith("6"):
        return f"1.{code}"
    elif code.startswith("0") or code.startswith("3"):
        return f"0.{code}"
    return code  # 已带前缀则原样返回

def _parse_watchlist() -> dict:
    # 1. 优先从 watchlist.json 文件读取（Web 管理面板维护）
    wl_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
    if os.path.exists(wl_file):
        try:
            with open(wl_file, encoding="utf-8") as f:
                data = json.load(f)
            if data:
                print(f"[配置] 从 watchlist.json 加载自选股: {list(data.keys())}")
                return data
        except Exception as e:
            print(f"[配置] watchlist.json 读取失败: {e}")
    # 2. 回退到 WATCHLIST_CONFIG 环境变量（GitHub Secret）
    config = os.environ.get("WATCHLIST_CONFIG", "")
    if config.strip():
        result = {}
        for item in config.split(","):
            item = item.strip()
            if ":" in item:
                name, code = item.split(":", 1)
                result[name.strip()] = _auto_market(code)
        if result:
            print(f"[配置] 从 Secrets 加载自选股: {list(result.keys())}")
            return result
    # 3. 默认列表
    return {
        "贵州茅台": "1.600519",
        "宁德时代": "0.300750",
        "比亚迪":   "0.002594",
    }

WATCHLIST = _parse_watchlist()


def load_customers() -> list:
    """加载多客户配置（customers.json），支持多客户模式"""
    customers_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customers.json")
    if os.path.exists(customers_file):
        try:
            with open(customers_file, encoding="utf-8") as f:
                data = json.load(f)
            customers = data.get("customers", [])
            enabled = [c for c in customers if c.get("enabled", True)]
            if enabled:
                print(f"[配置] 从 customers.json 加载 {len(enabled)} 个客户")
                return enabled
        except Exception as e:
            print(f"[配置] customers.json 读取失败: {e}")
    # 无 customers.json 时，回退单客户模式
    print("[配置] 使用单客户模式（watchlist.json / Secrets）")
    return [{
        "id": "000",
        "name": "默认用户",
        "email": os.environ.get("EMAIL_TO", "972548750@qq.com"),
        "watchlist": WATCHLIST,
        "wecom_webhook": os.environ.get("WECOM_WEBHOOK_URL", ""),
        "feishu_webhook": os.environ.get("FEISHU_WEBHOOK_URL", ""),
        "enabled": True,
    }]


def _fix_api_scale(price: float, value: float) -> float:
    """自动校正东方财富API数据精度（价格>10万说明是分为单位，需÷100）"""
    if abs(price) > 100000:
        return value / 100
    return value


# 热门个股列表（yfinance 备用源，用于东方财富失败时获取涨跌幅）
POPULAR_STOCKS_YF = {
    "贵州茅台": "600519.SS", "宁德时代": "300750.SZ", "比亚迪": "002594.SZ",
    "招商银行": "600036.SS", "中国平安": "601318.SS", "隆基绿能": "601012.SS",
    "药明康德": "603259.SS", "立讯精密": "002475.SZ", "美的集团": "000333.SZ",
    "格力电器": "000651.SZ", "五粮液": "000858.SZ", "中国中免": "601888.SS",
    "哈药股份": "600664.SS", "赣锋锂业": "002460.SZ", "紫光国微": "002049.SZ",
    "中芯国际": "688981.SS", "海光信息": "688041.SS", "寒武纪": "688256.SS",
    "科大讯飞": "002230.SZ", "三六零": "601360.SS", "东方财富": "300059.SZ",
    "中信证券": "600030.SS", "海天味业": "603288.SS", "恒瑞医药": "600276.SS",
    "长春高新": "000661.SZ", "迈瑞医疗": "300760.SZ", "片仔癀": "600436.SS",
    "中国神华": "601088.SS", "兖矿能源": "600188.SS", "长江电力": "600900.SS",
}


def fetch_top_movers_yfinance(top_n: int = 8) -> tuple:
    """通过 yfinance 获取热门个股涨跌幅（备用源）"""
    gainers = []
    losers = []
    for name, code in POPULAR_STOCKS_YF.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            change = latest["Close"] - prev["Close"]
            change_pct = (change / prev["Close"]) * 100
            if not _is_valid_pct(change_pct):
                continue
            item = {
                "name": name,
                "code": code.split(".")[0],
                "price": round(float(latest["Close"]), 2),
                "change_pct": round(float(change_pct), 2),
            }
            if change_pct > 0:
                gainers.append(item)
            else:
                losers.append(item)
        except Exception:
            pass
    # 排序取前N
    gainers.sort(key=lambda x: x["change_pct"], reverse=True)
    losers.sort(key=lambda x: x["change_pct"])
    gainers = gainers[:top_n]
    losers = losers[:top_n]
    if gainers or losers:
        print(f"  ✓ [备用] 涨幅榜{len(gainers)}只，跌幅榜{len(losers)}只（yfinance）")
    return gainers, losers


def fetch_top_movers(top_n: int = 8) -> tuple:
    """获取A股涨幅榜和跌幅榜前N个股（东方财富优先，yfinance备用）"""
    import urllib.request

    top_gainers = []
    top_losers = []
    headers = {"User-Agent": "Mozilla/5.0"}

    # 涨幅榜（按涨跌幅降序）
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
            # 只过滤*ST，保留ST和N开头的新股（新股涨幅有参考价值）
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
        print(f"  ✓ 涨幅榜: 获取到 {len(top_gainers)} 只")
    except Exception as e:
        print(f"  ✗ 涨幅榜获取失败: {e}")

    # 跌幅榜（按涨跌幅升序）
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
        print(f"  ✓ 跌幅榜: 获取到 {len(top_losers)} 只")
    except Exception as e:
        print(f"  ✗ 跌幅榜获取失败: {e}")

    # 东方财富失败时，切换 yfinance 备用源
    if len(top_gainers) < 3 and len(top_losers) < 3:
        print("  → 东方财富数据不足，切换 yfinance 备用源...")
        top_gainers, top_losers = fetch_top_movers_yfinance(top_n)

    return top_gainers, top_losers


def fetch_concept_sector_ranking(top_n: int = 6) -> dict:
    """获取A股概念板块涨幅榜和跌幅榜（东方财富API）"""
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
        print(f"  ✗ 概念板块涨幅榜获取失败: {e}")

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
        print(f"  ✗ 概念板块跌幅榜获取失败: {e}")

    return results


# A股行业板块 ETF 映射（yfinance 备用源）
SECTOR_ETFS_YF = {
    "银行": "512800.SS",
    "非银金融": "512070.SS",
    "房地产": "150770.SZ",
    "食品饮料": "515170.SS",
    "医药生物": "512010.SS",
    "电子": "159997.SZ",
    "计算机": "512720.SS",
    "电力设备": "159752.SZ",
    "汽车": "516110.SS",
    "机械设备": "516010.SS",
    "有色金属": "512400.SS",
    "钢铁": "515210.SS",
    "煤炭": "515220.SS",
    "石油石化": "159697.SZ",
    "通信": "515880.SS",
    "传媒": "512980.SS",
}


def fetch_a_share_sectors_yfinance() -> dict:
    """通过 yfinance 获取 A 股行业板块涨跌（备用源，使用行业 ETF）"""
    results = {}
    for name, code in SECTOR_ETFS_YF.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            if hist.empty or len(hist) < 2:
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            change = latest["Close"] - prev["Close"]
            change_pct = (change / prev["Close"]) * 100
            if not _is_valid_pct(change_pct):
                continue
            results[name] = {
                "name": name,
                "price": round(float(latest["Close"]), 3),
                "change_pct": round(float(change_pct), 2),
                "change": round(float(change), 3),
            }
        except Exception as e:
            print(f"  ✗ [备用] {name}: {e}")
    if results:
        # 按涨跌幅排序，取前10
        sorted_items = sorted(results.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        results = dict(sorted_items[:10])
        print(f"  ✓ 行业板块排行: 获取到 {len(results)} 个（yfinance 备用源）")
    return results


def fetch_a_share_sectors(top_n: int = 10) -> dict:
    """动态获取A股行业板块排行（东方财富API优先，yfinance备用）"""
    results = {}
    import urllib.request
    headers = {"User-Agent": "Mozilla/5.0"}

    # 获取行业板块涨幅排行（m:90+t:2 = 行业板块）
    url = (
        f"http://push2.eastmoney.com/api/qt/clist/get?"
        f"pn=1&pz={top_n}&po=1&np=1&fltt=2&invt=2&fid=f3"
        f"&fs=m:90+t:2"
        f"&fields=f2,f3,f4,f12,f14"
    )
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("diff", []):
            name = item.get("f14", "")
            pct = float(item.get("f3", 0))
            if not _is_valid_pct(pct):
                print(f"  ⚠ 板块 {name}: 涨跌幅异常({pct}%)，跳过")
                continue
            results[name] = {
                "name": name,
                "price": float(item.get("f2", 0)),
                "change_pct": pct,
                "change": float(item.get("f4", 0)),
            }
        print(f"  ✓ 行业板块排行: 获取到 {len(results)} 个（动态）")
    except Exception as e:
        print(f"  ✗ 行业板块排行获取失败: {e}")

    # 东方财富失败时，切换 yfinance 备用源
    if len(results) < 3:
        print("  → 东方财富数据不足，切换 yfinance 备用源...")
        results = fetch_a_share_sectors_yfinance()

    return results


def _is_valid_pct(pct: float) -> bool:
    """检查涨跌幅是否在合理范围内（A股±22%，含ST和新股浮动）"""
    return -22 <= pct <= 22


def fetch_a_share_yfinance() -> dict:
    """通过yfinance获取A股指数数据（从GitHub服务器访问稳定可靠）"""
    yf_mapping = {
        "上证指数": "000001.SS",
        "深证成指": "399001.SZ",
        "沪深300":  "000300.SS",
        "创业板指": "399006.SZ",
    }
    results = {}
    for name, code in yf_mapping.items():
        try:
            ticker = yf.Ticker(code)
            hist = ticker.history(period="5d")
            if hist.empty:
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            change = latest["Close"] - prev["Close"]
            change_pct = (change / prev["Close"]) * 100
            results[name] = {
                "name": name,
                "price": round(float(latest["Close"]), 2),
                "change": round(float(change), 2),
                "change_pct": round(float(change_pct), 2),
                "volume": str(int(latest.get("Volume", 0))),
                "high": round(float(latest["High"]), 2),
                "low": round(float(latest["Low"]), 2),
            }
            print(f"  ✓ {name}: {results[name]['price']:.2f} ({results[name]['change_pct']:+.2f}%)")
        except Exception as e:
            print(f"  ✗ {name}获取失败: {e}")
    return results


def fetch_a_share_eastmoney_fallback() -> dict:
    """通过东方财富API获取A股指数（yfinance失败时的备用方案）"""
    results = {}
    import urllib.request

    for name, code in A_SHARE_INDICES.items():
        market = "1" if code.startswith("0") else "0"
        secid = f"{market}.{code}"
        url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fltt=2&fields=f43,f44,f45,f46,f47,f48,f57,f58,f169,f170"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            d = data.get("data")
            if d and d.get("f57"):
                price = float(d.get("f43", 0))
                pct = float(d.get("f170", 0))
                if price <= 0 or not _is_valid_pct(pct):
                    print(f"  ⚠ {name}: 数据异常(price={price}, pct={pct})，跳过")
                    continue
                results[name] = {
                    "name": name,
                    "price": price,
                    "change": float(d.get("f169", 0)),
                    "change_pct": pct,
                    "volume": str(d.get("f47", "")),
                    "high": float(d.get("f44", 0)),
                    "low": float(d.get("f45", 0)),
                }
                print(f"  ✓ [备用] {name}: {price:.2f} ({pct:+.2f}%)")
        except Exception as e:
            print(f"  ✗ [备用] {name}获取失败: {e}")
    return results


def _stock_to_yfinance(secid: str) -> str:
    """将东方财富格式(1.600519)转为yfinance格式(600519.SS)"""
    if "." in secid:
        market, code = secid.split(".", 1)
        suffix = "SS" if market == "1" else "SZ"
        return f"{code}.{suffix}"
    return secid


def fetch_watchlist_data(watchlist: dict = None) -> dict:
    """获取自选股/持仓个股实时行情（东方财富优先，失败则yfinance备用）"""
    import urllib.request
    results = {}
    wl = watchlist if watchlist is not None else WATCHLIST
    for name, code in wl.items():
        # 使用更完整的字段：f48=成交额, f168=换手率, f50=量比
        url = f"http://push2.eastmoney.com/api/qt/stock/get?secid={code}&fltt=2&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f168,f169,f170,f171"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            d = data.get("data")
            if d and d.get("f57"):
                price = float(d.get("f43", 0))
                pct = float(d.get("f170", 0))
                if price <= 0 or not _is_valid_pct(pct):
                    print(f"  ⚠ {name}: 东方财富数据异常(price={price}, pct={pct}%)，切换备用源")
                    raise ValueError(f"数据异常: pct={pct}")
                # 成交额格式化（元转万元/亿元）
                amount = float(d.get("f48", 0))
                if amount >= 1e8:
                    amount_str = f"{amount/1e8:.2f}亿"
                elif amount >= 1e4:
                    amount_str = f"{amount/1e4:.2f}万"
                else:
                    amount_str = f"{amount:.0f}"
                # 换手率和量比（某些情况下可能返回 None 或 '-'）
                turnover_raw = d.get("f168")
                volume_ratio_raw = d.get("f50")
                turnover = float(turnover_raw) if turnover_raw and turnover_raw != '-' else 0
                volume_ratio = float(volume_ratio_raw) if volume_ratio_raw and volume_ratio_raw != '-' else 0
                results[name] = {
                    "name": name,
                    "price": price,
                    "change": float(d.get("f169", 0)),
                    "change_pct": pct,
                    "high": float(d.get("f44", 0)),
                    "low": float(d.get("f45", 0)),
                    "volume": str(d.get("f47", "")),
                    "amount": amount_str,  # 成交额
                    "turnover": turnover,  # 换手率 %
                    "volume_ratio": volume_ratio,  # 量比
                }
                print(f"  ✓ {name}: {price:.2f} ({pct:+.2f}%) 换手:{turnover:.2f}% 成交额:{amount_str} 量比:{volume_ratio:.2f}")
                continue
        except Exception as e:
            print(f"  ↻ {name} 东方财富失败({e})，尝试yfinance...")
        # yfinance 备用
        try:
            yf_code = _stock_to_yfinance(code)
            ticker = yf.Ticker(yf_code)
            hist = ticker.history(period="5d")
            if hist.empty:
                print(f"  ✗ {name}: yfinance无数据")
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            change = latest["Close"] - prev["Close"]
            change_pct = (change / prev["Close"]) * 100
            # 成交额计算（价格*成交量）
            amount = latest["Close"] * latest.get("Volume", 0)
            if amount >= 1e8:
                amount_str = f"{amount/1e8:.2f}亿"
            elif amount >= 1e4:
                amount_str = f"{amount/1e4:.2f}万"
            else:
                amount_str = f"{amount:.0f}"
            # yfinance 无法直接获取换手率和量比，用默认值
            results[name] = {
                "name": name,
                "price": round(float(latest["Close"]), 2),
                "change": round(float(change), 2),
                "change_pct": round(float(change_pct), 2),
                "high": round(float(latest["High"]), 2),
                "low": round(float(latest["Low"]), 2),
                "volume": str(int(latest.get("Volume", 0))),
                "amount": amount_str,  # 成交额
                "turnover": 0,  # 换手率（yfinance无法获取）
                "volume_ratio": 0,  # 量比（yfinance无法获取）
            }
            print(f"  ✓ [备用] {name}: {results[name]['price']:.2f} ({results[name]['change_pct']:+.2f}%)")
        except Exception as e2:
            print(f"  ✗ {name}: yfinance也失败({e2})")
    return results


def fetch_market_news(top_n: int = 8) -> list:
    """获取最新财经新闻（东方财富滚动新闻）"""
    import urllib.request
    news = []
    url = (f"https://push2ex.eastmoney.com/getAllStockNewsList?"
           f"pageSize={top_n}&pageNo=1&fields=title,showTime,url")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("data", {}).get("list", []):
            news.append({
                "title": item.get("title", ""),
                "time": item.get("showTime", ""),
            })
        print(f"  ✓ 获取到 {len(news)} 条新闻")
    except Exception as e:
        print(f"  ✗ 新闻获取失败: {e}")
    return news


def fetch_kline_eastmoney(secid: str, days: int = 60) -> list:
    """获取东方财富日K线历史数据"""
    import urllib.request
    url = (f"http://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
           f"&fields2=f51,f52,f53,f54,f55,f56,f57"
           f"&klt=101&fqt=1&lmt={days}&end=20500101")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        klines = []
        for line in data.get("data", {}).get("klines", []):
            parts = line.split(",")
            klines.append({
                "date": parts[0], "open": float(parts[1]),
                "close": float(parts[2]), "high": float(parts[3]),
                "low": float(parts[4]), "volume": float(parts[5]),
            })
        return klines
    except Exception as e:
        print(f"  ✗ K线获取失败: {e}")
        return []


def fetch_kline_yfinance(symbol: str, days: int = 60) -> list:
    """获取yfinance日K线历史数据"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=f"{days+10}d")
        klines = []
        for idx, row in hist.iterrows():
            klines.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": float(row["Open"]), "close": float(row["Close"]),
                "high": float(row["High"]), "low": float(row["Low"]),
                "volume": float(row["Volume"]),
            })
        return klines
    except Exception:
        return []


def analyze_strategy(name: str, klines: list) -> dict:
    """计算技术指标并生成策略信号（MA/MACD/RSI/布林带）"""
    if len(klines) < 20:
        return {"name": name, "signals": []}
    closes = [k["close"] for k in klines]
    volumes = [k["volume"] for k in klines]
    signals = []

    def ma(data, n):
        return sum(data[-n:]) / n if len(data) >= n else None

    ma5, ma10, ma20 = ma(closes, 5), ma(closes, 10), ma(closes, 20)
    # 均线趋势
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            signals.append("📈 均线多头排列")
        elif ma5 < ma10 < ma20:
            signals.append("📉 均线空头排列")
        if closes[-1] > ma5 > ma10:
            signals.append("✅ 价格站上均线")
        elif closes[-1] < ma5 < ma10:
            signals.append("⚠️ 价格跌破均线")
    # MACD
    if len(closes) >= 26:
        ema12, ema26 = closes[-12:].__iter__(), closes[-26:].__iter__()
        e12 = sum(closes[-12:]) / 12
        e26 = sum(closes[-26:]) / 26
        dif = e12 - e26
        e12_prev = sum(closes[-13:-1]) / 12
        e26_prev = sum(closes[-27:-1]) / 26
        dif_prev = e12_prev - e26_prev
        dea = (dif + dif_prev) / 2
        dea_prev_val = sum(closes[-27:-1]) / 26
        if dif > 0 and dif_prev <= 0:
            signals.append("🔴 MACD金叉")
        elif dif < 0 and dif_prev >= 0:
            signals.append("🟢 MACD死叉")
        elif dif > dea > 0:
            signals.append("📈 MACD多头")
        elif dif < dea < 0:
            signals.append("📉 MACD空头")
    # RSI
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
            signals.append(f"⚠️ RSI超买({rsi:.0f})")
        elif rsi < 30:
            signals.append(f"✅ RSI超卖({rsi:.0f})")
        else:
            signals.append(f"📊 RSI中性({rsi:.0f})")
    # 布林带
    if len(closes) >= 20:
        sma20 = sum(closes[-20:]) / 20
        std20 = (sum((c - sma20) ** 2 for c in closes[-20:]) / 20) ** 0.5
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20
        if closes[-1] > upper:
            signals.append("⚠️ 突破布林上轨(注意压力)")
        elif closes[-1] < lower:
            signals.append("✅ 触及布林下轨(或有支撑)")
    # 量能
    if len(volumes) >= 6:
        vol5 = sum(volumes[-5:]) / 5
        vol_prev5 = sum(volumes[-10:-5]) / 5
        if vol5 > vol_prev5 * 1.3:
            signals.append("📈 明显放量")
        elif vol5 < vol_prev5 * 0.7:
            signals.append("📉 明显缩量")

    return {"name": name, "signals": signals}


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


def rule_analysis(a_share: dict, a_share_sectors: dict, us_data: dict, asia_data: dict, sectors: dict,
                  strategy_signals: list = None) -> str:
    """基于规则的数据分析（不依赖外部AI API）"""
    lines = []
    lines.append("【📊 市场概览】\n")

    # A股分析
    if a_share:
        lines.append("▎A股主要指数：")
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

    # A股板块分析
    if a_share_sectors:
        lines.append("▎A股热门板块：")
        sorted_as = sorted(a_share_sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_as:
            emoji = "🔥" if d["change_pct"] > 2 else ("📈" if d["change_pct"] > 0 else ("📉" if d["change_pct"] < -2 else "⚪"))
            lines.append(f"  {emoji} {name}: {d['change_pct']:+.2f}%")
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
        lines.append("【💡 行业影响推断】")
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

    # A股综合预判
    lines.append("")
    lines.append("【🎯 A股今日预判】")
    
    # 收集所有影响因子
    bullish_factors = []
    bearish_factors = []
    
    # 美股影响
    if us_data:
        us_avg = sum(d["change_pct"] for d in us_data.values()) / len(us_data)
        if us_avg > 0.5:
            bullish_factors.append(f"美股隔夜走强（均涨幅{us_avg:+.2f}%），情绪面利好")
        elif us_avg < -0.5:
            bearish_factors.append(f"美股隔夜走弱（均跌幅{us_avg:+.2f}%），情绪面承压")
    
    # 日韩影响
    if asia_data:
        jp = asia_data.get("日经225", {})
        kr = asia_data.get("韩国KOSPI", {})
        if jp.get("change_pct", 0) > 0.5:
            bullish_factors.append("日经225走强，亚太市场氛围偏暖")
        elif jp.get("change_pct", 0) < -0.5:
            bearish_factors.append("日经225走弱，亚太市场氛围偏冷")
    
    # 板块影响
    if sectors:
        sorted_sec = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        top_name = sorted_sec[0][0] if sorted_sec else ""
        top_pct = sorted_sec[0][1]["change_pct"] if sorted_sec else 0
        if top_pct > 1.5:
            bullish_factors.append(f"{top_name}板块领涨全球（{top_pct:+.2f}%），相关A股板块或跟涨")
        bottom_name = sorted_sec[-1][0] if sorted_sec else ""
        bottom_pct = sorted_sec[-1][1]["change_pct"] if sorted_sec else 0
        if bottom_pct < -1.5:
            bearish_factors.append(f"{bottom_name}板块领跌全球（{bottom_pct:+.2f}%），相关A股板块注意风险")
    
    if bullish_factors:
        lines.append("  偏多因素：")
        for f in bullish_factors:
            lines.append(f"    ✅ {f}")
    if bearish_factors:
        lines.append("  偏空因素：")
        for f in bearish_factors:
            lines.append(f"    ⚠️ {f}")
    
    if not bullish_factors and not bearish_factors:
        lines.append("  今日外部因素中性，A股走势更多取决于国内消息面和资金面。")
    elif len(bullish_factors) > len(bearish_factors):
        lines.append(f"  📈 综合判断：偏多因素占优（{len(bullish_factors)} vs {len(bearish_factors)}），A股今日有望偏强运行。")
    elif len(bearish_factors) > len(bullish_factors):
        lines.append(f"  📉 综合判断：偏空因素占优（{len(bearish_factors)} vs {len(bullish_factors)}），A股今日可能承压。")
    else:
        lines.append(f"  📊 综合判断：多空因素均衡，A股今日大概率维持震荡格局。")

    return "\n".join(lines)


def ai_deep_analysis(a_share: dict, a_share_sectors: dict, us_data: dict, asia_data: dict, sectors: dict,
                     top_movers: list = None, top_losers: list = None, concept_rank: dict = None,
                     watchlist: dict = None, news: list = None,
                     strategy_signals: list = None) -> Optional[str]:
    """使用DeepSeek API生成结构化决策仪表盘分析报告"""
    if not DEEPSEEK_API_KEY:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        # 构建丰富的数据摘要（含异动个股、概念板块）
        data_parts = {
            "A股指数": {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in a_share.items()},
            "A股板块": {k: f"{v['change_pct']:+.2f}%" for k, v in a_share_sectors.items()},
            "美股": {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in us_data.items()},
            "日韩": {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in asia_data.items()},
            "美股板块": {k: f"{v['change_pct']:+.2f}%" for k, v in sectors.items()},
        }
        if top_movers:
            data_parts["A股涨幅榜"] = [f"{s['name']}({s['change_pct']:+.1f}%)" for s in top_movers[:5]]
        if top_losers:
            data_parts["A股跌幅榜"] = [f"{s['name']}({s['change_pct']:+.1f}%)" for s in top_losers[:5]]
        if concept_rank:
            if concept_rank.get("top"):
                data_parts["领涨概念"] = [f"{s['name']}({s['change_pct']:+.1f}%)" for s in concept_rank["top"][:4]]
            if concept_rank.get("bottom"):
                data_parts["领跌概念"] = [f"{s['name']}({s['change_pct']:+.1f}%)" for s in concept_rank["bottom"][:4]]
        if watchlist:
            data_parts["自选股"] = {k: f"{v['price']:.2f}({v['change_pct']:+.2f}%)" for k, v in watchlist.items()}
        if news:
            data_parts["最新新闻"] = [n["title"] for n in news[:5]]
        if strategy_signals:
            data_parts["技术信号"] = {s["name"]: s["signals"] for s in strategy_signals if s["signals"]}

        data_summary = json.dumps(data_parts, ensure_ascii=False, indent=2)

        prompt = f"""你是资深股市分析师。以下是今日全球市场数据（JSON格式）：

{data_summary}

请生成一份结构化股市日报，严格按以下格式输出（使用emoji标记，500字以内）：

【📊 市场总览】（1-2句话概括 + 综合评分X/10）

【🔥 板块动向】
▎A股板块：领涨/领跌分析
▎全球板块：关键变化

【⚠️ 风险警报】（2-3条，每条用❗开头）

【💡 利好催化】（2-3条，每条用✅开头）

【🎯 操作建议】
▎仓位：（建议仓位水平）
▎关注：（值得关注的方向）
▎回避：（需要回避的方向）

要求：语言通俗易懂，适合非专业投资者阅读。重点关注A股相关影响，给出实操性建议。"""
        if watchlist:
            prompt += "\n\n请额外对自选股持仓逐一给出简短点评（1-2句）。"
        if news:
            prompt += "\n请结合最新新闻事件分析对市场的潜在影响。"

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1200,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[AI分析] 调用失败: {e}")
        return None


def generate_html_report(date_str: str, a_share: dict, a_share_sectors: dict, us_data: dict, asia_data: dict,
                          sectors: dict, rule_text: str, ai_text: Optional[str],
                          top_movers: list = None, top_losers: list = None,
                          concept_rank: dict = None,
                          watchlist: dict = None, news: list = None,
                          strategy_signals: list = None) -> str:
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
        html += '<div class="card"><div class="section-title">🇨🇳 A股主要指数</div>'
        for name, d in a_share.items():
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><b>{d['price']:.2f}</b> <span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # A股热门板块
    if a_share_sectors:
        html += '<div class="card"><div class="section-title">🔥 A股热门板块</div>'
        sorted_as = sorted(a_share_sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
        for name, d in sorted_as:
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            html += f"""<div class="idx">
  <span class="idx-name">{name}</span>
  <span class="idx-price"><span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # A股异动个股和板块
    has_movers = (top_movers and len(top_movers) > 0) or (top_losers and len(top_losers) > 0)
    has_concept = concept_rank and (len(concept_rank.get("top", [])) > 0 or len(concept_rank.get("bottom", [])) > 0)
    if has_movers or has_concept:
        html += '<div class="card"><div class="section-title">⚡ A股昨日异动</div>'

        # 涨幅榜个股
        if top_movers and len(top_movers) > 0:
            html += '<div style="margin-bottom:10px;"><b style="color:#e74c3c;font-size:13px;">📈 涨幅榜</b></div>'
            for s in top_movers:
                html += f"""<div class="idx">
  <span class="idx-name">{s['name']} <span class="gray">{s['code']}</span></span>
  <span class="idx-price"><b>{s['price']:.2f}</b> <span class="red">{s['change_pct']:+.2f}%</span></span>
</div>"""

        # 跌幅榜个股
        if top_losers and len(top_losers) > 0:
            html += '<div style="margin:10px 0 8px;"><b style="color:#27ae60;font-size:13px;">📉 跌幅榜</b></div>'
            for s in top_losers:
                html += f"""<div class="idx">
  <span class="idx-name">{s['name']} <span class="gray">{s['code']}</span></span>
  <span class="idx-price"><b>{s['price']:.2f}</b> <span class="green">{s['change_pct']:+.2f}%</span></span>
</div>"""

        # 概念板块异动
        if has_concept:
            if concept_rank.get("top"):
                tags = " ".join([f'<span class="tag" style="background:#ffeaea;color:#c0392b;">{s["name"]} {s["change_pct"]:+.1f}%</span>' for s in concept_rank["top"][:4]])
                html += f'<div style="margin-top:10px;"><b style="font-size:13px;">🔥 领涨概念：</b>{tags}</div>'
            if concept_rank.get("bottom"):
                tags = " ".join([f'<span class="tag" style="background:#eafaf1;color:#1e8449;">{s["name"]} {s["change_pct"]:+.1f}%</span>' for s in concept_rank["bottom"][:4]])
                html += f'<div style="margin-top:6px;"><b style="font-size:13px;">❄️ 领跌概念：</b>{tags}</div>'

        html += "</div>"

    # 自选股持仓
    if watchlist:
        html += '<div class="card"><div class="section-title">💼 自选股持仓</div>'
        for name, d in watchlist.items():
            cls = "red" if d["change_pct"] > 0 else ("green" if d["change_pct"] < 0 else "gray")
            # 获取额外指标（兼容旧数据）
            turnover = d.get("turnover", 0)
            amount = d.get("amount", "-")
            volume_ratio = d.get("volume_ratio", 0)
            # 构建额外指标显示（始终显示）
            extra_info = []
            # 换手率
            if turnover > 0:
                extra_info.append(f'换手<span style="color:#8e44ad;">{turnover:.2f}%</span>')
            else:
                extra_info.append(f'换手<span style="color:#ccc;">--</span>')
            # 成交额
            if amount and amount != "-":
                extra_info.append(f'成交额<span style="color:#2980b9;">{amount}</span>')
            else:
                extra_info.append(f'成交额<span style="color:#ccc;">--</span>')
            # 量比
            if volume_ratio > 0:
                vr_color = "#e74c3c" if volume_ratio > 1.5 else ("#27ae60" if volume_ratio < 0.7 else "#666")
                extra_info.append(f'量比<span style="color:{vr_color};">{volume_ratio:.2f}</span>')
            else:
                extra_info.append(f'量比<span style="color:#ccc;">--</span>')
            extra_html = " | ".join(extra_info)
            html += f"""<div class="idx" style="flex-wrap:wrap;">
  <div style="flex:1;min-width:200px;">
    <div><span class="idx-name">{name}</span></div>
    <div style="font-size:11px;color:#888;margin-top:2px;">{extra_html}</div>
  </div>
  <span class="idx-price"><b>{d['price']:.2f}</b> <span class="{cls}">{d['change_pct']:+.2f}%</span></span>
</div>"""
        html += "</div>"

    # 市场新闻
    if news:
        html += '<div class="card"><div class="section-title">📰 最新财经资讯</div>'
        for n in news[:6]:
            t = n.get("time", "")
            html += f'<div style="padding:4px 0;border-bottom:1px solid #f0f0f0;font-size:13px;"><span class="gray" style="font-size:11px;">{t}</span> {n["title"]}</div>'
        html += "</div>"

    # 策略信号
    if strategy_signals:
        has_any = any(s.get("signals") for s in strategy_signals)
        if has_any:
            html += '<div class="card"><div class="section-title">📐 技术策略信号</div>'
            for s in strategy_signals:
                if s.get("signals"):
                    tags = " ".join([f'<span class="tag">{sig}</span>' for sig in s["signals"]])
                    html += f'<div style="padding:6px 0;border-bottom:1px solid #f0f0f0;"><b style="font-size:13px;">{s["name"]}</b><div style="margin-top:4px;">{tags}</div></div>'
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


def send_webhook(a_share: dict, us_data: dict, asia_data: dict, ai_text: str = None,
               wecom_url: str = None, feishu_url: str = None):
    """发送 Webhook 通知（企业微信/飞书，支持传入自定义 webhook URL）"""
    # ---- 构建推送摘要 ----
    lines = ["📊 今日市场摘要"]
    if a_share:
        parts = [f"{n} {d['price']:.2f}({d['change_pct']:+.2f}%)" for n, d in a_share.items()]
        lines.append("A股：" + " | ".join(parts))
    if us_data:
        parts = [f"{n} {d['change_pct']:+.2f}%" for n, d in us_data.items()]
        lines.append("美股：" + " | ".join(parts))
    if asia_data:
        parts = [f"{n} {d['change_pct']:+.2f}%" for n, d in asia_data.items()]
        lines.append("日韩：" + " | ".join(parts))
    # 附加 AI 分析摘要
    if ai_text:
        lines.append("")
        lines.append(ai_text[:300])
    msg = "\n".join(lines)

    # ---- 企业微信机器人 ----
    wecom = wecom_url or os.environ.get("WECOM_WEBHOOK_URL", "")
    if wecom:
        try:
            payload = {"msgtype": "text", "text": {"content": msg}}
            r = _requests.post(wecom, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("errcode") == 0:
                print("[企微通知] 发送成功 ✓")
            else:
                print(f"[企微通知] 发送失败: {r.text}")
        except Exception as e:
            print(f"[企微通知] 发送失败: {e}")

    # ---- 飞书机器人 ----
    feishu = feishu_url or os.environ.get("FEISHU_WEBHOOK_URL", "")
    if feishu:
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": "📊 全球股市日报"}},
                    "elements": [{"tag": "markdown", "content": msg}]
                }
            }
            r = _requests.post(feishu, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("code", -1) == 0:
                print("[飞书通知] 发送成功 ✓")
            else:
                print(f"[飞书通知] 发送失败: {r.text}")
        except Exception as e:
            print(f"[飞书通知] 发送失败: {e}")


def send_email(html_content: str, subject: str, to_addr: str = None):
    """发送HTML邮件"""
    recipient = to_addr or EMAIL_TO
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_FROM
    msg["To"] = recipient
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15)
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, [recipient], msg.as_string())
        server.quit()
        print(f"[邮件] 发送至 {recipient} 成功 ✓")
    except Exception as e:
        print(f"[邮件] 发送至 {recipient} 失败: {e}")
        raise


def main():
    BJ_TZ = timezone(timedelta(hours=8))
    print(f"[开始] {datetime.now(BJ_TZ).strftime('%Y-%m-%d %H:%M:%S')} 北京时间")

    today = datetime.now(BJ_TZ)
    date_str = today.strftime("%Y年%m月%d日")

    # 如果是周末，使用上周五的数据
    weekday = today.weekday()
    if weekday == 5:  # 周六
        date_str = (today - timedelta(days=1)).strftime("%Y年%m月%d日")
    elif weekday == 6:  # 周日
        date_str = (today - timedelta(days=2)).strftime("%Y年%m月%d日")

    # ============================================================
    # 加载客户列表
    # ============================================================
    customers = load_customers()
    print(f"[客户] 共 {len(customers)} 个客户待处理")

    # ============================================================
    # 获取公共市场数据（所有客户共享，只获取一次）
    # ============================================================

    # 1. 抓取A股指数数据（yfinance优先，从GitHub稳定；东方财富备用）
    print("[数据] 获取A股指数...")
    a_share = fetch_a_share_yfinance()
    if len(a_share) < 2:
        print("  → yfinance数据不足，切换东方财富备用源...")
        a_share_fallback = fetch_a_share_eastmoney_fallback()
        for k, v in a_share_fallback.items():
            if k not in a_share:
                a_share[k] = v
    print(f"  → 获取到 {len(a_share)} 个指数")

    # 2. 抓取A股板块数据
    print("[数据] 获取A股热门板块...")
    a_share_sectors = fetch_a_share_sectors()
    print(f"  → 获取到 {len(a_share_sectors)} 个板块")

    # 2.5 抓取A股异动个股（涨幅榜+跌幅榜）
    print("[数据] 获取A股异动个股...")
    top_movers, top_losers = fetch_top_movers(8)
    print(f"  → 涨幅榜{len(top_movers)}只，跌幅榜{len(top_losers)}只")

    # 2.6 抓取概念板块排行
    print("[数据] 获取概念板块排行...")
    concept_rank = fetch_concept_sector_ranking(6)
    print(f"  → 领涨{len(concept_rank.get('top', []))}个，领跌{len(concept_rank.get('bottom', []))}个")

    # 2.8 获取市场新闻
    print("[数据] 获取市场新闻...")
    news = fetch_market_news(8)

    # 3. 抓取美股数据
    print("[数据] 获取美股数据...")
    us_data = fetch_yfinance_data(US_INDICES)
    print(f"  → 获取到 {len(us_data)} 个指数")

    # 4. 抓取日韩数据
    print("[数据] 获取日韩数据...")
    asia_data = fetch_yfinance_data(ASIA_INDICES)
    print(f"  → 获取到 {len(asia_data)} 个指数")

    # 5. 抓取美股板块数据
    print("[数据] 获取美股板块...")
    sectors = fetch_sector_data()
    print(f"  → 获取到 {len(sectors)} 个板块")

    # 5.5 技术指标分析
    print("[分析] 计算技术指标...")
    strategy_signals = []
    for name, code in A_SHARE_INDICES.items():
        market = "1" if code.startswith("0") else "0"
        klines = fetch_kline_eastmoney(f"{market}.{code}")
        if klines:
            sig = analyze_strategy(name, klines)
            strategy_signals.append(sig)
            print(f"  ✓ {name}: {len(sig['signals'])}个信号")
    for name, code in {"标普500": "^GSPC", "纳斯达克": "^IXIC"}.items():
        klines = fetch_kline_yfinance(code)
        if klines:
            sig = analyze_strategy(name, klines)
            strategy_signals.append(sig)
            print(f"  ✓ {name}: {len(sig['signals'])}个信号")

    # 6. 规则分析（公共部分）
    print("[分析] 执行规则分析...")
    rule_text = rule_analysis(a_share, a_share_sectors, us_data, asia_data, sectors, strategy_signals)

    # ============================================================
    # 遍历每个客户，生成个性化报告并发送
    # ============================================================
    for idx, customer in enumerate(customers, 1):
        cust_name = customer.get("name", f"客户{customer['id']}")
        cust_email = customer.get("email", "")
        cust_watchlist = customer.get("watchlist", {})
        cust_wecom = customer.get("wecom_webhook", "")
        cust_feishu = customer.get("feishu_webhook", "")

        print(f"\n{'='*50}")
        print(f"[客户 {idx}/{len(customers)}] {cust_name} (ID: {customer['id']})")
        print(f"{'='*50}")

        # 7. 获取该客户的自选股行情
        print(f"[自选] 获取 {cust_name} 的自选股行情...")
        watchlist_data = fetch_watchlist_data(cust_watchlist) if cust_watchlist else {}
        print(f"  → 获取到 {len(watchlist_data)} 只自选股")

        # 8. AI深度分析（包含该客户的自选股信息）
        ai_text = ai_deep_analysis(a_share, a_share_sectors, us_data, asia_data, sectors,
                                   top_movers, top_losers, concept_rank, watchlist_data, news,
                                   strategy_signals)
        if ai_text:
            print(f"[AI] {cust_name} 的 DeepSeek 分析完成")
        else:
            print(f"[AI] {cust_name} 跳过AI分析")

        # 9. 生成HTML邮件
        print(f"[报告] 生成 {cust_name} 的报告...")
        html = generate_html_report(date_str, a_share, a_share_sectors, us_data, asia_data, sectors,
                                    rule_text, ai_text, top_movers, top_losers, concept_rank,
                                    watchlist_data, news, strategy_signals)

        # 10. 发送邮件
        if cust_email:
            print(f"[邮件] 发送至 {cust_email}...")
            subject = f"📊 全球股市日报 - {date_str}"
            try:
                send_email(html, subject, to_addr=cust_email)
            except Exception as e:
                print(f"[邮件] 发送失败: {e}")
        else:
            print(f"[邮件] {cust_name} 未配置邮箱，跳过")

        # 11. Webhook 通知
        if cust_wecom or cust_feishu:
            print(f"[通知] 发送 {cust_name} 的 Webhook 通知...")
            send_webhook(a_share, us_data, asia_data, ai_text,
                        wecom_url=cust_wecom, feishu_url=cust_feishu)

    print(f"\n[完成] 共处理 {len(customers)} 个客户，全部任务执行完毕 ✓")


if __name__ == "__main__":
    main()
