/**
 * 通用 Brief 编辑器 - Volume / Chapter 共用
 *
 * 两种模式:
 * - 'volume': 编辑 outline.creative_brief = {volume_goal, anti_patterns, required_tropes, pacing}
 * - 'chapter': 编辑 chapter.creative_brief = {directive, forbidden_zones, must_check_nodes}
 */
import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, SaveOutlined } from '@ant-design/icons';

const { Paragraph, Text } = Typography;

export type BriefMode = 'volume' | 'chapter';

interface BriefEditorProps {
  mode: BriefMode;
  open: boolean;
  initialValue: Record<string, unknown> | null | undefined;
  onClose: () => void;
  onSave: (brief: Record<string, unknown>) => Promise<void> | void;
  title?: string;
}

interface ListEditorProps {
  label: string;
  hint: string;
  values: string[];
  onChange: (next: string[]) => void;
  color?: string;
}

function ListEditor({ label, hint, values, onChange, color = 'default' }: ListEditorProps) {
  const [input, setInput] = useState('');

  const handleAdd = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    if (values.includes(trimmed)) {
      message.warning('该条目已存在');
      return;
    }
    onChange([...values, trimmed]);
    setInput('');
  };

  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Text strong>{label}</Text>
      <Paragraph type="secondary" style={{ fontSize: 12, margin: '4px 0 8px' }}>{hint}</Paragraph>
      <Space size={[8, 8]} wrap style={{ marginBottom: 12 }}>
        {values.map((v, i) => (
          <Tag key={i} closable color={color} onClose={() => onChange(values.filter((_, idx) => idx !== i))}>
            {v}
          </Tag>
        ))}
        {values.length === 0 && <Text type="secondary" italic>(暂无)</Text>}
      </Space>
      <Space.Compact style={{ width: '100%' }}>
        <Input value={input} onChange={(e) => setInput(e.target.value)} onPressEnter={handleAdd} placeholder="输入后回车" />
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加</Button>
      </Space.Compact>
    </Card>
  );
}

const VOLUME_DEFAULTS = {
  volume_goal: '',
  anti_patterns: [] as string[],
  required_tropes: [] as string[],
  pacing: '',
};

const CHAPTER_DEFAULTS = {
  directive: '',
  forbidden_zones: [] as string[],
  must_check_nodes: [] as string[],
};

export default function BriefEditor({
  mode,
  open,
  initialValue,
  onClose,
  onSave,
  title,
}: BriefEditorProps) {
  const defaultBrief = mode === 'volume' ? VOLUME_DEFAULTS : CHAPTER_DEFAULTS;
  const [brief, setBrief] = useState<Record<string, unknown>>(defaultBrief);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (initialValue && typeof initialValue === 'object') {
      setBrief({ ...defaultBrief, ...initialValue });
    } else {
      setBrief({ ...defaultBrief });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialValue, mode]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(brief);
      message.success(`${mode === 'volume' ? '卷级' : '章级'}契约已保存`);
      onClose();
    } catch (err) {
      console.error(err);
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      title={title ?? (mode === 'volume' ? '卷级契约' : '章级契约')}
      open={open}
      onClose={onClose}
      width={520}
      extra={
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
          保存
        </Button>
      }
    >
      <Paragraph type="secondary">
        {mode === 'volume'
          ? '本卷契约会作用于挂在本大纲下的所有章节,优先级高于项目级契约。'
          : '本章契约只作用于本章,优先级最高(会覆盖项目级和卷级)。'}
      </Paragraph>

      <Form layout="vertical">
        {mode === 'volume' && (
          <>
            <Form.Item label="本卷叙事目标">
              <Input.TextArea
                rows={3}
                value={brief.volume_goal as string || ''}
                onChange={(e) => setBrief({ ...brief, volume_goal: e.target.value })}
                placeholder="例如:本卷讲述主角入门到第一次比武的过程,重在建立人物关系"
              />
            </Form.Item>

            <Form.Item label="期望节奏">
              <Select
                value={(brief.pacing as string) || ''}
                onChange={(v) => setBrief({ ...brief, pacing: v })}
                allowClear
                placeholder="选择本卷节奏倾向"
                options={[
                  { value: 'fast', label: '快节奏(情节驱动)' },
                  { value: 'medium', label: '中等(情感与情节并重)' },
                  { value: 'slow', label: '慢节奏(细腻铺陈)' },
                ]}
              />
            </Form.Item>

            <ListEditor
              label="本卷反模式"
              hint="本卷专属的避免套路(项目级反模式之外的)"
              values={(brief.anti_patterns as string[]) || []}
              onChange={(v) => setBrief({ ...brief, anti_patterns: v })}
              color="orange"
            />
            <ListEditor
              label="本卷必备桥段"
              hint="本卷一定要出现的元素(例如:必须有第一次师门冲突)"
              values={(brief.required_tropes as string[]) || []}
              onChange={(v) => setBrief({ ...brief, required_tropes: v })}
              color="green"
            />
          </>
        )}

        {mode === 'chapter' && (
          <>
            <Form.Item label="本章核心指令">
              <Input.TextArea
                rows={3}
                value={(brief.directive as string) || ''}
                onChange={(e) => setBrief({ ...brief, directive: e.target.value })}
                placeholder="例如:本章必须见到师父并开始第一课"
              />
            </Form.Item>

            <ListEditor
              label="本章必须覆盖"
              hint="必须在本章中出现/完成的关键节点"
              values={(brief.must_check_nodes as string[]) || []}
              onChange={(v) => setBrief({ ...brief, must_check_nodes: v })}
              color="green"
            />

            <ListEditor
              label="本章额外禁忌"
              hint="本章特定的禁区(在项目/卷级禁忌之外)"
              values={(brief.forbidden_zones as string[]) || []}
              onChange={(v) => setBrief({ ...brief, forbidden_zones: v })}
              color="red"
            />
          </>
        )}
      </Form>
    </Drawer>
  );
}
