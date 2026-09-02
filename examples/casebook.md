# 真实测试案例库

这里记录 17 篇已经实际跑过、修改过的深度文章。案例的作用是帮助选择叙事结构、证据颗粒度和视觉组件，不是提供可复制的标题或事实。处理新文章时只读取最相近的 1-3 个案例，并重新抓取当前原文；旧案例和对标文章都不能直接进入新文章的研究账本。

## 富媒体与产品发布

### Seedance 2.5：长叙事、参考与定向编辑

- 原始材料：[字节跳动 Seed 发布文章](https://seed.bytedance.com/zh/blog/%E4%B8%80%E9%95%9C%E6%88%90%E7%89%87-%E9%9A%8F%E5%BF%83%E5%8F%82%E8%80%83-seedance-2-5-%E6%AD%A3%E5%BC%8F%E5%8F%91%E5%B8%83)。
- 测试标题：`字节跳动发布 Seedance 2.5：单次生成 30 秒，一次可调用 50 份参考素材`
- 可借鉴：产品发布标题优先放入读者最关心且已核实的具体规格。开篇用“4 分 22 秒官方短片与单次 30 秒生成”的真实反差建立问题，再按歌手长叙事、早餐时间戳、18 张参考图、白模与绿幕的演示顺序推进；“约束密度”保留为读完案例后的深层结论，不抢在开头解释。
- 视觉与媒体：从 10 段正文演示中按能力覆盖保留一组互补视频：首屏总览、长叙事案例、时间码操作、参考素材分工和制作流程各自回答不同问题时都可采用，不为追求短小一刀切。把提示词的时间段做成可拖动分镜，把有明确角色分工的参考素材做成可展开参考图谱，把冲突的官方说法做成带来源的紧凑对照；原始提示词只提取关键片段，避免整段倾倒，也不要再用一张通用能力大表和连续数字卡概括全部内容。
- 避免：为了页面短而只留少量代表视频、为了媒体完整而机械收录全部演示、把 Seed Edge 的 EdgeBench 视频混入产品证据，或用官方精选样片推断普遍成功率和生产稳定性。

### MiniMax Music 3：音乐模型与试听

- 原始材料：[MiniMax Music 3.0](https://www.minimax.io/blog/minimax-music-3-0-next-generation-open-weights-production-ready-versatile-music-model)；对标材料：[小互版本](https://best.xiaohu.ai/article/minimax-music-3/)。
- 测试标题：`MiniMax 把 5 分钟 AI 作曲模型开放下载：一句想法，真能做成完整歌曲吗？`
- 可借鉴：用“旧痛点 -> 输入怎样变成编排 -> 全局/局部分工 -> 部署与许可边界”推进；官方样曲使用播放器卡，必须同时给真实提示词、中文听感重点和证据边界。
- 避免：复制全部曲库、只放播放器不解释、把开放权重写成无条件开源，或把精选样曲外推成独立质量结论。

### Gemini 3.5 Transcribe：视频与语音转录

- 原始材料：[Google 发布文章](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-5-transcribe/)；对标材料：[小互版本](https://best.xiaohu.ai/article/gemini-3-5-transcribe/)。
- 测试标题：`Google 发布 Gemini 3.5 Transcribe：它为何不只想做听写`
- 可借鉴：先区分实时交互和预录处理，再解释模型如何整理表达、指标分别回答什么；有信息量的原始演示视频应嵌入相关章节并补中文观看重点。
- 避免：漏掉动态视频、同时堆两张近似图片、用低质量 AI 示意图替代真实产品画面，或把预览数据写成生产结论。

### LTX-2.5：视频模型与制作管线

- 原始材料：[LTX-2.5 发布文章](https://ltx.io/blog/the-foundation-film-is-made-on/)。
- 测试标题：`LTX-2.5 真正想卖的不是一段好视频，而是一条你能掌控的制作管线`
- 可借鉴：从“单段视频”重新定性为“制作流程”，按骨架生成、细节渲染、多镜头控制、部署选择和证据边界推进；流程图解释控制链，原始视频负责展示真实结果。
- 避免：把多个演示视频连续堆在一起、用装饰长图拉长页面，或仅凭架构故事宣称综合领先。

### Cloudflare OS：企业 AI 工作台

- 原始材料：[Cloudflare OS](https://blog.cloudflare.com/cloudflare-os/)；对标材料：[小互版本](https://best.xiaohu.ai/article/cloudflare-os/)。
- 测试标题：`Cloudflare 开源企业 AI 工作台：员工先要约十套系统的管理员权限，它才开始重做安全边界`
- 可借鉴：用真实员工动作进入，再从工作台定位、真人找需求、权限边界、审批队列、token 改造和 ROI 边界逐层展开；层级栈适合权限结构，决策表适合审批规则。
- 避免：把内部审计说明暴露在前端、用同一种卡片重复展示层级和类比，或把官方采用数字直接当外部 ROI。

### 比尔·盖茨的 AI 时代判断：政策评论与视频

- 原始材料：[Gates Notes](https://www.gatesnotes.com/home/home-page-topic/reader/a-turbulent-ai-era-and-critical-choices-to-make)；对标材料：[小互版本](https://best.xiaohu.ai/article/turbulent-ai-era-critical-choices/)。
- 测试标题：`比尔·盖茨最新 AI 警告：真正危险的不是机器变聪明，而是社会还没准备好`
- 可借鉴：围绕“能力扩散快于制度适应”组织企业压力、公共收益、滥用风险和三类治理选择；策略标签适合平行政策方案，有实质观点的视频才保留。
- 避免：为满足媒体数量加入无信息增量的视频、使用细长截图，或让数字条和类比卡视觉过于相似。

### a16z 科技风向：多图表主题综述

- 原始材料：[Winds of Thematic Change](https://www.a16z.news/p/charts-of-the-week-winds-of-thematic)。
- 测试标题：`a16z 最新图表：2026 年科技风向变了，资金正涌向核能、数据中心和 AI 智能体`
- 可借鉴：从大量图表中选择真正支撑主线的证据，连接资金、建设、算力资源、企业采用和自动化入口；情景计算器只用于让读者理解口径变化。
- 避免：照搬全部图表、连续放三张大型表格、用多个组件重复同一数字，或把同期上涨都归因于 AI。

## 技术论文、模型与代码仓库

### Apple 蒸馏缩放律：PDF 论文

- 原始材料：[Distillation Scaling Laws](https://arxiv.org/pdf/2502.08606v2)；对标材料：[小互版本](https://best.xiaohu.ai/article/distillation-scaling-laws/)。
- 测试标题：`Apple 把 AI 蒸馏算清了：最强老师，未必教得出最好学生`
- 可借鉴：用反常结果进入，随后解释损失口径、教师成本、有限数据区间和训练前决策；保留论文关键图、公式变量和实验条件，互动只帮助理解变量关系。
- 避免：把相关曲线简化成“老师越强越好/越差”、漏掉成本口径，或用装饰图替代论文证据图。

### Agent 消息感染：安全研究 PDF

- 原始材料：[论文 PDF](https://arxiv.org/pdf/2608.10218)。
- 测试标题：`AI Agent 的真正感染面：一条消息如何升级成下一轮系统指令`
- 可借鉴：先把抽象“思想感染”重定性为控制面升级，再区分实验口径、持久文件机制、内容保真、行动载荷、外推限制与治理；攻击链用流程图，关键论文图紧跟对应论点。
- 避免：沿用论文修辞制造神秘感、把受控实验写成开放网络事实，或因压缩篇幅漏掉人工条件和模型差异。

### Prime Intellect 多智能体 RL：机制解释

- 原始材料：[Multi-Agent Systems](https://www.primeintellect.ai/blog/multi-agent-systems)；对标材料：[小互版本](https://best.xiaohu.ai/article/prime-rl-multi-agent/)。
- 测试标题：`多智能体 RL 真正改了什么？Prime Intellect 把奖励归因放进环境`
- 可借鉴：围绕唯一机制“环境安排互动并分配训练信号”，按模型与环境职责、互动类型和证据边界推进；流程图说明调用关系，对比表只比较同层职责。
- 避免：把“多智能体”误写成简单增加模型数量，或在没有训练效果证据时宣称方法更有效。

### X For You 算法：GitHub 仓库深读

- 原始材料：[xai-org/x-algorithm](https://github.com/xai-org/x-algorithm)；对标材料：[小互版本](https://best.xiaohu.ai/article/x-algorithm-open-source/)。
- 测试标题：`X 开源 For You 算法：复制链接权重 20，点赞只有 0.5`
- 可借鉴：从仓库关键文件重建候选、打分、过滤三道关；排名条展示同口径权重，漏斗展示逐级筛选，互动对比解释用户动作如何改变信号。
- 避免：只读 README、把权重当最终曝光概率，或让表格、漏斗和排名条重复同一层信息。

### OpenAI Jalapeno：芯片基准

- 原始材料：[Jalapeno First Results](https://openai.com/index/jalapeno-first-results/)；对标材料：[小互版本](https://best.xiaohu.ai/article/jalapeno-first-results/)。
- 测试标题：`OpenAI 首款定制推理芯片 Jalapeno 首测：三款大模型都更快、更省电`
- 可借鉴：标题先说清芯片归属；从方向性结果进入，解释瓶颈怎样变化，再用紧凑指标条展示同口径基准并贴近限制。
- 避免：一次摆三张大表、用陌生项目名掩盖 OpenAI、混淆芯片与整机口径，或把首测写成生产终局。

### Claude 文本水印：机制与检测边界

- 原始材料：[Anthropic 公告](https://www.anthropic.com/news/claude-text-watermark)。
- 测试标题：`Anthropic 为 Claude 加入文本水印：工作原理与检测边界`
- 可借鉴：用候选词与随机源互动解释水印写入，再依次讨论质量、可检出条件、阳性/阴性边界和机构使用方式；独立材料只支持其实际验证的方法。
- 避免：把模型参与等同作者身份、把其他实现的实验直接替 Claude 私有配置背书，或虚构学校和企业真实案例。

## 事件、调查与组织故事

### OpenAI friction 邮箱：组织机制

- 原始材料：[Fortune 报道](https://fortune.com/2026/08/11/openai-employees-email-friction-address-to-eliminate-bureaucratic-bottlenecks-sam-altman/)；对标材料：[小互版本](https://best.xiaohu.ai/article/openai-friction-email/)。
- 测试标题：`OpenAI 用一个邮箱对抗官僚主义：员工一封信，可能让整个团队改优先级`
- 可借鉴：用停车位、API 额度等具体小事建立代入，再解释高层注意力如何重排优先级，以及投诉者收益与执行团队改期成本之间的冲突。
- 避免：用含义不清的中文专名替代原始叫法、从抽象组织理论开场，或把相关性写成 OpenAI 快速发展的唯一原因。

### Claude 进入 CI/CD 和值班：工程事件链

- 原始材料：[Claude on-call](https://claude.com/blog/ai-ci-cd-on-call)；对标材料：[小互版本](https://best.xiaohu.ai/article/ai-ci-cd-on-call-v4/)。
- 测试标题：`Anthropic 把 Claude 塞进值班群：44 项测试消失后，它 3 分钟确认恢复`
- 可借鉴：用具体事故和时间进入，按诊断、值班记忆、修复建议、验证与人工上线边界推进；时间线表现事件顺序，对比表表现职责差异。
- 避免：把不同层级内容强行并排、使用“分母、边界、如何被接住”等语义不明标签，或把整篇文章做成同一种纵向卡片。

### ChatGPT 暴力计划报告：敏感新闻

- 原始材料：[Palm Beach Post 报道](https://www.palmbeachpost.com/story/news/crime/2026/08/14/openai-reported-florida-man-darren-zhou-chatgpt-murder-messages-fbi/91285875007/)。
- 测试标题：`他把杀人计划告诉 ChatGPT，结果 OpenAI 报了警`
- 可借鉴：首屏交代人物、时间、地点、计划、报告、逮捕和司法结果；时间线区分 OpenAI、FBI、警方、检方和法院的动作，隐私解释区分主动报告与政府索取。
- 避免：写成“AI 自动报警抓人”、把匿名或辩方说法当法院事实，或用其他事件制造未经证实的直接因果。

### AliExpress 无声音频：技术调查故事

- 原始材料：[调查文章](https://blog.laserphile.com/2026/08/aliexpress-webpage-keeping-multipoint.html)。
- 测试标题：`阿里旗下 AliExpress，被发现用“无声音频”给用户设备验指纹`
- 可借鉴：从耳机被网页抢占的怪事进入，按排除播放器、定位 AudioContext、解释零增益任务、推断用途和划定指纹边界推进；证据截图和技术流程分别承担“发现了什么”和“为什么会这样”。
- 避免：把推断写成已证实监控、把单一音频特征写成设备身份证，或为了短而删掉关键调查链。
