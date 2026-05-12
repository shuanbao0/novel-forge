/**
 * 结构化润色指南选择器 - 6 个指南的卡片式多选
 *
 * 用法:嵌入到 Polish Modal 或者作为独立 Drawer。
 * 选定的 guide_ids 通过 onChange 回调返回给上层,由上层调用 polishApi.polish。
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Checkbox,
  Collapse,
  Drawer,
  Empty,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { polishGuidesApi, type PolishGuide } from '../services/api';

const { Text, Paragraph } = Typography;

interface PolishGuidesPickerProps {
  open: boolean;
  initialSelection?: string[];
  onClose: () => void;
  onConfirm: (selectedIds: string[]) => void;
}

export default function PolishGuidesPicker({
  open,
  initialSelection = [],
  onClose,
  onConfirm,
}: PolishGuidesPickerProps) {
  const [loading, setLoading] = useState(false);
  const [guides, setGuides] = useState<PolishGuide[]>([]);
  const [selected, setSelected] = useState<string[]>(initialSelection);

  const load = useCallback(async () => {
    if (!open) return;
    setLoading(true);
    try {
      const list = await polishGuidesApi.list();
      setGuides(list);
    } catch (err) {
      console.error(err);
      message.error('加载润色指南失败');
    } finally {
      setLoading(false);
    }
  }, [open]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (open) {
      setSelected(initialSelection);
    }
  }, [open, initialSelection]);

  const toggle = (id: string) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const selectAll = () => setSelected(guides.map(g => g.id));
  const clearAll = () => setSelected([]);

  return (
    <Drawer
      title={`结构化润色指南 (已选 ${selected.length}/${guides.length})`}
      placement="right"
      width={620}
      open={open}
      onClose={onClose}
      extra={
        <Space>
          <Button size="small" onClick={clearAll}>清空</Button>
          <Button size="small" onClick={selectAll}>全选</Button>
          <Button type="primary" onClick={() => { onConfirm(selected); onClose(); }}>
            应用所选({selected.length})
          </Button>
        </Space>
      }
    >
      <Paragraph type="secondary">
        润色时会按所选指南逐一改写,每个指南聚焦一个维度(场景/情感/对话/动作/节奏/感官)。
        不选默认走通用 AI 去味。
      </Paragraph>

      <Spin spinning={loading}>
        {guides.length === 0 && !loading && (
          <Empty description="未能加载指南" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}

        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {guides.map(g => (
            <Card
              key={g.id}
              size="small"
              hoverable
              onClick={() => toggle(g.id)}
              style={{
                borderColor: selected.includes(g.id) ? '#1677ff' : undefined,
                cursor: 'pointer',
              }}
            >
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Space>
                    <Checkbox checked={selected.includes(g.id)} />
                    <Text strong style={{ fontSize: 15 }}>{g.name}</Text>
                  </Space>
                  <Tag>{g.id}</Tag>
                </Space>
                <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                  焦点:{g.focus}
                </Paragraph>
                <Collapse
                  ghost
                  size="small"
                  items={[
                    {
                      key: 'rules',
                      label: <Text type="secondary" style={{ fontSize: 12 }}>展开规则与示例</Text>,
                      children: (
                        <div onClick={(e) => e.stopPropagation()}>
                          <Text strong style={{ fontSize: 12 }}>规则:</Text>
                          <ul style={{ margin: '4px 0 8px', paddingLeft: 20, fontSize: 12 }}>
                            {g.rules.map((r, i) => <li key={i}>{r}</li>)}
                          </ul>
                          {g.examples_bad.length > 0 && (
                            <>
                              <Text strong style={{ fontSize: 12 }} type="danger">反例:</Text>
                              <ul style={{ margin: '4px 0 8px', paddingLeft: 20, fontSize: 12, color: '#cf1322' }}>
                                {g.examples_bad.map((ex, i) => <li key={i}>{ex}</li>)}
                              </ul>
                            </>
                          )}
                          {g.examples_good.length > 0 && (
                            <>
                              <Text strong style={{ fontSize: 12 }} type="success">正例:</Text>
                              <ul style={{ margin: '4px 0', paddingLeft: 20, fontSize: 12, color: '#389e0d' }}>
                                {g.examples_good.map((ex, i) => <li key={i}>{ex}</li>)}
                              </ul>
                            </>
                          )}
                        </div>
                      ),
                    },
                  ]}
                />
              </Space>
            </Card>
          ))}
        </Space>
      </Spin>
    </Drawer>
  );
}
