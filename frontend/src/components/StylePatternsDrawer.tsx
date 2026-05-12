/**
 * 写作模式 Drawer - 显示已抽取的作者风格特征 + 重新学习 / 清空
 *
 * 触发: ProjectDetail 侧边栏 "写作模式" 入口
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  ReadOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import {
  stylePatternApi,
  type StylePattern,
} from '../services/api';

const { Paragraph, Text } = Typography;

interface StylePatternsDrawerProps {
  projectId: string;
  open: boolean;
  onClose: () => void;
}

function PatternView({ pattern }: { pattern: StylePattern }) {
  const rhythmLabel = pattern.rhythm === 'fast' ? '快节奏' : pattern.rhythm === 'slow' ? '慢节奏' : '中等节奏';

  return (
    <div>
      <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="平均句长">{pattern.avg_sentence_length} 字</Descriptions.Item>
        <Descriptions.Item label="平均段长">{pattern.avg_paragraph_length} 字</Descriptions.Item>
        <Descriptions.Item label="对白占比">{(pattern.dialogue_ratio * 100).toFixed(1)}%</Descriptions.Item>
        <Descriptions.Item label="标点密度">{pattern.punctuation_density.toFixed(1)} /千字</Descriptions.Item>
        <Descriptions.Item label="短句比">{(pattern.short_sentence_ratio * 100).toFixed(1)}%</Descriptions.Item>
        <Descriptions.Item label="长句比">{(pattern.long_sentence_ratio * 100).toFixed(1)}%</Descriptions.Item>
        <Descriptions.Item label="节奏" span={2}><Tag color="blue">{rhythmLabel}</Tag></Descriptions.Item>
      </Descriptions>

      <Card size="small" title="作者常用副词" style={{ marginBottom: 12 }}>
        {pattern.favorite_adverbs.length === 0 ? (
          <Text type="secondary" italic>未识别(样本不足或未达频次阈值)</Text>
        ) : (
          <Space size={[8, 8]} wrap>
            {pattern.favorite_adverbs.map((w, i) => <Tag key={i} color="purple">{w}</Tag>)}
          </Space>
        )}
      </Card>

      <Card size="small" title="高频短语" style={{ marginBottom: 12 }}>
        {pattern.favorite_phrases.length === 0 ? (
          <Text type="secondary" italic>未识别</Text>
        ) : (
          <Space size={[8, 8]} wrap>
            {pattern.favorite_phrases.map((p, i) => <Tag key={i} color="cyan">{p}</Tag>)}
          </Space>
        )}
      </Card>

      <Card size="small" title="段首习惯起势" style={{ marginBottom: 12 }}>
        {pattern.common_openers.length === 0 ? (
          <Text type="secondary" italic>未识别</Text>
        ) : (
          <Space size={[8, 8]} wrap>
            {pattern.common_openers.map((o, i) => <Tag key={i}>{o}...</Tag>)}
          </Space>
        )}
      </Card>

      <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 16 }}>
        基于 <Text strong>{pattern.sample_chapter_count}</Text> 章 / <Text strong>{pattern.sample_word_count}</Text> 字提取。
        {pattern.extracted_at && <> 抽取时间: {new Date(pattern.extracted_at).toLocaleString()}</>}
      </Paragraph>
    </div>
  );
}

export default function StylePatternsDrawer({
  projectId,
  open,
  onClose,
}: StylePatternsDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [learning, setLearning] = useState(false);
  const [hasData, setHasData] = useState(false);
  const [pattern, setPattern] = useState<StylePattern | null>(null);

  const load = useCallback(async () => {
    if (!projectId || !open) return;
    setLoading(true);
    try {
      const resp = await stylePatternApi.get(projectId);
      setHasData(!!resp.has_data);
      setPattern(resp.pattern);
    } catch (err) {
      console.error(err);
      message.error('加载写作模式失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, open]);

  useEffect(() => { void load(); }, [load]);

  const handleLearn = async () => {
    setLearning(true);
    try {
      const resp = await stylePatternApi.learn(projectId);
      setHasData(true);
      setPattern(resp.pattern);
      message.success(`已从 ${resp.pattern.sample_chapter_count} 章中学习写作模式`);
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '抽取失败';
      message.error(msg);
    } finally {
      setLearning(false);
    }
  };

  const handleClear = async () => {
    try {
      await stylePatternApi.clear(projectId);
      setHasData(false);
      setPattern(null);
      message.success('已清空写作模式');
    } catch (err) {
      console.error(err);
      message.error('操作失败');
    }
  };

  return (
    <Drawer
      title="写作模式"
      placement="right"
      width={560}
      open={open}
      onClose={onClose}
      extra={
        <Space>
          <Button
            type="primary"
            icon={<SyncOutlined />}
            loading={learning}
            onClick={handleLearn}
          >
            {hasData ? '重新学习' : '开始学习'}
          </Button>
          {hasData && (
            <Popconfirm title="清空已抽取的写作模式?" onConfirm={handleClear} okText="清空" cancelText="取消">
              <Button icon={<DeleteOutlined />} danger>清空</Button>
            </Popconfirm>
          )}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        icon={<ReadOutlined />}
        message="写作模式自一致"
        description={
          <span>
            从项目已完成的章节中抽取作者的写作特征(句长/节奏/常用词/段首习惯),
            自动注入后续章节生成 prompt,保证整本书风格一致。
            建议在完成 <Text strong>5+ 章节</Text>后运行一次。
          </span>
        }
        style={{ marginBottom: 16 }}
      />

      <Spin spinning={loading}>
        {hasData && pattern ? (
          <PatternView pattern={pattern} />
        ) : (
          !loading && (
            <Empty
              description="尚未抽取写作模式 — 点击右上角 '开始学习' 按钮"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              style={{ padding: '40px 0' }}
            />
          )
        )}
      </Spin>
    </Drawer>
  );
}
