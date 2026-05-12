/**
 * 创作契约编辑器 - 设置项目级硬约束(风格底线/禁忌/反模式/必备桥段/读者承诺)
 *
 * 数据流: 加载时 GET → 用户编辑 → 保存时 PUT → 章节生成自动注入 prompt
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, SaveOutlined } from '@ant-design/icons';
import {
  creativeContractApi,
  type CreativeContractPayload,
} from '../services/api';

const { Title, Paragraph, Text } = Typography;

interface CreativeContractEditorProps {
  projectId: string;
  open: boolean;
  onClose: () => void;
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

  const handleRemove = (idx: number) => {
    onChange(values.filter((_, i) => i !== idx));
  };

  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Title level={5} style={{ marginTop: 0 }}>{label}</Title>
      <Paragraph type="secondary" style={{ fontSize: 12 }}>{hint}</Paragraph>

      <Space size={[8, 8]} wrap style={{ marginBottom: 12 }}>
        {values.map((v, idx) => (
          <Tag
            key={idx}
            closable
            color={color}
            onClose={() => handleRemove(idx)}
            style={{ fontSize: 13, padding: '4px 8px' }}
          >
            {v}
          </Tag>
        ))}
        {values.length === 0 && <Text type="secondary" italic>(暂无)</Text>}
      </Space>

      <Space.Compact style={{ width: '100%' }}>
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={handleAdd}
          placeholder="输入后回车添加"
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加</Button>
      </Space.Compact>
    </Card>
  );
}

const EMPTY_CONTRACT: CreativeContractPayload = {
  style_baseline: '',
  forbidden_zones: [],
  anti_patterns: [],
  required_tropes: [],
  narrative_promises: [],
};

export default function CreativeContractEditor({
  projectId,
  open,
  onClose,
}: CreativeContractEditorProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [contract, setContract] = useState<CreativeContractPayload>(EMPTY_CONTRACT);

  const load = useCallback(async () => {
    if (!projectId || !open) return;
    setLoading(true);
    try {
      const resp = await creativeContractApi.get(projectId);
      setContract(resp.contract);
    } catch (err) {
      console.error(err);
      message.error('加载契约失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, open]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await creativeContractApi.update(projectId, contract);
      message.success('契约已保存,下次章节生成将自动应用');
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
      title="创作契约"
      placement="right"
      width={560}
      open={open}
      onClose={onClose}
      extra={
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={handleSave}
        >
          保存
        </Button>
      }
    >
      <Paragraph type="secondary">
        创作契约是项目级硬约束,会自动注入到每次章节生成的系统提示词中。
        设置后所有章节都会受这些规则约束,确保整本书的风格与设定一致。
      </Paragraph>

      <Form layout="vertical" disabled={loading}>
        <Form.Item label="风格底线">
          <Input.TextArea
            rows={3}
            value={contract.style_baseline}
            onChange={(e) => setContract({ ...contract, style_baseline: e.target.value })}
            placeholder="例如:第三人称限制视角,叙述节奏紧凑,对话占比 30% 以上"
          />
        </Form.Item>

        <ListEditor
          label="禁忌区"
          hint="严禁出现的情节/设定(如:不能写穿越、主角不能死)"
          values={contract.forbidden_zones}
          onChange={(v) => setContract({ ...contract, forbidden_zones: v })}
          color="red"
        />

        <ListEditor
          label="反模式"
          hint="避免的写作套路(如:不要金手指、不要降智反派)"
          values={contract.anti_patterns}
          onChange={(v) => setContract({ ...contract, anti_patterns: v })}
          color="orange"
        />

        <ListEditor
          label="必备桥段"
          hint="本书类型要求必须包含的元素(如:武侠须有师徒情、修仙须有突破场景)"
          values={contract.required_tropes}
          onChange={(v) => setContract({ ...contract, required_tropes: v })}
          color="green"
        />

        <ListEditor
          label="读者承诺"
          hint="向读者隐含承诺的长线剧情目标(如:主角必须为父报仇),会被审稿系统重点检查"
          values={contract.narrative_promises}
          onChange={(v) => setContract({ ...contract, narrative_promises: v })}
          color="blue"
        />
      </Form>
    </Drawer>
  );
}
