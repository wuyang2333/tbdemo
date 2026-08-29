import { ExperimentOutlined, PictureOutlined, SearchOutlined } from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Tag, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "../components/ui/page-header";
import { DecisionBand, WorkspacePage } from "../components/ui/workspace-template";

const { Paragraph, Text } = Typography;

const EXTENSIONS = [
  {
    key: "assets",
    title: "商品与素材归因",
    icon: <PictureOutlined />,
    description: "关联推广计划、商品和素材版本，识别高效商品、素材疲劳与替换机会。",
    inputs: ["商品", "主图与视频", "计划关联", "点击与成交"],
    path: "/promotions/assets",
  },
  {
    key: "targets",
    title: "关键词与人群分析",
    icon: <SearchOutlined />,
    description: "判断哪些搜索词和人群带来有效成交，哪些正在浪费投放机会。",
    inputs: ["关键词", "搜索词", "人群包", "成交与退款"],
    path: "/promotions/targets",
  },
  {
    key: "experiments",
    title: "营销实验",
    icon: <ExperimentOutlined />,
    description: "记录投放假设、版本变化和观察结果，区分相关性与可复制增量。",
    inputs: ["实验假设", "版本对比", "观察窗口", "结果判定"],
    path: "/promotions/experiments",
  },
];

export function PromotionsExtensionsPage() {
  const navigate = useNavigate();

  return (
    <WorkspacePage kind="management">
      <PageHeader
        icon={<ExperimentOutlined />}
        eyebrow="推广管理"
        title="扩展分析"
        description="核心闭环稳定后，再接入商品素材、关键词人群和营销实验，所有结果仍回到决策、执行与验证。"
      />
      <DecisionBand
        eyebrow="扩展建设顺序"
        title="先补商品与素材归因，再扩关键词、人群和营销实验"
        description="扩展模块不另起流程，所有发现都应回到决策、执行和验证闭环。"
        action={<Button type="primary" onClick={() => navigate(EXTENSIONS[0].path)}>查看第一阶段</Button>}
        ariaLabel="推广扩展建设结论"
      />

      <Row gutter={[16, 16]}>
        {EXTENSIONS.map((item) => (
          <Col xs={24} lg={8} key={item.key}>
            <Card
              variant="borderless"
              title={item.title}
              extra={<Tag color="blue">框架</Tag>}
              style={{ height: "100%" }}
            >
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Paragraph type="secondary" style={{ margin: 0 }}>{item.description}</Paragraph>
                <div>
                  <Text type="secondary">计划接入</Text>
                  <div style={{ marginTop: 8 }}>
                    <Space size={[6, 6]} wrap>{item.inputs.map((input) => <Tag key={input}>{input}</Tag>)}</Space>
                  </div>
                </div>
                <Button block onClick={() => navigate(item.path)}>查看建设框架</Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </WorkspacePage>
  );
}
