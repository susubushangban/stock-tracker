"""
股市追踪 - Web 看板
使用方法: python web_dashboard.py
然后浏览器打开 http://localhost:8000
"""
from flask import Flask, render_template_string, jsonify
import json
import os
import sys

# 确保可以导入 main.py 中的函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import (
    WATCHLIST, A_SHARE_INDICES, US_INDICES, ASIA_INDICES,
    fetch_a_share_yfinance, fetch_a_share_eastmoney_fallback,
    fetch_a_share_sectors, fetch_concept_sector_ranking,
    fetch_top_movers, fetch_watchlist_data,
    fetch_yfinance_data, fetch_sector_data,
    fetch_kline_eastmoney, fetch_kline_yfinance, analyze_strategy,
)

app = Flask(__name__)

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>📊 股市追踪看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#0f0f1a;color:#e0e0e0;min-height:100vh}
.nav{background:#1a1a2e;padding:12px 20px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #2a2a4a;position:sticky;top:0;z-index:100}
.nav h1{font-size:18px;color:#fff}
.nav-r{display:flex;align-items:center;gap:12px}
.nav-time{color:#666;font-size:12px}
.btn{padding:6px 14px;border-radius:6px;border:none;cursor:pointer;font-size:12px;font-family:inherit}
.btn-refresh{background:#e94560;color:#fff}
.btn-refresh:hover{background:#c73e54}
.container{max-width:1400px;margin:0 auto;padding:16px}
.grid{display:grid;gap:16px;margin-bottom:16px}
.g2{grid-template-columns:repeat(2,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g2{grid-template-columns:1fr}}
@media(max-width:500px){.g4{grid-template-columns:1fr}}
.card{background:#1a1a2e;border-radius:12px;padding:16px;border:1px solid #2a2a4a}
.card-title{font-size:14px;font-weight:bold;margin-bottom:12px;color:#e94560;display:flex;align-items:center;gap:6px}
.idx-row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05)}
.idx-row:last-child{border-bottom:none}
.idx-name{font-size:13px;color:#aaa}
.idx-price{font-size:16px;font-weight:bold}
.idx-pct{font-size:12px;padding:2px 8px;border-radius:4px;margin-left:8px;font-weight:bold}
.up{color:#e94560}.up .idx-pct{background:rgba(233,69,96,0.15)}
.down{color:#00d4aa}.down .idx-pct{background:rgba(0,212,170,0.15)}
.flat{color:#666}.flat .idx-pct{background:rgba(255,255,255,0.05)}
.tag{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;margin:2px;font-weight:500}
.tag-r{background:rgba(233,69,96,0.15);color:#e94560}
.tag-g{background:rgba(0,212,170,0.15);color:#00d4aa}
.tag-b{background:rgba(52,152,219,0.15);color:#3498db}
.signal-card{background:rgba(255,255,255,0.03);border-radius:8px;padding:12px;margin-bottom:8px}
.signal-card:last-child{margin-bottom:0}
.signal-name{font-size:13px;font-weight:bold;color:#fff;margin-bottom:6px}
.chart-box{width:100%;height:380px}
.mover-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:13px}
.mover-row:last-child{border-bottom:none}
.loader{text-align:center;padding:40px;color:#555;font-size:14px}
.section-label{font-size:16px;font-weight:bold;color:#fff;margin:20px 0 12px;padding-left:4px}
.empty{color:#555;font-size:13px;text-align:center;padding:20px}
</style>
</head>
<body>
<div class="nav">
  <h1>📊 股市追踪看板</h1>
  <div class="nav-r">
    <span class="nav-time">{{ update_time }}</span>
    <button class="btn btn-refresh" onclick="location.reload()">🔄 刷新数据</button>
  </div>
</div>
<div class="container">

  {# ===== A股指数 ===== #}
  <div class="section-label">🇨🇳 A股市场</div>
  <div class="grid g4">
    {% for name, d in a_share.items() %}
    <div class="card">
      <div class="idx-name">{{ name }}</div>
      <div class="idx-price {{ 'up' if d.change_pct > 0 else ('down' if d.change_pct < 0 else 'flat') }}">
        <span class="idx-price">{{ "%.2f"|format(d.price) }}</span>
        <span class="idx-pct">{{ "%+.2f"|format(d.change_pct) }}%</span>
      </div>
    </div>
    {% endfor %}
  </div>

  {# ===== A股板块 + 概念 ===== #}
  <div class="grid g2" style="margin-top:16px">
    <div class="card">
      <div class="card-title">🔥 热门板块</div>
      {% if sectors %}
        {% for name, d in sectors.items()|sort(attribute='1.change_pct', reverse=true) %}
        <div class="idx-row {{ 'up' if d.change_pct > 0 else ('down' if d.change_pct < 0 else 'flat') }}">
          <span class="idx-name">{{ name }}</span>
          <span class="idx-pct">{{ "%+.2f"|format(d.change_pct) }}%</span>
        </div>
        {% endfor %}
      {% else %}<div class="empty">暂无数据（东方财富API受限）</div>{% endif %}
    </div>
    <div class="card">
      <div class="card-title">💡 概念板块</div>
      {% if concept_rank.top %}
      <div style="margin-bottom:10px">
        <div style="font-size:12px;color:#e94560;margin-bottom:4px">▲ 领涨</div>
        {% for s in concept_rank.top %}<span class="tag tag-r">{{ s.name }} {{ "%+.1f"|format(s.change_pct) }}%</span>{% endfor %}
      </div>
      {% endif %}
      {% if concept_rank.bottom %}
      <div>
        <div style="font-size:12px;color:#00d4aa;margin-bottom:4px">▼ 领跌</div>
        {% for s in concept_rank.bottom %}<span class="tag tag-g">{{ s.name }} {{ "%+.1f"|format(s.change_pct) }}%</span>{% endfor %}
      </div>
      {% endif %}
      {% if not concept_rank.top and not concept_rank.bottom %}<div class="empty">暂无数据</div>{% endif %}
    </div>
  </div>

  {# ===== 涨幅榜 + 跌幅榜 ===== #}
  <div class="grid g2" style="margin-top:16px">
    <div class="card">
      <div class="card-title">📈 涨幅榜 TOP8</div>
      {% if top_movers %}
        {% for s in top_movers %}
        <div class="mover-row up">
          <span>{{ s.name }} <span style="color:#555;font-size:11px">{{ s.code }}</span></span>
          <span><b>{{ "%.2f"|format(s.price) }}</b> <span class="tag tag-r">{{ "%+.2f"|format(s.change_pct) }}%</span></span>
        </div>
        {% endfor %}
      {% else %}<div class="empty">暂无数据</div>{% endif %}
    </div>
    <div class="card">
      <div class="card-title">📉 跌幅榜 TOP8</div>
      {% if top_losers %}
        {% for s in top_losers %}
        <div class="mover-row down">
          <span>{{ s.name }} <span style="color:#555;font-size:11px">{{ s.code }}</span></span>
          <span><b>{{ "%.2f"|format(s.price) }}</b> <span class="tag tag-g">{{ "%+.2f"|format(s.change_pct) }}%</span></span>
        </div>
        {% endfor %}
      {% else %}<div class="empty">暂无数据</div>{% endif %}
    </div>
  </div>

  {# ===== 自选股 ===== #}
  <div class="section-label">💼 自选股</div>
  <div class="grid g4">
    {% for name, d in watchlist.items() %}
    <div class="card">
      <div class="idx-name">{{ name }}</div>
      <div class="{{ 'up' if d.change_pct > 0 else ('down' if d.change_pct < 0 else 'flat') }}">
        <span class="idx-price">{{ "%.2f"|format(d.price) }}</span>
        <span class="idx-pct">{{ "%+.2f"|format(d.change_pct) }}%</span>
      </div>
      {% if d.get('high') %}
      <div style="font-size:11px;color:#555;margin-top:4px">
        高 {{ "%.2f"|format(d.high) }} / 低 {{ "%.2f"|format(d.low) }}
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% if not watchlist %}<div class="card"><div class="empty">未配置自选股</div></div>{% endif %}

  {# ===== K线图 + 技术信号 ===== #}
  <div class="section-label">📐 技术分析</div>
  <div class="grid g2">
    <div class="card">
      <div class="card-title">📊 上证指数 K线</div>
      {% if kline_data %}
      <div id="kline-chart" class="chart-box"></div>
      {% else %}
      <div class="empty">K线数据暂不可用（非交易时段或API受限）</div>
      {% endif %}
    </div>
    <div class="card">
      <div class="card-title">🎯 技术信号</div>
      {% for sig in signals %}
        {% if sig.signals %}
        <div class="signal-card">
          <div class="signal-name">{{ sig.name }}</div>
          {% for s in sig.signals %}
          <span class="tag {{ 'tag-r' if '超买' in s or '跌破' in s or '空头' in s or '死叉' in s or '缩量' in s or '压力' in s else ('tag-g' if '超卖' in s or '站上' in s or '多头' in s or '金叉' in s or '放量' in s or '支撑' in s else 'tag-b') }}">{{ s }}</span>
          {% endfor %}
        </div>
        {% endif %}
      {% endfor %}
      {% if not signals or not signals|selectattr('signals')|list %}
      <div class="empty">暂无技术信号</div>
      {% endif %}
    </div>
  </div>

  {# ===== 美股 ===== #}
  <div class="section-label">🇺🇸 美股市场</div>
  <div class="grid g4">
    {% for name, d in us_data.items() %}
    <div class="card">
      <div class="idx-name">{{ name }}</div>
      <div class="{{ 'up' if d.change_pct > 0 else ('down' if d.change_pct < 0 else 'flat') }}">
        <span class="idx-price">{{ "%.2f"|format(d.price) }}</span>
        <span class="idx-pct">{{ "%+.2f"|format(d.change_pct) }}%</span>
      </div>
    </div>
    {% endfor %}
  </div>

  {# ===== 日韩 ===== #}
  <div class="section-label">🇯🇵🇰🇷 日韩市场</div>
  <div class="grid g4">
    {% for name, d in asia_data.items() %}
    <div class="card">
      <div class="idx-name">{{ name }}</div>
      <div class="{{ 'up' if d.change_pct > 0 else ('down' if d.change_pct < 0 else 'flat') }}">
        <span class="idx-price">{{ "%.2f"|format(d.price) }}</span>
        <span class="idx-pct">{{ "%+.2f"|format(d.change_pct) }}%</span>
      </div>
    </div>
    {% endfor %}
  </div>

  {# ===== 美股板块 ===== #}
  <div class="section-label">🏭 美股板块风向</div>
  <div class="card">
    {% if us_sectors %}
    <div id="sector-chart" class="chart-box"></div>
    {% else %}<div class="empty">暂无数据</div>{% endif %}
  </div>

</div>

<script>
// K线图
{% if kline_data %}
(function(){
  var chart = echarts.init(document.getElementById('kline-chart'), 'dark');
  var dates = {{ kline_data|tojson }};
  var ohlc = dates.map(function(d){ return [d.open, d.close, d.low, d.high]; });
  var datesList = dates.map(function(d){ return d.date; });
  var volumes = dates.map(function(d){ return d.volume; });
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [
      { left: '10%', right: '4%', top: '8%', height: '58%' },
      { left: '10%', right: '4%', top: '72%', height: '18%' }
    ],
    xAxis: [
      { type: 'category', data: datesList, gridIndex: 0, axisLabel: { show: false } },
      { type: 'category', data: datesList, gridIndex: 1, axisLabel: { fontSize: 10, color: '#666' } }
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#2a2a4a' } } },
      { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } }
    ],
    series: [
      {
        type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#e94560', color0: '#00d4aa', borderColor: '#e94560', borderColor0: '#00d4aa' }
      },
      {
        type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: function(p){ return ohlc[p.dataIndex][1] >= ohlc[p.dataIndex][0] ? '#e94560' : '#00d4aa'; } }
      }
    ]
  });
  window.addEventListener('resize', function(){ chart.resize(); });
})();
{% endif %}

// 美股板块柱状图
{% if us_sectors %}
(function(){
  var el = document.getElementById('sector-chart');
  if(!el) return;
  var chart = echarts.init(el, 'dark');
  var data = {{ us_sectors|tojson }};
  var names = Object.keys(data).sort(function(a,b){ return data[b].change_pct - data[a].change_pct; });
  var vals = names.map(function(n){ return data[n].change_pct; });
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', formatter: '{b}: {c}%' },
    grid: { left: '15%', right: '8%', top: '6%', bottom: '6%' },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: '#888' }, splitLine: { lineStyle: { color: '#2a2a4a' } } },
    yAxis: { type: 'category', data: names.reverse(), axisLabel: { color: '#ccc', fontSize: 12 } },
    series: [{
      type: 'bar', data: vals.reverse(),
      itemStyle: { color: function(p){ return p.value >= 0 ? '#e94560' : '#00d4aa'; }, borderRadius: [0,4,4,0] },
      label: { show: true, position: 'right', formatter: '{c}%', fontSize: 11, color: '#aaa' }
    }]
  });
  window.addEventListener('resize', function(){ chart.resize(); });
})();
{% endif %}
</script>
</body>
</html>
"""


@app.route('/')
def dashboard():
    """主看板页面"""
    from datetime import datetime, timezone, timedelta
    BJ = timezone(timedelta(hours=8))
    now = datetime.now(BJ)

    print("[看板] 正在获取数据...")

    # A股
    print("  → A股指数...")
    a_share = fetch_a_share_yfinance()
    if len(a_share) < 2:
        a_share.update(fetch_a_share_eastmoney_fallback())

    print("  → A股板块...")
    sectors = fetch_a_share_sectors()

    print("  → 概念板块...")
    concept_rank = fetch_concept_sector_ranking(6)

    print("  → 涨跌幅榜...")
    top_movers, top_losers = fetch_top_movers(8)

    print("  → 自选股...")
    watchlist = fetch_watchlist_data()

    # 美股/日韩
    print("  → 美股...")
    us_data = fetch_yfinance_data(US_INDICES)

    print("  → 日韩...")
    asia_data = fetch_yfinance_data(ASIA_INDICES)

    print("  → 美股板块...")
    us_sectors = fetch_sector_data()

    # K线数据
    print("  → K线数据...")
    kline = fetch_kline_eastmoney("1.000001", 60)
    if not kline:
        kline = fetch_kline_yfinance("000001.SS", 60)

    # 技术信号
    print("  → 技术信号...")
    signals = []
    for name, code in A_SHARE_INDICES.items():
        market = "1" if code.startswith("0") else "0"
        kl = fetch_kline_eastmoney(f"{market}.{code}")
        if not kl:
            kl = fetch_kline_yfinance(f"{code}.SS" if market == "1" else f"{code}.SZ")
        if kl:
            signals.append(analyze_strategy(name, kl))
    for name, sym in {"标普500": "^GSPC", "纳斯达克": "^IXIC"}.items():
        kl = fetch_kline_yfinance(sym)
        if kl:
            signals.append(analyze_strategy(name, kl))

    print("[看板] 数据获取完成 ✓")

    return render_template_string(
        HTML_TEMPLATE,
        a_share=a_share,
        sectors=sectors,
        concept_rank=concept_rank,
        top_movers=top_movers,
        top_losers=top_losers,
        watchlist=watchlist,
        us_data=us_data,
        asia_data=asia_data,
        us_sectors=us_sectors,
        kline_data=kline,
        signals=signals,
        update_time=now.strftime("%Y-%m-%d %H:%M 北京时间"),
    )


@app.route('/api/refresh')
def refresh():
    """API: 刷新数据（前端用 JS 调用）"""
    return jsonify({"status": "ok", "message": "请刷新页面"})


if __name__ == '__main__':
    import webbrowser
    port = 8000
    print(f"\n{'='*40}")
    print(f"  📊 股市追踪看板")
    print(f"  🌐 http://localhost:{port}")
    print(f"  按 Ctrl+C 停止")
    print(f"{'='*40}\n")
    webbrowser.open(f'http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
