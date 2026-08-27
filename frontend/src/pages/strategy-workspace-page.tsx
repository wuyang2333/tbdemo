import {
  AppstoreOutlined,
  BookOutlined,
  BulbOutlined,
  CalendarOutlined,
  CalculatorOutlined,
  EditOutlined,
  EyeOutlined,
  ExperimentOutlined,
  FileDoneOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FundOutlined,
  LineChartOutlined,
  NotificationOutlined,
  PictureOutlined,
  RadarChartOutlined,
  SearchOutlined,
  ShopOutlined,
  ShoppingOutlined,
  TagsOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Alert, Card, Col, Row, Space, Steps, Tag, Typography } from "antd";
import type { ReactNode } from "react";

import { PageHeader } from "../components/ui/page-header";

const { Paragraph, Text, Title } = Typography;

type WorkspaceSection = {
  workspace: string;
  title: string;
  description: string;
  objective: string;
  icon: ReactNode;
  capabilities: string[];
  inputs: string[];
  outputs: string[];
};

const SECTIONS: Record<string, WorkspaceSection> = {
  "promotion-budget": {
    workspace: "推广管理",
    title: "预算与预警中心",
    description: "统一管理店铺、场景和计划预算，沉淀可解释的投放预警。",
    objective: "回答“预算是否花得合理，哪些异常需要立即处理”。",
    icon: <FundOutlined />,
    capabilities: ["预算进度与预测", "预算分配建议", "异常预警规则", "预警转任务闭环"],
    inputs: ["计划预算", "实时花费", "成交与利润", "目标与底线"],
    outputs: ["预算看板", "投放预警", "处理任务", "执行验证"],
  },
  "promotion-assets": {
    workspace: "推广管理",
    title: "商品与素材中心",
    description: "关联商品、主图、视频和详情页版本，识别真正带来转化的投放资产。",
    objective: "回答“预算具体花在哪些商品和素材上，哪些值得继续放大”。",
    icon: <PictureOutlined />,
    capabilities: ["商品投放表现", "素材版本管理", "素材效果归因", "素材疲劳识别"],
    inputs: ["商品与 SKU", "主图与视频", "计划关联", "点击与成交"],
    outputs: ["商品排行", "素材排行", "高效卖点", "替换建议"],
  },
  "promotion-targets": {
    workspace: "推广管理",
    title: "关键词与人群中心",
    description: "统一沉淀关键词、人群包及其与计划和商品的承接关系。",
    objective: "回答“哪些词和人群带来有效成交，哪些正在浪费预算”。",
    icon: <SearchOutlined />,
    capabilities: ["关键词分层", "搜索词挖掘", "人群表现", "浪费识别"],
    inputs: ["关键词报表", "人群包", "计划投放", "成交与退款"],
    outputs: ["词库", "否定词建议", "人群排行", "优化清单"],
  },
  "promotion-experiments": {
    workspace: "推广管理",
    title: "实验与归因中心",
    description: "记录投放调整、观察窗口和结果，判断策略是否真正有效。",
    objective: "回答“这次投放变化带来的增长是否可复制”。",
    icon: <ExperimentOutlined />,
    capabilities: ["实验假设", "版本对比", "观察窗口", "结果与复盘"],
    inputs: ["计划变更", "商品与素材版本", "核心指标", "活动日历"],
    outputs: ["实验结论", "增量评估", "策略模板", "复盘案例"],
  },
  "monitoring-overview": {
    workspace: "竞品监控",
    title: "竞品监控总览",
    description: "集中查看重点竞品、核心商品和关键经营动作的最新变化。",
    objective: "回答“今天哪些竞品发生了值得关注的变化，应该先处理什么”。",
    icon: <EyeOutlined />,
    capabilities: ["核心变化摘要", "竞品表现排行", "监控任务状态", "异常与机会聚合"],
    inputs: ["竞品店铺", "竞品商品", "价格与活动", "搜索与内容变化"],
    outputs: ["每日竞品动态", "重点预警", "机会线索", "跟进任务"],
  },
  "competitor-shops": {
    workspace: "竞品监控",
    title: "竞品店铺库",
    description: "维护直接竞品、标杆店铺和潜在竞争者的分层档案。",
    objective: "回答“我们真正需要关注谁，以及每个竞品为什么值得监控”。",
    icon: <ShopOutlined />,
    capabilities: ["竞品分组与标签", "店铺档案", "经营指标对比", "监控范围与频率"],
    inputs: ["店铺链接", "主营类目", "商品结构", "公开经营信号"],
    outputs: ["竞品清单", "竞品画像", "标杆分组", "监控配置"],
  },
  "competitor-products": {
    workspace: "竞品监控",
    title: "竞品商品追踪",
    description: "跟踪竞品核心商品、新品、爆品和商品结构变化。",
    objective: "回答“竞品在主推什么、哪些商品正在起量、我们该如何应对”。",
    icon: <ShoppingOutlined />,
    capabilities: ["重点商品监控", "新品与爆品识别", "销量评价趋势", "商品版本快照"],
    inputs: ["商品链接", "销量与评价", "主图标题", "SKU 与属性"],
    outputs: ["商品趋势", "新品清单", "爆品信号", "差异化建议"],
  },
  "competitor-pricing": {
    workspace: "竞品监控",
    title: "价格与活动追踪",
    description: "记录竞品标价、到手价、优惠机制和大促节奏变化。",
    objective: "回答“竞品什么时候降价、用了什么优惠、是否会影响我们的转化”。",
    icon: <FundOutlined />,
    capabilities: ["价格历史曲线", "优惠拆解", "活动日历", "价格变化预警"],
    inputs: ["标价与到手价", "优惠券", "满减赠品", "活动时间"],
    outputs: ["价格档案", "活动对比", "降价预警", "应对建议"],
  },
  "competitor-radar": {
    workspace: "竞品监控",
    title: "竞品动作雷达",
    description: "捕捉上新、换图、改标题、内容投放和店铺活动等经营动作。",
    objective: "回答“竞品最近做了什么动作，这些动作可能释放什么经营信号”。",
    icon: <NotificationOutlined />,
    capabilities: ["页面变更识别", "上新与下架追踪", "内容动作追踪", "重要程度评分"],
    inputs: ["商品页面快照", "店铺上新", "直播与短视频", "活动页面"],
    outputs: ["动作时间线", "变化对比", "重要信号", "待验证假设"],
  },
  "competitor-reports": {
    workspace: "竞品监控",
    title: "竞品分析报告",
    description: "把分散的监控变化整理为周报、专题分析和行动建议。",
    objective: "回答“本周竞争格局发生了什么变化，我们接下来应该采取什么动作”。",
    icon: <FileSearchOutlined />,
    capabilities: ["竞品周报", "专题对比", "变化原因归纳", "行动建议跟踪"],
    inputs: ["监控变化", "重点预警", "店铺数据", "运营记录"],
    outputs: ["竞品周报", "专题报告", "应对清单", "历史结论"],
  },
  "content-overview": {
    workspace: "内容运营",
    title: "内容运营总览",
    description: "汇总选题、生产、发布和效果，掌握内容团队整体节奏。",
    objective: "回答“内容团队正在做什么、进度是否正常、哪些内容值得继续放大”。",
    icon: <FileTextOutlined />,
    capabilities: ["内容数据总览", "生产进度", "渠道表现", "高潜内容识别"],
    inputs: ["内容计划", "素材与稿件", "发布记录", "互动与转化"],
    outputs: ["内容看板", "进度预警", "优秀内容", "本周行动"],
  },
  "content-topics": {
    workspace: "内容运营",
    title: "选题策划中心",
    description: "从商品卖点、用户需求、热点和竞品内容中形成可执行选题。",
    objective: "回答“接下来应该创作什么内容，面向谁、解决什么问题”。",
    icon: <BulbOutlined />,
    capabilities: ["选题池", "用户需求归类", "热点与竞品参考", "选题评分"],
    inputs: ["商品卖点", "搜索与问答", "用户评价", "热点与竞品内容"],
    outputs: ["选题清单", "内容 brief", "优先级", "创作任务"],
  },
  "content-calendar": {
    workspace: "内容运营",
    title: "内容日历",
    description: "统一安排不同渠道、商品和活动节点的内容发布节奏。",
    objective: "回答“什么时候、在哪个渠道、发布什么内容，由谁负责”。",
    icon: <CalendarOutlined />,
    capabilities: ["月周日排期", "渠道排期", "活动节点联动", "负责人和状态"],
    inputs: ["营销日历", "选题池", "渠道计划", "人员产能"],
    outputs: ["内容排期", "发布任务", "延期提醒", "渠道节奏"],
  },
  "content-assets": {
    workspace: "内容运营",
    title: "内容素材库",
    description: "管理图片、视频、文案、商品卖点和可复用内容组件。",
    objective: "回答“有哪些素材可以直接使用，是否合规，历史效果如何”。",
    icon: <PictureOutlined />,
    capabilities: ["素材分类与标签", "版本管理", "授权与合规", "素材效果关联"],
    inputs: ["图片与视频", "文案模板", "品牌规范", "历史投放效果"],
    outputs: ["可用素材", "内容组件", "授权记录", "高效素材模板"],
  },
  "content-studio": {
    workspace: "内容运营",
    title: "内容创作工作台",
    description: "围绕商品和选题完成文案、图文、短视频脚本与版本协作。",
    objective: "回答“如何更快产出符合品牌要求、适配不同渠道的内容版本”。",
    icon: <EditOutlined />,
    capabilities: ["内容 brief", "AI 辅助创作", "多渠道改写", "审核与版本协作"],
    inputs: ["选题 brief", "商品信息", "品牌规范", "参考素材"],
    outputs: ["图文稿件", "短视频脚本", "渠道版本", "待审内容"],
  },
  "content-performance": {
    workspace: "内容运营",
    title: "发布与效果复盘",
    description: "记录内容发布结果，并关联曝光、互动、引流和成交表现。",
    objective: "回答“哪些内容真正带来了业务结果，成功经验能否被复制”。",
    icon: <LineChartOutlined />,
    capabilities: ["发布记录", "渠道指标对比", "内容归因", "高表现模式提炼"],
    inputs: ["发布链接", "曝光互动", "进店与成交", "内容标签"],
    outputs: ["效果排行", "内容复盘", "创作建议", "可复用模式"],
  },
  opportunities: {
    workspace: "市场洞察",
    title: "选品与市场机会",
    description: "从需求、竞争、价格带和利润空间中筛选值得进入的市场。",
    objective: "回答“接下来应该卖什么、为什么值得卖、先验证哪一个”。",
    icon: <AppstoreOutlined />,
    capabilities: ["类目与价格带趋势", "市场需求与竞争强度", "候选商品池", "机会评分与选品决策"],
    inputs: ["类目数据", "关键词趋势", "竞品商品", "成本与售价"],
    outputs: ["机会清单", "候选商品", "选品评分", "验证计划"],
  },
  keywords: {
    workspace: "市场洞察",
    title: "关键词运营中心",
    description: "统一管理店铺词库、搜索排名、商品承接和推广表现。",
    objective: "回答“哪些词值得争、由哪个商品承接、下一步怎么优化”。",
    icon: <SearchOutlined />,
    capabilities: ["关键词分组与标签", "自然与付费排名", "标题覆盖诊断", "机会词与流失词识别"],
    inputs: ["搜索词", "商品标题", "自然流量", "推广关键词"],
    outputs: ["店铺词库", "优化清单", "排名预警", "商品承接关系"],
  },
  radar: {
    workspace: "市场洞察",
    title: "经营机会雷达",
    description: "持续扫描市场、商品、流量、评价和竞品中的增长信号。",
    objective: "回答“今天有哪些值得抓住的机会，以及应由谁处理”。",
    icon: <RadarChartOutlined />,
    capabilities: ["机会信号聚合", "价值与紧急度评分", "机会订阅", "转任务与结果跟踪"],
    inputs: ["市场趋势", "竞品变化", "店铺数据", "客户反馈"],
    outputs: ["每日机会", "优先级评分", "负责人任务", "机会转化记录"],
  },
  products: {
    workspace: "增长实验室",
    title: "商品策略中心",
    description: "定义商品角色、生命周期和资源投入策略。",
    objective: "回答“每个商品承担什么角色，应该加码、观察还是退出”。",
    icon: <TagsOutlined />,
    capabilities: ["商品角色矩阵", "生命周期识别", "资源分配建议", "主推与淘汰清单"],
    inputs: ["商品表现", "利润数据", "库存水位", "推广投入"],
    outputs: ["商品分层", "经营策略", "资源计划", "本周行动清单"],
  },
  pricing: {
    workspace: "增长实验室",
    title: "价格与促销中心",
    description: "管理价格、优惠、利润底线和活动节奏。",
    objective: "回答“怎么促销既有竞争力，又不突破利润和价格风险底线”。",
    icon: <FundOutlined />,
    capabilities: ["全店价格体检", "优惠方案管理", "利润底价保护", "促销日历与恢复检查"],
    inputs: ["标价与到手价", "商品成本", "优惠规则", "竞品价格"],
    outputs: ["调价建议", "促销方案", "风险预警", "活动价格档案"],
  },
  simulator: {
    workspace: "增长实验室",
    title: "经营沙盘",
    description: "在调价、投放和备货之前模拟收入、利润和风险。",
    objective: "回答“这个方案在保守、正常、理想情景下分别会怎样”。",
    icon: <CalculatorOutlined />,
    capabilities: ["多情景测算", "保本 ROI 计算", "价格弹性模拟", "库存与预算联动"],
    inputs: ["价格", "流量", "转化率", "成本与退款率"],
    outputs: ["销售预测", "利润预测", "保本条件", "风险边界"],
  },
  experiments: {
    workspace: "增长实验室",
    title: "营销实验中心",
    description: "记录营销假设、版本变化和实验前后效果。",
    objective: "回答“这次增长究竟来自哪项改动，是否值得复制”。",
    icon: <ExperimentOutlined />,
    capabilities: ["实验方案与假设", "实验组与对照组", "观察窗口管理", "结果判定与推广"],
    inputs: ["商品版本", "营销动作", "核心指标", "观察周期"],
    outputs: ["实验结论", "影响评估", "可复制策略", "失败经验"],
  },
  creative: {
    workspace: "增长实验室",
    title: "素材洞察中心",
    description: "关联素材版本、表达标签和经营效果。",
    objective: "回答“什么素材、卖点和表达方式更能带来点击与转化”。",
    icon: <PictureOutlined />,
    capabilities: ["素材版本库", "内容标签体系", "素材效果归因", "高表现模式提炼"],
    inputs: ["主图与视频", "详情页版本", "点击转化", "评价与咨询"],
    outputs: ["素材排行", "卖点洞察", "创作建议", "可复用模板"],
  },
  reviews: {
    workspace: "运营知识库",
    title: "经营复盘中心",
    description: "把日报、周报、活动结果和关键动作沉淀为结构化复盘。",
    objective: "回答“发生了什么、为什么发生、下次应该怎么做”。",
    icon: <FileDoneOutlined />,
    capabilities: ["日周月复盘", "活动复盘", "数据自动引用", "行动项持续跟踪"],
    inputs: ["经营指标", "营销动作", "异常事件", "团队记录"],
    outputs: ["复盘报告", "原因归纳", "行动项", "经验沉淀"],
  },
  decisions: {
    workspace: "运营知识库",
    title: "运营决策档案",
    description: "记录重要决策的背景、依据、预期和最终结果。",
    objective: "回答“当时为什么这样决策，后来是否证明它是正确的”。",
    icon: <BulbOutlined />,
    capabilities: ["决策背景记录", "数据证据关联", "预期结果", "决策效果回看"],
    inputs: ["问题背景", "参考数据", "备选方案", "负责人判断"],
    outputs: ["决策记录", "效果验证", "经验标签", "可检索案例"],
  },
  knowledge: {
    workspace: "运营知识库",
    title: "知识库与 SOP",
    description: "沉淀标准流程、操作模板、业务口径和历史案例。",
    objective: "回答“遇到这个问题，团队应该按照什么标准流程处理”。",
    icon: <BookOutlined />,
    capabilities: ["知识分类与检索", "SOP 与检查清单", "版本与适用范围", "AI 问答引用"],
    inputs: ["复盘结论", "决策案例", "岗位经验", "操作规范"],
    outputs: ["标准流程", "检查清单", "知识文章", "培训材料"],
  },
  automation: {
    workspace: "运营知识库",
    title: "运营自动化中心",
    description: "把监控规则连接到任务、SOP、提醒和结果验证。",
    objective: "回答“发现问题后，系统如何自动推动团队完成处理闭环”。",
    icon: <ThunderboltOutlined />,
    capabilities: ["触发条件配置", "自动创建任务", "推荐 SOP", "恢复验证与复盘"],
    inputs: ["业务事件", "预警规则", "人员权限", "SOP 模板"],
    outputs: ["自动化流程", "执行记录", "超时提醒", "闭环结果"],
  },
};

