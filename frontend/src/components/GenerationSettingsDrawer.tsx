/**
 * 生成偏好 Drawer - 编辑项目的 generation_settings
 *
 * 包含两部分:
 *  1. 主角叙述声音 (年龄 / 时代 / 禁用词汇)
 *     —— 喂给后端 NarratorVoiceDecorator,约束 AI 内心独白的年龄感
 *  2. 项目级支线
 *     —— 喂给规划阶段,让大纲扩展按节奏把支线分布到各章
 *
 * 触发: ProjectDetail 侧边栏"生成偏好"入口
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Typography,
  message,
} from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import { useProjectSync } from '../store/hooks';
import type { GenerationSettings, Project } from '../types';

const { Paragraph, Text } = Typography;

interface Props {
  project: Project;
  open: boolean;
  onClose: () => void;
  onSaved?: (updated: Project) => void;
}

interface FormShape {
  age?: number;
  era?: string;
  forbidden_vocab: string[];
  subplots: string[];
}

function toFormValues(settings?: GenerationSettings | null): FormShape {
  const voice = settings?.protagonist_voice ?? {};
  return {
    age: voice.age,
    era: voice.era,
    forbidden_vocab: Array.isArray(voice.forbidden_vocab) ? voice.forbidden_vocab : [],
    subplots: Array.isArray(settings?.subplots) ? settings?.subplots ?? [] : [],
  };
}

function toGenerationSettings(values: FormShape): GenerationSettings {
  const voiceHasContent =
    values.age != null || (values.era && values.era.trim()) || (values.forbidden_vocab && values.forbidden_vocab.length > 0);
  return {
    protagonist_voice: voiceHasContent
      ? {
          age: values.age,
          era: (values.era || '').trim() || undefined,
          forbidden_vocab: (values.forbidden_vocab || []).map((v) => v.trim()).filter(Boolean),
        }
      : undefined,
    subplots: (values.subplots || []).map((v) => v.trim()).filter(Boolean),
  };
}

export default function GenerationSettingsDrawer({ project, open, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormShape>();
  const [saving, setSaving] = useState(false);
  const { updateProject } = useProjectSync();

  const initialValues = useMemo(() => toFormValues(project.generation_settings), [project.generation_settings]);

  useEffect(() => {
    if (open) {
      form.setFieldsValue(initialValues);
    }
  }, [open, initialValues, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const payload = toGenerationSettings(values);
      const updated = await updateProject(project.id, { generation_settings: payload });
      message.success('生成偏好已保存');
      onSaved?.(updated);
      onClose();
    } catch (err: any) {
      if (err?.errorFields) {
        return; // antd 校验错误,表单内提示已显示
      }
      console.error(err);
      message.error('保存失败: ' + (err?.message || '未知错误'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      title="生成偏好"
      width={520}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
            保存
          </Button>
        </Space>
      }
    >
      <Paragraph type="secondary">
        这里的配置会影响 <Text strong>章节生成</Text> 与 <Text strong>大纲扩展</Text> 的提示词。
        修改后只影响后续新生成的内容,不会重写已有章节。
      </Paragraph>

      <Form form={form} layout="vertical" initialValues={initialValues}>
        <Typography.Title level={5}>主角叙述声音</Typography.Title>
        <Paragraph type="secondary" style={{ marginTop: -8 }}>
          用于约束主角内心独白与对白的年龄/时代感,防止重生类主角动辄"现金流""战略评估"这种过老的口吻。
        </Paragraph>

        <Form.Item label="主角当前年龄" name="age">
          <InputNumber min={5} max={120} placeholder="例如 18" style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item label="故事时代背景" name="era">
          <Input placeholder="例如 2008年 / 民国初年 / 近未来 2042" maxLength={50} />
        </Form.Item>

        <Form.Item
          label="禁用词汇 / 概念"
          name="forbidden_vocab"
          tooltip="主角内心独白与叙述里不允许出现的词,逐个输入回车确认。例如：现金流、用户曲线、战略评估"
        >
          <Select
            mode="tags"
            placeholder="输入后回车添加(例如：现金流)"
            tokenSeparators={[',', '，', ' ']}
            style={{ width: '100%' }}
          />
        </Form.Item>

        <Typography.Title level={5} style={{ marginTop: 24 }}>
          项目级支线
        </Typography.Title>
        <Paragraph type="secondary" style={{ marginTop: -8 }}>
          声明全书贯穿的支线名称(如:苏晚晴线、马三追债线)。
          规划阶段会要求 LLM 把每条支线按节奏分布到不同章节,避免支线长期搁置。
        </Paragraph>

        <Form.Item
          label="支线列表"
          name="subplots"
          tooltip="输入后回车添加。规划阶段会确保每条支线在批章节内至少推进 1 次。"
        >
          <Select
            mode="tags"
            placeholder="输入后回车添加(例如：苏晚晴线)"
            tokenSeparators={[',', '，']}
            style={{ width: '100%' }}
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
