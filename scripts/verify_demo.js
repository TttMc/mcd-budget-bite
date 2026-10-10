/* 一致性对拍：在同一个半 DOM 桩里跑 index.html 的真实脚本，把结果与 Python 求解器对比。
   用法：node scripts/verify_demo.js <budget> <kcal>
*/
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
const html = fs.readFileSync(path.join(ROOT, 'docs', 'index.html'), 'utf8');

const budget = Number(process.argv[2] || 30);
const kcal = Number(process.argv[3] || 800);

// —— 最小 DOM 桩 ——
const store = {};
function mkEl(id) {
  return {
    id, _text: '', _html: '',
    set textContent(v) { this._text = String(v); }, get textContent() { return this._text; },
    set innerHTML(v) { this._html = String(v); }, get innerHTML() { return this._html; },
    value: id === 'budget' ? String(budget) : id === 'kcal' ? String(kcal) : '',
    addEventListener() {},
    classList: { add() {}, remove() {} },
    dataset: {},
  };
}
global.document = {
  getElementById(id) { return store[id] || (store[id] = mkEl(id)); },
  querySelectorAll() { return []; },
};

// 抽出 <script> 正文并执行
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('未找到 script 段'); process.exit(1); }
// eslint-disable-next-line no-eval
eval(m[1]);

// 从渲染结果里解析三套方案的合计与热量
function parsePlans(htmlStr) {
  const out = [];
  const re = /<h3>([^<]+?)(?: ★)?<\/h3>[\s\S]*?<span class="big">¥([\d.]+)<\/span><\/div>\s*<div><span class="stat-k">热量<\/span> <b>(\d+)<\/b>/g;
  let x;
  while ((x = re.exec(htmlStr)) !== null) {
    out.push({ title: x[1].trim(), price: Number(x[2]), kcal: Number(x[3]) });
  }
  return out;
}

const got = parsePlans(store['plans']._html);
console.log(JSON.stringify({
  budget, kcal,
  plans: got,
  empty: store['plans']._html.includes('class="empty"'),
  bars: (store['ladder']._html.match(/class="bar"/g) || []).length,
}));
