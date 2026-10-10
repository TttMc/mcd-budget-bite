# WorkBuddy 开发上下文

本文件记录「麦麦预算餐盘（mcd-budget-bite）」在腾讯 WorkBuddy 中的开发过程，
用于核验 WorkBuddy 专项奖励的参与条件。

## 一、项目概况

| 项 | 内容 |
|---|---|
| 项目名称 | 麦麦预算餐盘 · mcd-budget-bite |
| 开发工具 | 腾讯 WorkBuddy（Agent 模式） |
| MCP 接入 | 在 WorkBuddy 中以自定义连接器方式接入麦当劳 MCP（Streamable HTTP） |
| 起始时间 | 2026-10-10 |
| 参赛活动 | 2026 麦当劳程序员创意开发大赛（M-CODE） |

## 二、开发过程记录

### 1. 赛前分析（WorkBuddy 完成）

- 拉取并解析官方活动仓库 README、`activityGuidelines.md`、`RANKING.md`
- 结论：名次完全由 GitHub 公开 Star 数决定，非评审制
- 拉取 10-10 10:00 排行榜快照，对 113 个已上榜项目做赛道归类
- 发现赛道分化：省钱派（约 22 个）与热量派（约 15 个）互相分裂，
  两者结合的只有 4 个且分数偏低 → 据此确定「预算 × 热量双约束」的差异化定位

### 2. MCP 接入与验证（WorkBuddy 完成）

- 用 `curl` 完成 Streamable HTTP 握手，确认 `mcd-mcp` v1.0.0 可用
- 拉取 `tools/list`，确认 35 个 Tool 全部可用
  （比官方 README 还多出 `query-promotions`、`query-survey-coupon`）
- 在 WorkBuddy 中编写零依赖的 MCP 客户端 `scripts/mcp_client.py`

### 3. 真实数据调用（WorkBuddy 完成）

依次跑通并落盘缓存：

- `now-time-info` → 2026-10-10 11:03（正餐时段）
- `query-nearby-stores` → 上海黄浦悦荟广场餐厅，storeCode `1450104`
- `query-meals` → 121 项在售餐品，15 个分类
- `list-nutrition-foods` → 158 条营养记录（自定义分隔格式）
- `query-meal-detail` → 51 个套餐的逐一拆解，缓存至 `data/meal_details.json`

### 4. 关键问题发现与解决（WorkBuddy 完成）

**问题 A：营养数据格式非标准**
`list-nutrition-foods` 返回的是 `[160]{...}:\n 品名,null,1288,308,...` 的自定义文本，
且各 Tool 的业务数据被包在 markdown 的 `## Original Response` 段里。
→ 编写 `_extract_json` 与分隔文本解析器解决。

**问题 B：模糊匹配导致静默错误（最重要的发现）**
初版用 `difflib` 模糊匹配（cutoff 0.62）对齐菜单与营养库，命中 44 项。
但复核发现 `巨无霸三件套` 被匹配到 `巨无霸`（相似度 0.67），
而三件套还含中薯条与可乐中杯，真实热量约为单品的 2 倍。
→ **推翻模糊匹配方案**，改为「严格匹配 + 套餐拆解 + 缺失标注」，
宁可少推荐也绝不算错。这一取舍已写入 README 与 MCP_INTEGRATION.md。

**问题 C：求解结果不符合常识**
初版「最省型」输出「新地 + 圆筒冰淇淋」——确实便宜，但不是一顿饭。
→ 加入主食约束（组合必须含咸食主食），并限制天梯榜只统计单品，
排除多人份拼盘的口径污染。

### 5. 交付物（WorkBuddy 生成）

| 文件 | 说明 |
|---|---|
| `SKILL.md` | Skill 定义、触发条件、工作流、硬性约束 |
| `README.md` | 项目介绍、安装、真实输出示例、设计取舍、免责说明 |
| `MCP_INTEGRATION.md` | MCP 接入、6 个 Tool 的调用流程、数据对齐方案、踩坑记录 |
| `CONTEST_DECLARATION.md` | 参赛声明（官方模板，未改动） |
| `mcp-config.example.json` | 脱敏配置，仅含环境变量占位符 |
| `scripts/mcp_client.py` | MCP Streamable HTTP 客户端，零第三方依赖 |
| `scripts/solve.py` | 双约束求解器（全枚举 + 帕累托筛选 + 天梯榜） |
| `data/*.json` | 菜单、营养、套餐拆解缓存 |

### 6. 在线 Demo（WorkBuddy 生成，2026-10-10 14:20）

为便于传播与核验，在 WorkBuddy 中生成了一个零依赖的前端 Demo：