export function StrategyWorkspacePage({ sectionId }: { sectionId: string }) {
  const section = SECTIONS[sectionId] ?? SECTIONS.opportunities;

  return (
    <div>
      <PageHeader
        icon={section.icon}
        eyebrow={section.workspace}
        title={section.title}
        description={section.description}
        extra={<Tag color="blue">框架已搭建</Tag>}
      />

      <Alert
        type="info"
        showIcon
        title="当前为功能框架版本"
        description="页面入口、信息结构和后续建设范围已经就绪；真实数据接入、计算模型和业务动作将在后续迭代中逐步补充。"
        style={{ marginBottom: 16 }}
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card variant="borderless" title="这个页面将解决什么问题" style={{ height: "100%" }}>
            <Title level={4} style={{ marginTop: 0 }}>{section.objective}</Title>
            <Paragraph type="secondary" style={{ marginBottom: 0, lineHeight: "24px" }}>
              后续功能将围绕数据输入、业务判断、运营动作和结果验证四个环节展开，确保页面不只展示信息，还能推动实际经营决策。
            </Paragraph>
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card variant="borderless" title="建设状态" style={{ height: "100%" }}>
            <Steps
              size="small"
              direction="vertical"
              current={0}
              items={[
                { title: "页面与导航框架", description: "已完成" },
                { title: "数据源与指标口径", description: "待确认" },
                { title: "核心业务流程", description: "待开发" },
                { title: "自动化与智能建议", description: "后续迭代" },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card variant="borderless" title="核心能力规划" style={{ marginTop: 16 }}>
        <Row gutter={[12, 12]}>
          {section.capabilities.map((capability, index) => (
            <Col xs={24} sm={12} xl={6} key={capability}>
              <div
                style={{
                  height: "100%",
                  padding: 16,
                  border: "1px solid var(--ops-border)",
                  borderRadius: "var(--ops-radius)",
                  background: "var(--ops-panel-2)",
                }}
              >
                <Text type="secondary" style={{ fontSize: 12 }}>能力 {index + 1}</Text>
                <div style={{ marginTop: 6, fontWeight: 600 }}>{capability}</div>
              </div>
            </Col>
          ))}
        </Row>
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card variant="borderless" title="计划接入的数据">
            <Space size={[8, 8]} wrap>
              {section.inputs.map((item) => <Tag key={item}>{item}</Tag>)}
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card variant="borderless" title="计划形成的产出">
            <Space size={[8, 8]} wrap>
              {section.outputs.map((item) => <Tag color="purple" key={item}>{item}</Tag>)}
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
