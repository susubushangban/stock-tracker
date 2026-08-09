"""
股市追踪 - 自选股管理面板
使用方法: python watchlist_app.py
然后浏览器打开 http://localhost:5000
"""
from flask import Flask, jsonify, request, render_template_string
import json
import os
import requests

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_watchlist():
    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_watchlist(data):
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _auto_market(code: str) -> str:
    code = code.strip()
    if code.startswith("6"):
        return f"1.{code}"
    elif code.startswith("0") or code.startswith("3"):
        return f"0.{code}"
    return code


def commit_to_github(watchlist: dict) -> bool:
    """将 watchlist.json 同步到 GitHub"""
    try:
        cfg = load_config()
        token = cfg["github_token"]
        repo = cfg["github_repo"]
        branch = cfg.get("github_branch", "main")
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Mozilla/5.0",
        }
        url = f"https://api.github.com/repos/{repo}/contents/watchlist.json"
        # 获取当前 sha
        try:
            fi = requests.get(url, headers=headers, timeout=10).json()
            sha = fi.get("sha")
        except Exception:
            sha = None
        # 读取本地文件内容
        with open(WATCHLIST_FILE, encoding="utf-8") as f:
            content = f.read()
        import base64
        b64 = base64.b64encode(content.encode("utf-8")).decode()
        body = {
            "message": "🔄 更新自选股配置 (via Web Manager)",
            "content": b64,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=headers, json=body, timeout=15)
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[GitHub] 同步失败: {e}")
        return False


# ============================================================
# 路由
# ============================================================
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/watchlist")
def api_get_watchlist():
    data = load_watchlist()
    return jsonify(data)


@app.route("/api/watchlist/add", methods=["POST"])
def api_add_stock():
    body = request.json
    name = (body.get("name") or "").strip()
    code = (body.get("code") or "").strip()
    if not name or not code:
        return jsonify({"ok": False, "error": "名称和代码不能为空"}), 400
    secid = _auto_market(code)
    wl = load_watchlist()
    # 检查是否已存在
    if name in wl:
        return jsonify({"ok": False, "error": f"{name} 已在自选中"}), 400
    wl[name] = secid
    save_watchlist(wl)
    ok = commit_to_github(wl)
    return jsonify({"ok": ok, "watchlist": wl})


@app.route("/api/watchlist/remove", methods=["POST"])
def api_remove_stock():
    body = request.json
    name = (body.get("name") or "").strip()
    wl = load_watchlist()
    if name not in wl:
        return jsonify({"ok": False, "error": f"未找到 {name}"}), 404
    del wl[name]
    save_watchlist(wl)
    ok = commit_to_github(wl)
    return jsonify({"ok": ok, "watchlist": wl})


@app.route("/api/watchlist/reorder", methods=["POST"])
def api_reorder():
    """重新排序（可选功能）"""
    body = request.json
    names = body.get("order", [])
    wl = load_watchlist()
    new_wl = {}
    for n in names:
        if n in wl:
            new_wl[n] = wl[n]
    # 补充遗漏的
    for n, v in wl.items():
        if n not in new_wl:
            new_wl[n] = v
    save_watchlist(new_wl)
    return jsonify({"ok": True})


# ============================================================
# HTML 模板（移动端优先）
# ============================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>自选股管理</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: #f0f2f5; color: #333; min-height: 100vh;
}
.header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff; padding: 20px 16px 16px; text-align: center;
}
.header h1 { font-size: 20px; font-weight: 600; }
.header p { font-size: 12px; opacity: 0.8; margin-top: 4px; }
.container { max-width: 500px; margin: 0 auto; padding: 16px; }