| 文件 | 说明 |
|---|---|
| `docs/index.html` | 单文件页面，数据内联，双击即可打开；也可 GitHub Pages 在线访问 |
| `docs/template.html` | 页面模板，含 `/*__DATA__*/{}` 占位符 |
| `docs/demo_data.json` | 候选集快照，由求解器导出 |
| `scripts/export_demo_data.py` | 复用 solve.py 的候选构建逻辑导出快照 |
| `scripts/build_demo.py` | 把快照注入模板，产出 index.html |
| `scripts/verify_demo.js` | 前端与 Python 求解器的一致性对拍 |

页面内的 JavaScript 求解器按与 Python 完全相同的规则实现（同款主食关键词、
同款三套方案选取逻辑、同款天梯榜口径）。为避免「demo 是一套、脚本是另一套」，
WorkBuddy 编写了 `verify_demo.js`：在 Node 里用最小 DOM 桩执行页面真实脚本，
解析渲染结果与命令行输出逐项比对。已验证 6 个场景（¥20/500 至 ¥50/1400）
三套方案的价格与热量全部相同，另含极端无解场景的空状态。

在线地址：https://tttmc.github.io/mcd-budget-bite/ （GitHub Pages，从 `/docs` 部署）

## 三、验证结果

在三个预算场景下实际运行通过：

| 场景 | 最省型 | 最均衡型 |
|---|---|---|
| ¥25 / 700 kcal | 麦香鸡 ¥17 / 369 kcal | 双层深海鳕鱼堡 ¥24 / 485 kcal |
| ¥30 / 800 kcal | 麦香鸡 ¥17 / 369 kcal | 牛肉堡单品精选 + 麦麦脆汁鸡 ¥29 / 576 kcal |
| ¥40 / 900 kcal | 麦香鸡 ¥17 / 369 kcal | 双层深海鳕鱼堡 + 麦麦脆汁鸡 ¥39 / 813 kcal |

¥40 档均衡解蛋白质 49g、钠 1822mg，求解器如实给出
「约占日均参考值 91%，当天其余餐次建议清淡」的风险提示。

## 四、在 WorkBuddy 中以 Skill 形态实际运行

本项目不止是脚本，已作为**用户级 Skill 安装进 WorkBuddy**，可在对话中用自然语言直接调用。

- 安装路径：`~/.workbuddy/skills/mcd-budget-bite/`（SKILL.md + scripts + data）
- 触发方式：在 WorkBuddy 对话中说人话即可，无需任何命令

### 自然语言对话实测记录（2026-10-10 12:06）

以下三句均为用户原话，由 WorkBuddy 识别意图 → 补齐缺省参数 → 调用麦当劳 MCP → 求解 → 回传结果：

| 用户输入 | WorkBuddy 的意图解析 | 实际输出 |
|---|---|---|
| 「30 块能吃啥麦当劳」 | 预算 ¥30；未提热量 → 取默认 800 kcal | 最饱型：麦乐鸡套餐 + 圆筒冰淇淋 ¥30 / 742 kcal |
| 「预算 25，热量别超 700，帮我配一顿」 | 预算 ¥25、热量上限 700 kcal，双约束齐全 | 最均衡型：双层深海鳕鱼堡 ¥24 / 485 kcal / 蛋白质 28g |
| 「我在减脂，今晚想吃麦当劳」 | 识别为减脂意图、未给数字 → 按一餐 600 kcal 估 | 最均衡型：牛肉堡单品精选 + 麦麦脆汁鸡 ¥29 / 576 kcal / 蛋白质 34g |

三次调用均走真实 MCP 链路（门店 `1450104` 上海黄浦悦荟广场餐厅），
并各自附带热量贴士与性价比天梯榜。

**问题 D：门店数据串号（ demo 阶段发现）**
菜单与套餐详情原本共用一个缓存文件。查过北京门店后，上海门店的离线读取会
静默拿到北京数据——两者差异极小（麦香鸡沪 ¥17 / 京 ¥16.5），肉眼几乎不可察。
→ 改为按门店隔离的 `raw_meals_<code>.json` / `meal_details_<code>.json`，
并在缓存内写入来源门店标记，离线读取时校验，不一致直接报错而非给出错误答案。

### 已发现并如实记录的局限

第三例中「最饱型」给出「麦香鸡 + 派」——目标函数单纯最大化热量，与「减脂」意图存在冲突，
主食约束挡住了纯甜品组合，但没挡住「主食 + 甜品」。
此为已知缺陷，已在对话中向用户明确说明，后续拟增加「蛋白质优先模式」修正。

## 五、合规说明

- MCP Token 仅存于环境变量 `MCD_MCP_TOKEN`，未写入任何仓库文件
- `mcp-config.example.json` 只含 `YOUR_MCP_TOKEN` 占位符
- 已确认仓库内无真实 Token、密钥、邮箱或本机路径信息
- 项目未使用任何自动化手段获取 Star
