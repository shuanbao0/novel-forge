/**
 * 统一搜索 Drawer - 跨实体类型搜索 + 按类型分组展示
 *
 * 触发: ProjectDetail 顶部 / 全局快捷键
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Input,
  List,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import {
  unifiedSearchApi,
  type SearchHit,
  type UnifiedSearchResponse,
} from '../services/api';

const { Text, Paragraph } = Typography;

interface UnifiedSearchDrawerProps {
  projectId: string;
  open: boolean;
  onClose: () => void;
}

const TYPE_LABELS: Record<string, string> = {
  character: '角色',
  foreshadow: '伏笔',
  memory: '记忆',
  review: '审稿',
  outline: '大纲',
  chapter: '章节',
  commit: '快照',
};

const TYPE_COLOR: Record<string, string> = {
  character: 'blue',
  foreshadow: 'purple',
  memory: 'cyan',
  review: 'orange',
  outline: 'geekblue',
  chapter: 'green',
  commit: 'magenta',
};

const ALL_TYPES: string[] = ['character', 'foreshadow', 'memory', 'review', 'outline', 'chapter', 'commit'];

function groupByType(hits: SearchHit[]): Record<string, SearchHit[]> {
  return hits.reduce<Record<string, SearchHit[]>>((acc, h) => {
    (acc[h.type] ||= []).push(h);
    return acc;
  }, {});
}

export default function UnifiedSearchDrawer({
  projectId,
  open,
  onClose,
}: UnifiedSearchDrawerProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [selectedTypes, setSelectedTypes] = useState<string[]>(ALL_TYPES);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UnifiedSearchResponse | null>(null);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim() || !projectId) {
      setResult(null);
      return;
    }
    setLoading(true);
    try {
      const resp = await unifiedSearchApi.search(projectId, q.trim(), selectedTypes);
      setResult(resp);
    } catch (err) {
      console.error(err);
      message.error('搜索失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, selectedTypes]);

  // 当 Drawer 打开 / 关闭时重置查询
  useEffect(() => {
    if (!open) {
      setQuery('');
      setResult(null);
    }
  }, [open]);

  const handleHitClick = useCallback((hit: SearchHit) => {
    if (!projectId) return;
    switch (hit.type) {
      case 'chapter':
        navigate(`/chapter-reader/${hit.id}`);
        break;
      case 'character':
        navigate(`/project/${projectId}/characters`);
        break;
      case 'foreshadow':
        navigate(`/project/${projectId}/foreshadows`);
        break;
      case 'outline':
        navigate(`/project/${projectId}/outline`);
        break;
      case 'review':
      case 'commit':
        if (hit.extra?.chapter_id) {
          navigate(`/chapter-reader/${hit.extra.chapter_id}`);
        }
        break;
      default:
        break;
    }
    onClose();
  }, [navigate, projectId, onClose]);

  const grouped = result ? groupByType(result.hits) : {};
  const groupKeys = Object.keys(grouped);

  return (
    <Drawer
      title="跨实体搜索"
      placement="right"
      width={620}
      open={open}
      onClose={onClose}
    >
      <Input.Search
        placeholder="输入关键字…"
        size="large"
        enterButton={<SearchOutlined />}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onSearch={runSearch}
        loading={loading}
        autoFocus
        style={{ marginBottom: 12 }}
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Text type="secondary" style={{ marginRight: 12 }}>搜索范围:</Text>
        <Checkbox.Group
          value={selectedTypes}
          onChange={(v) => setSelectedTypes(v as string[])}
        >
          <Space size={[8, 4]} wrap>
            {ALL_TYPES.map(t => (
              <Checkbox key={t} value={t}>{TYPE_LABELS[t] ?? t}</Checkbox>
            ))}
          </Space>
        </Checkbox.Group>
      </Card>

      <Spin spinning={loading}>
        {!result && !loading && (
          <Empty description="输入关键字开始搜索" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}

        {result && result.total === 0 && (
          <Empty description={`未找到与 "${result.query}" 相关的内容`} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}

        {result && result.total > 0 && (
          <div>
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
              共找到 <Text strong>{result.total}</Text> 条结果
            </Paragraph>
            {groupKeys.map(type => (
              <Card
                key={type}
                size="small"
                title={
                  <Space>
                    <Tag color={TYPE_COLOR[type] ?? 'default'}>{TYPE_LABELS[type] ?? type}</Tag>
                    <Badge count={grouped[type].length} showZero color="#999" />
                  </Space>
                }
                style={{ marginBottom: 12 }}
              >
                <List
                  size="small"
                  dataSource={grouped[type]}
                  renderItem={(hit) => (
                    <List.Item
                      onClick={() => handleHitClick(hit)}
                      style={{ cursor: 'pointer' }}
                    >
                      <List.Item.Meta
                        title={<Text strong>{hit.title}</Text>}
                        description={
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {hit.snippet || '(无摘要)'}
                          </Text>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            ))}
          </div>
        )}
      </Spin>
    </Drawer>
  );
}
