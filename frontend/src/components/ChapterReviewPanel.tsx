/**
 * 章节审稿面板 - 多维度问题列表 + 严重级筛选 + 单条操作
 *
 * 设计:
 * - 顶部展示按严重级聚合的徽章 + 重跑按钮
 * - 列表按维度分组,每条问题可"忽略"或"标记已修复"
 * - 空状态展示"暂无审稿意见 / 点击重跑"
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Collapse,
  Descriptions,
  Empty,
  List,
  Popconfirm,
  Progress,
  Space,
  Spin,
  Statistic,
  Tabs,
  Tag,
  Typography,
  message,
  theme,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  chapterCommitApi,
  chapterReviewApi,
  type ChapterCommit,
  type ChapterReviewIssue,
  type ChapterReviewListResponse,
} from '../services/api';

const { Text, Paragraph } = Typography;

interface ChapterReviewPanelProps {
  chapterId: string;
}

const DIMENSION_LABELS: Record<string, string> = {
  consistency: '一致性',
  timeline: '时间线',
  ooc: '角色 OOC',
  continuity: '章节衔接',
  logic: '因果逻辑',
  ai_flavor: 'AI 味',
};

const SEVERITY_COLOR: Record<string, string> = {
  blocking: 'red',
  warn: 'orange',
  info: 'blue',
};

const SEVERITY_LABEL: Record<string, string> = {
  blocking: '阻塞',
  warn: '建议',
  info: '提示',
};

function groupByDimension(issues: ChapterReviewIssue[]): Record<string, ChapterReviewIssue[]> {
  return issues.reduce<Record<string, ChapterReviewIssue[]>>((acc, issue) => {
    (acc[issue.dimension] ||= []).push(issue);
    return acc;
  }, {});
}

export default function ChapterReviewPanel({ chapterId }: ChapterReviewPanelProps) {
  const { token } = theme.useToken();
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [data, setData] = useState<ChapterReviewListResponse | null>(null);
  const [commit, setCommit] = useState<ChapterCommit | null>(null);

  const load = useCallback(async () => {
    if (!chapterId) return;
    setLoading(true);
    try {
      const [resp, latestCommit] = await Promise.all([
        chapterReviewApi.list(chapterId, { status: 'open' }),
        chapterCommitApi.latest(chapterId).catch(() => null),
      ]);
      setData(resp);
      setCommit(latestCommit);
    } catch (err) {
      console.error('加载审稿意见失败', err);
      message.error('加载审稿意见失败');
    } finally {
      setLoading(false);
    }
  }, [chapterId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRerun = useCallback(async () => {
    setRerunning(true);
    try {
      const resp = await chapterReviewApi.rerun(chapterId);
      if (resp.scheduled) {
        message.success('审稿任务已排队,稍后刷新可查看新结果');
      }
    } catch (err) {
      console.error(err);
      message.error('重跑审稿失败');
    } finally {
      setRerunning(false);
    }
  }, [chapterId]);

  const handleIgnore = useCallback(
    async (issue: ChapterReviewIssue) => {
      try {
        await chapterReviewApi.ignore(chapterId, issue.id);
        message.success('已忽略');
        await load();
      } catch (err) {
        console.error(err);
        message.error('操作失败');
      }
    },
    [chapterId, load],
  );

  const handleResolve = useCallback(
    async (issue: ChapterReviewIssue) => {
      try {
        await chapterReviewApi.resolve(chapterId, issue.id);
        message.success('已标记为已修复');
        await load();
      } catch (err) {
        console.error(err);
        message.error('操作失败');
      }
    },
    [chapterId, load],
  );

  const grouped = useMemo(() => (data ? groupByDimension(data.items) : {}), [data]);
  const dimensions = Object.keys(grouped);

  const blockingCount = data?.summary.by_severity?.blocking ?? 0;
  const warnCount = data?.summary.by_severity?.warn ?? 0;
  const infoCount = data?.summary.by_severity?.info ?? 0;

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
        <Space size="small">
          <Text strong style={{ fontSize: 15 }}>章节审稿</Text>
          {blockingCount > 0 && <Badge count={blockingCount} color={SEVERITY_COLOR.blocking} />}
          {warnCount > 0 && <Badge count={warnCount} color={SEVERITY_COLOR.warn} />}
          {infoCount > 0 && <Badge count={infoCount} color={SEVERITY_COLOR.info} />}
        </Space>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={rerunning}
          onClick={handleRerun}
        >
          重跑审稿
        </Button>
      </Space>

      {blockingCount > 0 && (
        <Alert
          type="error"
          showIcon
          message={`本章存在 ${blockingCount} 个阻塞级问题,强烈建议修改后再发布`}
          style={{ marginBottom: 12 }}
        />
      )}

      {commit && commit.fulfillment?.total_nodes ? (
        <Alert
          type={
            (commit.fulfillment.covered_count ?? 0) === commit.fulfillment.total_nodes
              ? 'success'
              : 'warning'
          }
          showIcon
          message={`节点覆盖: ${commit.fulfillment.covered_count ?? 0} / ${commit.fulfillment.total_nodes}`}
          description={
            (commit.fulfillment.missed_nodes?.length ?? 0) > 0
              ? `未覆盖: ${commit.fulfillment.missed_nodes!.join('、')}`
              : '全部三层大纲节点已在本章覆盖'
          }
          style={{ marginBottom: 12 }}
        />
      ) : null}

      <Spin spinning={loading}>
        <Tabs
          defaultActiveKey="reviews"
          items={[
            {
              key: 'reviews',
              label: <span>审稿意见{data?.summary.total ? `(${data.summary.total})` : ''}</span>,
              children: (
                <>
                  {dimensions.length === 0 && !loading && (
                    <Empty
                      description="暂无未处理的审稿意见"
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      style={{ padding: '24px 0' }}
                    />
                  )}

                  {dimensions.length > 0 && (
                    <Collapse
                      defaultActiveKey={dimensions}
                      ghost
                      items={dimensions.map(dim => {
                        const issues = grouped[dim];
                        return {
                          key: dim,
                          label: (
                            <Space>
                              <Text strong>{DIMENSION_LABELS[dim] ?? dim}</Text>
                              <Tag>{issues.length}</Tag>
                            </Space>
                          ),
                          children: (
                            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                              {issues.map(issue => (
                                <div
                                  key={issue.id}
                                  style={{
                                    padding: 12,
                                    border: `1px solid ${token.colorBorderSecondary}`,
                                    borderRadius: 6,
                                    background: token.colorBgContainer,
                                  }}
                                >
                                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                                    <Space size="small">
                                      <Tag color={SEVERITY_COLOR[issue.severity] ?? 'default'}>
                                        {SEVERITY_LABEL[issue.severity] ?? issue.severity}
                                      </Tag>
                                      {issue.category && <Tag>{issue.category}</Tag>}
                                      <Text strong>{issue.title}</Text>
                                    </Space>
                                    <Space size="small">
                                      <Popconfirm
                                        title="忽略此条意见?"
                                        onConfirm={() => handleIgnore(issue)}
                                        okText="确认"
                                        cancelText="取消"
                                      >
                                        <Button size="small" icon={<CloseCircleOutlined />}>忽略</Button>
                                      </Popconfirm>
                                      <Button
                                        size="small"
                                        type="primary"
                                        ghost
                                        icon={<CheckCircleOutlined />}
                                        onClick={() => handleResolve(issue)}
                                      >
                                        已修复
                                      </Button>
                                    </Space>
                                  </Space>
                                  {issue.evidence && (
                                    <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 4, fontSize: 13 }}>
                                      <WarningOutlined style={{ marginRight: 4 }} />
                                      原文:{issue.evidence}
                                    </Paragraph>
                                  )}
                                  {issue.fix_hint && (
                                    <Paragraph style={{ marginBottom: 0, fontSize: 13 }}>
                                      <Text type="success">建议:</Text> {issue.fix_hint}
                                    </Paragraph>
                                  )}
                                </div>
                              ))}
                            </Space>
                          ),
                        };
                      })}
                    />
                  )}
                </>
              ),
            },
            {
              key: 'score',
              label: '抓力评分',
              children: <ReadingPullView commit={commit} />,
            },
            {
              key: 'events',
              label: <span>事件{(commit?.extraction_meta as any)?.events_count ? `(${(commit?.extraction_meta as any).events_count})` : ''}</span>,
              children: <EventsView commit={commit} />,
            },
            {
              key: 'entities',
              label: '实体候选',
              children: <DisambiguationView commit={commit} />,
            },
          ]}
        />
      </Spin>
    </div>
  );
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  character_state_changed: '角色状态变化',
  power_breakthrough: '实力突破',
  relationship_changed: '关系变化',
  world_rule_revealed: '世界规则揭示',
  world_rule_broken: '世界规则违反',
  open_loop_created: '钩子创建',
  open_loop_closed: '钩子闭合',
  promise_created: '承诺创建',
  promise_paid_off: '承诺兑现',
  artifact_obtained: '获得关键物',
};

function ReadingPullView({ commit }: { commit: ChapterCommit | null }) {
  const pull = (commit?.extraction_meta as any)?.reading_pull;
  if (!pull) return <Empty description="尚未生成评分" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const gradeColor: Record<string, string> = { S: 'gold', A: 'green', B: 'blue', C: 'orange', D: 'red' };

  return (
    <div>
      <Space size="large" style={{ marginBottom: 16 }}>
        <Statistic title="抓力分数" value={pull.score} suffix="/ 100" />
        <Statistic
          title="评级"
          valueRender={() => (
            <Tag color={gradeColor[pull.grade] ?? 'default'} style={{ fontSize: 24, padding: '8px 16px' }}>
              {pull.grade}
            </Tag>
          )}
          value={pull.grade}
        />
      </Space>

      <Progress percent={pull.score} status={pull.score >= 60 ? 'success' : 'exception'} style={{ marginBottom: 16 }} />

      <Descriptions title="分项明细" column={1} size="small" bordered>
        {Object.entries(pull.breakdown || {}).map(([k, v]) => (
          <Descriptions.Item key={k} label={k}>
            <Tag color={(v as number) > 0 ? 'green' : (v as number) < 0 ? 'red' : 'default'}>
              {(v as number) > 0 ? `+${v}` : v}
            </Tag>
          </Descriptions.Item>
        ))}
      </Descriptions>

      {pull.issues?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text strong>问题提示:</Text>
          <ul style={{ marginTop: 8 }}>
            {pull.issues.map((i: string, idx: number) => <li key={idx}>{i}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function EventsView({ commit }: { commit: ChapterCommit | null }) {
  const events: any[] = (commit?.extraction_meta as any)?.events || [];
  if (events.length === 0) {
    return <Empty description="未抽取到结构化事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return (
    <List
      size="small"
      dataSource={events}
      renderItem={(ev) => (
        <List.Item>
          <List.Item.Meta
            title={
              <Space>
                <Tag color="purple">{EVENT_TYPE_LABELS[ev.type] ?? ev.type}</Tag>
                <Text>{ev.summary}</Text>
              </Space>
            }
            description={
              <Text type="secondary" style={{ fontSize: 12 }}>
                {ev.actors?.length > 0 && <span>角色: {ev.actors.join('、')} </span>}
                {ev.evidence && <span>· {ev.evidence}</span>}
              </Text>
            }
          />
        </List.Item>
      )}
    />
  );
}

function DisambiguationView({ commit }: { commit: ChapterCommit | null }) {
  const items: any[] = (commit?.extraction_meta as any)?.disambiguation || [];
  if (items.length === 0) {
    return <Empty description="无新实体候选" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const colorMap: Record<string, string> = { new_entity: 'green', alias: 'gold', noise: 'default' };
  const labelMap: Record<string, string> = { new_entity: '建议入库', alias: '可能别名', noise: '低置信度' };
  return (
    <List
      size="small"
      dataSource={items}
      renderItem={(c) => (
        <List.Item>
          <List.Item.Meta
            title={
              <Space>
                <Text strong>{c.surface}</Text>
                <Tag color={colorMap[c.suggestion] ?? 'default'}>{labelMap[c.suggestion] ?? c.suggestion}</Tag>
                <Tag>置信度 {c.confidence}</Tag>
                <Tag>出现 {c.occurrences} 次</Tag>
              </Space>
            }
            description={c.similar_to ? <Text type="secondary">疑似已有角色: {c.similar_to}</Text> : null}
          />
        </List.Item>
      )}
    />
  );
}
