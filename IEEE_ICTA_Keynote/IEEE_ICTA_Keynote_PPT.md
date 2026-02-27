# PPT 逐页内容脚本
## From Cloud to Edge: Building AI Computing Infrastructure for the Age of Embodied Intelligence
### 27 slides | ~35 minutes

设计风格: 深色背景(#1a1a2e) + 白色文字 + 亮色强调(蓝#0ea5e9, 橙#f97316, 绿#22c55e)
字体: 英文 Montserrat/Inter, 中文备用

---

### SLIDE 1 — Title

```
[大字居中]
From Cloud to Edge
Building AI Computing Infrastructure
for the Age of Embodied Intelligence

[小字]
Chao Chen
General Manager, Suzhou Chuangjie Intelligent Technology
Vice Chair, Supercomputing & Intelligent Computing Committee, CCIA

IEEE ICTA 2026 | Singapore | October 2026
```

视觉: 深色背景，左下角抽象电路板纹理渐变到右上角机器人轮廓

---

### SLIDE 2 — About Me

```
[三列时间轴, 从左到右]

📐 Quantitative Trading    →    🏗️ AI Computing Centers    →    🤖 Embodied Intelligence
Applied Mathematics              Operating GPU clusters           Investing in humanoid robots
High-frequency computation        at national scale                LingShen Tech | TIEN Kung
"Compute = Profit"               "Compute = Infrastructure"       "Compute = Autonomy"
```

视觉: 水平时间轴, 三个节点用渐变线连接, 每个节点一个图标

---

### SLIDE 3 — Three Waves of Compute

```
[标题] Three Waves of Compute Demand

[折线图, X轴=时间, Y轴=计算需求(对数)]

Wave 1: Quantitative Finance (2010s)
  - Microsecond latency matters
  - Every compute cycle = money

Wave 2: AI Training (2020s)
  - GPU clusters at scale
  - Petaflops of throughput

Wave 3: Embodied AI (2026→)
  - Real-time on-body inference
  - Milliwatt-level efficiency

[右下角引述]
"Each wave demands fundamentally different IC design."
```

---

### SLIDE 4 — The Numbers

```
[标题] AI Compute: The Numbers

[三个大数字, 横排]

2/3                    $50B+                   31%
of all AI compute      inference chip           embodied AI
is inference (2026)    market (2026)            market CAGR

[底部来源] Deloitte TMT Predictions 2026 | Omdia Market Radar 2026
```

视觉: 三个超大数字, 亮蓝色, 下面灰色小字注释

---

### SLIDE 5 — Section Divider: Cloud

```
[全屏大字]

PART I
The Cloud
Operating AI at Scale

[背景: 数据中心机柜走廊照片, 加深色蒙版]
```

---

### SLIDE 6 — Scale of the Challenge

```
[标题] China's Intelligent Computing Centers

200+                   intelligent computing centers built since 2023

10,000+                GPU accelerators per large facility

<30%                   average GPU utilization rate

[底部]
"The system-level challenges dominate everything."
```

视觉: 三个数字纵向排列, 红色/黄色/白色渐变

---

### SLIDE 7 — Challenge 1: Thermal

```
[标题] Challenge #1: Thermal Management

[左侧]                          [右侧]
Single accelerator: 700W+        Air cooling → Liquid cooling
Single rack: 40-80 kW            PUE: 1.4 → 1.15
                                  = millions saved per year

[底部金句]
"Your chip's TDP is not a spec — it's a cost multiplier."

[建议配图: 液冷管道/冷板实拍]
```

---

### SLIDE 8 — Challenge 2: Power

```
[标题] Challenge #2: Power Supply

[信息图]
1,000 GPUs = 1 MW
10,000 GPUs = 10 MW = a small town

[中国地图示意, 标注]
East China: ¥0.8/kWh → expensive
West China: ¥0.3/kWh → AI moves west

[底部金句]
"Power is the new oil of the AI era."
```

---

### SLIDE 9 — Challenge 3: Utilization

```
[标题] Challenge #3: GPU Utilization

[仪表盘图, 指针指向 <30%]
Average GPU utilization: <30%

Why?
• Multi-tenant scheduling is hard
• Memory fragmentation between model sizes
• Daily hardware failures at scale
• Recovery and job migration overhead

[底部金句]
"Utilization rate matters more than total capacity."
```

---

### SLIDE 10 — Cloud Lessons for IC

```
[标题] What Cloud Operations Teach IC Designers

✅ 1. Design for system deployability, not benchmarks
✅ 2. Performance per watt > peak performance
✅ 3. Build diagnostics into the silicon
✅ 4. Reliability over years, not hours

[底部]
"The best chip is the one that runs stable at 85% load for 365 days."
```

视觉: 四行清单式, 每行前面绿色勾号

---

### SLIDE 11 — Section Divider: Embodied AI

```
[全屏大字]

PART II
From Racks to Bodies
When Compute Walks Out of the Data Center

[背景: 人形机器人照片, 加深色蒙版]
```

---

### SLIDE 12 — Why Embodied Intelligence

```
[标题] Why I Invest in Embodied AI

"I asked the engineering teams:
 What is your biggest bottleneck?"

❌ Not funding
❌ Not algorithms
✅ On-body compute

"The available processors simply cannot deliver
 what we need within our power and size constraints."
```

视觉: 暗背景, 引号高亮, 三行排除法用红×绿✓

---

### SLIDE 13 — LingShen Technology

```
[标题] Portfolio: LingShen Technology (灵生科技)

• Tsinghua University origin, founded 2023
• Universal brain platform for humanoid robots
• Self-developed:
  - LDP: Real-world Data Collection Platform
  - LWM: Embodied World Model
• Deployed: smart manufacturing, retail, healthcare
• Pre-A/Pre-A+ funding: >100M RMB

[建议配图: 灵生机器人产品照片]
```

---

### SLIDE 14 — TIEN Kung

```
[标题] Portfolio: TIEN Kung 天工

• Beijing Innovation Center of Humanoid Robotics
• Supported by MIIT + Beijing Municipality
• World's first pure-electric full-size humanoid running at 6 km/h
• v3.0 (Feb 2026): touch-interactive, high-dynamic whole-body control
• Open-source platform strategy

[建议配图: 天工3.0机器人照片]
```

---

### SLIDE 15 — Cloud vs On-Body Comparison

```
[标题] Cloud Chips vs. On-Body Chips: Two Worlds

                   Cloud                On-Body
─────────────────────────────────────────────────
Compute         PetaFLOPS            TeraOPS
Power           700W (rack cooled)    <50W (battery)
Latency         ~1 second OK          <10ms required
Failure mode    Swap & restart        Cannot fail
Workload        Single model          Multi-modal simultaneous
Form factor     Rack-mounted          Fits in torso
Cost target     $30,000/card          <$500/unit
```

视觉: 干净的对比表, 左列蓝色, 右列绿色, 关键差异红色加粗

---

### SLIDE 16 — The Core Insight

```
[全屏大字, 居中]

"Cloud computing's challenge:
 fitting chips into racks.

 Embodied computing's challenge:
 fitting racks into bodies."

[小字底部]
These require fundamentally different IC design philosophies.
```

视觉: 纯文字页, 极简, 文字分两行对称

---

### SLIDE 17 — Three-Tier Architecture

```
[标题] The Three-Tier Compute Architecture for Embodied AI

┌─────────────────────────────┐
│  ☁️  CLOUD                    │  Model training, world model updates
│  GPU Cluster                 │  Timescale: hours / days
│  Existing infrastructure     │
└──────────────┬──────────────┘
               │  Model download (non-realtime)
┌──────────────▼──────────────┐
│  🏭 EDGE                     │  Scene-specific inference, multi-robot coordination
│  Edge Server                 │  Timescale: ~100ms
│  100-300W                    │
└──────────────┬──────────────┘
               │  Real-time commands
┌──────────────▼──────────────┐
│  🤖 ON-BODY                  │  Perception, safety, autonomous control
│  SoC / NPU                  │  Timescale: <10ms
│  <50W                        │
└─────────────────────────────┘
```

视觉: 三层堆叠图, 上蓝中橙下绿, 箭头连接, 动画可逐层展开

---

### SLIDE 18 — IC Demands per Tier

```
[标题] IC Demands by Compute Tier

        Cloud              Edge               On-Body
────────────────────────────────────────────────────────
Key IC   GPU / AI          Inference           Heterogeneous
type     accelerator       accelerator         SoC

Power    400-700W          100-300W            <50W

Key      Interconnect      Multi-model         Multi-modal
challenge bandwidth        scheduling          integration

Market   Mature            Exploding           Greenfield
status                                         🟢 BIGGEST OPPORTUNITY
```

视觉: 三列, 底部"BIGGEST OPPORTUNITY"用绿色高亮框

---

### SLIDE 19 — Section Divider: Recommendations

```
[全屏大字]

PART III
Recommendations
for IC Designers

[背景: 芯片晶圆微距照片, 加蒙版]
```

---

### SLIDE 20 — For Cloud Chip Designers

```
[标题] For Cloud / Data Center Chip Designers

1️⃣  Performance per watt > peak performance
    Your customer's #1 cost is electricity

2️⃣  Standardize interconnects
    Proprietary = lock-in = slow adoption

3️⃣  Build diagnostics into silicon
    Remote monitoring is an operational necessity

4️⃣  Design for multi-tenant workloads
    Hardware isolation improves utilization
```

视觉: 四行, 每行编号+粗体标题+灰色注释, 左侧蓝色竖线装饰

---

### SLIDE 21 — For Embodied Chip Designers

```
[标题] For Edge / Embodied Chip Designers

1️⃣  Heterogeneous compute is mandatory
    CNN + Transformer + Control on one die

2️⃣  Power is the hard constraint
    Design to 50W first, then maximize compute

3️⃣  Latency > throughput
    One result in 5ms, not 1000 results per second

4️⃣  Safety is non-negotiable
    Functional safety, error correction, graceful degradation

5️⃣  Cost at scale: <$500/unit
    A $200K robot will never reach mass adoption
```

视觉: 五行, 绿色竖线, 第四行安全用红色强调

---

### SLIDE 22 — The Bridging Insight

```
[全屏引述]

"The best chip is never the one
 with the highest benchmark score.

 It is the one that runs reliably,
 efficiently, and affordably
 in its target deployment environment."

— From quantitative trading,
  through data centers,
  to robots.
```

---

### SLIDE 23 — Looking Ahead

```
[标题] Looking Ahead

2026    "Inference Famine"
        Demand for inference compute outpaces supply

2027    First wave of mass-produced humanoid robots
        Logistics, manufacturing, elder care

2028+   On-body AI compute market
        Comparable in scale to smartphone SoC market

[底部]
Every robot = a mobile computing platform
Aggregate demand = enormous new IC market
```

视觉: 竖向时间轴, 三个年份节点, 逐步展开

---

### SLIDE 24 — Convergence Visual

```
[标题] The Convergence

[三个圆交叉的韦恩图]

         ┌─────────┐
         │  Cloud   │
         │  AI      │
         └───┬─────┘
    ┌────────┼────────┐
    │  Edge  │On-Body │
    │  AI    │ AI     │
    └────────┴────────┘

Center intersection: "The IC Opportunity"

Each circle label:
Cloud: Training chips (mature)
Edge: Inference chips (growing)
On-Body: Embodied SoCs (emerging)
```

---

### SLIDE 25 — Call to Action

```
[标题] For Everyone in This Room

You are designing the nervous system
of tomorrow's intelligent machines.

Your decisions on:
  • Architecture
  • Power efficiency
  • Reliability

will determine whether embodied AI
becomes reality — or stays in the lab.
```

视觉: 简洁文字, "nervous system"用亮色强调

---

### SLIDE 26 — Closing Quote

```
[全屏, 分段动画]

"I started optimizing compute for financial models,
 where microseconds meant money.

 I then built computing centers,
 where power efficiency meant survival.

 Now I invest in robots,
 where real-time inference means safety."

Advancing IC with AI.
Advancing AI with IC —
from the cloud, through the edge, into the body.
```

视觉: 三段分行, 逐段出现, 最后一行金色

---

### SLIDE 27 — Thank You

```
[居中]

Thank You
谢谢

Chao Chen 陈超
chenchao@chuangjie.tech  [替换为实际邮箱]

Suzhou Chuangjie Intelligent Technology Co., Ltd.
苏州创杰智能科技有限公司

[IEEE ICTA 2026 logo]
```

---

## 附: PPT 制作技术说明

**推荐工具:** PowerPoint 或 Keynote
**比例:** 16:9
**总页数:** 27页
**预计时长:** 27页 / 35分钟 ≈ 每页1.3分钟

**配图需求清单:**
| Slide | 需要的图片 |
|-------|-----------|
| 1 | 抽象电路板+机器人轮廓(可用AI生成) |
| 5 | 数据中心走廊照片(可用库图) |
| 7 | 液冷设备实拍(如有自己的最佳) |
| 11 | 人形机器人照片(可用库图) |
| 13 | 灵生科技产品照片(找公司要) |
| 14 | 天工3.0照片(官网可下载) |
| 19 | 芯片晶圆微距照片(库图) |

**动画建议:**
- Slide 3 (三波浪): 折线逐段出现
- Slide 17 (三层架构): 自上而下逐层展开
- Slide 23 (展望): 年份逐个出现
- Slide 26 (结束语): 三段话逐段出现
- 其他页面: 不加动画, 保持干净
