# MCP 接入说明

说明本项目实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## 1. 接入方式

| 项 | 值 |
|---|---|
| MCP Server | 麦当劳中国 MCP Server（`mcd-mcp`，version 1.0.0） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（JSON-RPC 2.0） |
| 鉴权 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| 限流 | 600 次 / 分钟 |
| 配置文件 | `mcp-config.example.json` |

Token 申请：[https://open.mcd.cn/mcp](https://open.mcd.cn/mcp) → 手机号登录 → 控制台 → 激活。

Token 只从环境变量 `MCD_MCP_TOKEN` 读取，**不写入任何仓库文件**。

## 2. 实际使用的 Tool

共使用 6 个 Tool，跨「时间 / 门店 / 菜单 / 营养 / 价格」5 个能力域。

| Tool | 用途 | 在本项目中的作用 |
|---|---|---|
| `now-time-info` | 获取当前时间 | 判定早餐 / 正餐时段。麦当劳早餐与正餐菜单不同，取错菜单会导致整个求解结果失效 |
| `query-nearby-stores` | 查询附近门店 | 拿 `storeCode`。菜单与价格都依赖门店，这是后续所有调用的前置 |
| `query-meals` | 查询门店可售餐品 | 求解器的候选来源（含分类、餐品编码、现价、原价） |
| `list-nutrition-foods` | 餐品营养信息列表 | 热量 / 蛋白质 / 脂肪 / 碳水 / 钠 / 钙，双约束求解的第二条约束来源 |
| `query-meal-detail` | 餐品详情 | **关键**：拆解套餐子项 + 解析杯型默认规格 |
| `calculate-price` | 商品价格计算 | 复核最终候选的真实应付价（含优惠与配送费），避免自行加总出错 |

另有 `query-my-coupons` / `query-store-coupons` 可用于券的进一步利用，当前版本未纳入求解，
已在路线图中列出。

## 3. 调用流程

```
now-time-info
   └─→ 判定时段（早餐 / 正餐）
        └─→ query-nearby-stores  （beType=1 到店自提）
             └─→ 拿到 storeCode
                  ├─→ query-meals          → 候选餐品 + 现价
                  └─→ list-nutrition-foods → 营养数据（158 条）
                       └─→ 名称严格匹配
                            ├─ 匹配成功 → 直接取用
                            └─ 匹配失败 → query-meal-detail 拆解
                                 ├─ 套餐：各 round 默认子项逐项匹配后累加
                                 ├─ 杯型未指定（如「可乐」）→ 取默认规格
                                 └─ 仍缺失 → 标注缺失并排除
                       └─→ 双约束全枚举求解（预算 × 热量）
                            └─→ calculate-price 复核 Top 候选
                                 └─→ 输出三套方案 + 热量贴士 + 天梯榜
```

## 4. 数据对齐：本项目最关键的一步

麦当劳营养库（`list-nutrition-foods`）**只收录常规单品，不收录套餐**。
而 `query-meals` 返回的 121 项里有 51 项是套餐（三件套、四件套、分享盒等）。
要算准套餐热量，必须拆解。

`query-meal-detail` 返回的结构包含 `rounds[].choices[]`，每个 choice 带
`isDefault`、`quantity`、`diffPrice` 和 `modification`。以「麦辣鸡腿汉堡三件套」为例：

```
round 1  麦辣鸡腿汉堡          isDefault=1  diffPrice +¥0
round 2  中薯条                isDefault=1  diffPrice +¥0
         大薯条                isDefault=0  diffPrice +¥2.5
         小杯玉米杯            isDefault=0  diffPrice -¥0.5
round 3  可乐中杯              isDefault=1  diffPrice +¥0
```

取各 round 的 `isDefault=1` 子项，逐项匹配营养后累加，即得套餐真实营养。

### 为什么不做模糊匹配

开发过程中实测：用 `difflib` 模糊匹配（cutoff 0.62）时，
`巨无霸三件套` 被匹配到 `巨无霸`（相似度 0.67）。但三件套还含中薯条和可乐中杯，
**真实热量约为单品的 2 倍以上**。这类「看起来匹配上了其实错了」的问题
比「匹配不上」危险得多，会静默污染全部结果。

因此本项目的策略是：

1. 只做**严格相等匹配**（忽略空格与常见符号）
2. 匹配失败则走 `query-meal-detail` 拆解
3. 任一子项缺失 → 整个套餐判为缺失并排除
4. **绝不估算、绝不用近似值兜底**

当前 121 项餐品中，55 项可精确计算，其余为当季限定新品或规格歧义项，
在输出末尾明确标注「已排除 N 项营养数据缺失的餐品，不做估算」。

## 5. 业务价值

| 维度 | 说明 |
|---|---|
| **对用户** | 把「预算」和「热量」这两个同时存在、但现有工具各管一半的约束合并求解；一次给出三套方案而非单一答案 |
| **对麦当劳** | `list-nutrition-foods` 与官方菜单里已有的「500 大卡套餐」分类形成呼应，把官方已有的健康心智延伸到自由组合场景 |
| **对开发者** | 沉淀了一套可复用的「菜单—营养」对齐方案（严格匹配 + 套餐拆解 + 缺失标注），同类点餐类 Skill 都会遇到同样问题 |

## 6. 踩坑记录（给后来者）

1. `query-nearby-stores` 的 `searchType=2` **必须同时传 `city` 和 `keyword`**，
   只传一个会返回 `600058 城市名或者关键词不能为空`。
2. `list-nutrition-foods` 的返回**不是 JSON**，而是形如
   `[160]{productName,...}:\n  猪柳麦满分,null,1288,308,...` 的自定义分隔文本，需要自行解析。
3. 各 Tool 的业务数据被包在 markdown 说明里（`## Original Response` 段），
   需要剥掉外壳再解析，见 `scripts/mcp_client.py` 的 `_extract_json`。
4. 到店自提（beType=1）返回的门店**没有 beCode**，后续调用不要传；
   外送 / 得来速 / 团餐场景才需要。
5. `modification` 字段里带「麦香鸡酱」「切块生菜」这类可选项及差价，
   是实现「去掉酱料能省多少大卡」这类贴士的数据基础。