/* 添加表单 */
.add-card {
    background: #fff; border-radius: 12px; padding: 16px;
    margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.add-card h3 { font-size: 14px; color: #666; margin-bottom: 12px; }
.form-row { display: flex; gap: 8px; }
.form-row input {
    flex: 1; padding: 10px 12px; border: 1.5px solid #e0e0e0;
    border-radius: 8px; font-size: 15px; outline: none;
    transition: border-color 0.2s;
}
.form-row input:focus { border-color: #667eea; }
.form-row input::placeholder { color: #bbb; }
.btn-add {
    padding: 10px 20px; background: linear-gradient(135deg, #667eea, #764ba2);
    color: #fff; border: none; border-radius: 8px; font-size: 15px;
    font-weight: 600; cursor: pointer; white-space: nowrap;
    transition: opacity 0.2s;
}
.btn-add:active { opacity: 0.7; }
.btn-add:disabled { opacity: 0.5; cursor: not-allowed; }

/* 自选股列表 */
.list-card {
    background: #fff; border-radius: 12px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.list-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 16px; border-bottom: 1px solid #f0f0f0;
}
.list-header h3 { font-size: 14px; color: #666; }
.list-header .count { font-size: 12px; color: #999; }
.stock-item {
    display: flex; align-items: center; padding: 14px 16px;
    border-bottom: 1px solid #f5f5f5; transition: background 0.15s;
}
.stock-item:active { background: #f9f9f9; }
.stock-info { flex: 1; }
.stock-name { font-size: 15px; font-weight: 500; }
.stock-code { font-size: 12px; color: #999; margin-top: 2px; }
.btn-del {
    width: 32px; height: 32px; border-radius: 50%;
    background: #fff0f0; border: none; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; color: #e74c3c; transition: all 0.2s;
}
.btn-del:active { background: #e74c3c; color: #fff; }
.empty {
    text-align: center; padding: 40px 16px; color: #999; font-size: 14px;
}

/* Toast 通知 */
.toast {
    position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
    background: #333; color: #fff; padding: 10px 20px; border-radius: 20px;
    font-size: 14px; z-index: 999; opacity: 0; transition: opacity 0.3s;
    pointer-events: none; max-width: 90%;
}
.toast.show { opacity: 1; }
.toast.success { background: #27ae60; }
.toast.error { background: #e74c3c; }

/* 同步状态 */
.sync-bar {
    display: flex; align-items: center; justify-content: center;
    gap: 6px; padding: 8px; font-size: 12px; color: #999;
}
.sync-dot {
    width: 6px; height: 6px; border-radius: 50%; background: #27ae60;
}
.sync-dot.off { background: #e74c3c; }

/* 加载动画 */
.spinner {
    display: inline-block; width: 16px; height: 16px;
    border: 2px solid #ddd; border-top-color: #667eea;
    border-radius: 50%; animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
    <h1>📊 自选股管理</h1>
    <p>修改后自动同步到云端</p>
</div>

<div class="container">
    <div class="add-card">
        <h3>添加股票</h3>
        <div class="form-row">
            <input type="text" id="stockName" placeholder="股票名称（如：贵州茅台）">
            <input type="text" id="stockCode" placeholder="代码（如：600519）">
            <button class="btn-add" onclick="addStock()" id="btnAdd">添加</button>
        </div>
    </div>

    <div class="list-card">
        <div class="list-header">
            <h3>当前自选</h3>
            <span class="count" id="stockCount">-</span>
        </div>
        <div id="stockList">
            <div class="empty"><div class="spinner"></div><br>加载中...</div>
        </div>
    </div>

    <div class="sync-bar">
        <span class="sync-dot" id="syncDot"></span>
        <span id="syncText">已同步</span>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = id => document.getElementById(id);

function showToast(msg, type) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'toast show ' + (type || '');
    setTimeout(() => t.className = 'toast', 2500);
}

async function loadWatchlist() {
    try {
        const res = await fetch('/api/watchlist');
        const data = await res.json();
        const entries = Object.entries(data);
        $('stockCount').textContent = entries.length + ' 只';

        if (entries.length === 0) {
            $('stockList').innerHTML = '<div class="empty">暂无自选股<br>在上方添加</div>';
            return;
        }

        let html = '';
        for (const [name, code] of entries) {
            const market = code.split('.')[0];
            const pureCode = code.split('.')[1] || code;
            const marketLabel = market === '1' ? '沪' : '深';
            html += `
<div class="stock-item">
    <div class="stock-info">
        <div class="stock-name">${name}</div>
        <div class="stock-code">${marketLabel} ${pureCode}</div>
    </div>
    <button class="btn-del" onclick="removeStock('${name}')" title="删除">✕</button>
</div>`;
        }
        $('stockList').innerHTML = html;
    } catch (e) {
        $('stockList').innerHTML = '<div class="empty">加载失败</div>';
    }
}

async function addStock() {
    const name = $('stockName').value.trim();
    const code = $('stockCode').value.trim();
    if (!name || !code) { showToast('请填写名称和代码', 'error'); return; }

    $('btnAdd').disabled = true;
    $('btnAdd').textContent = '...';
    try {
        const res = await fetch('/api/watchlist/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, code}),
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`✓ 已添加 ${name}`, 'success');
            $('stockName').value = '';
            $('stockCode').value = '';
            loadWatchlist();
        } else {
            showToast(data.error || '添加失败', 'error');
        }
        updateSync(data.ok);
    } catch (e) {
        showToast('网络错误', 'error');
    }
    $('btnAdd').disabled = false;
    $('btnAdd').textContent = '添加';
}

async function removeStock(name) {
    if (!confirm(`确定删除 ${name}？`)) return;
    try {
        const res = await fetch('/api/watchlist/remove', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name}),
        });
        const data = await res.json();
        if (data.ok) {
            showToast(`✓ 已删除 ${name}`, 'success');
            loadWatchlist();
        } else {
            showToast(data.error || '删除失败', 'error');
        }
        updateSync(data.ok);
    } catch (e) {
        showToast('网络错误', 'error');
    }
}

function updateSync(ok) {
    $('syncDot').className = ok ? 'sync-dot' : 'sync-dot off';
    $('syncText').textContent = ok ? '已同步到云端' : '同步失败（本地已更新）';
}

// 回车键添加
$('stockCode').addEventListener('keydown', e => {
    if (e.key === 'Enter') addStock();
});
$('stockName').addEventListener('keydown', e => {
    if (e.key === 'Enter') $('stockCode').focus();
});

// 初始化
loadWatchlist();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print("=" * 40)
    print("📊 自选股管理面板")
    print("   打开浏览器访问: http://localhost:5000")
    print("   按 Ctrl+C 停止")
    print("=" * 40)
    app.run(host="0.0.0.0", port=5000, debug=False)
