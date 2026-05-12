/**
 * AI 润色模态框 - 串联 PolishGuidesPicker + 调用 polishApi.polish + 显示差异 + 应用
 *
 * 用法:
 *   <PolishModal chapterId={chapterId} originalText={...} open={...} onClose={...} onApply={...} />
 *
 * 流程:
 *   1. 显示原文 + 已选指南数量 + "选择指南"按钮(可选)
 *   2. 点击"开始润色"调用 /polish + 选定 guide_ids
 *   3. 返回润色文本,左右对比展示
 *   4. 用户点"应用",回调 onApply(polished_text)
 */
import { useCallback, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  HighlightOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { polishApi } from '../services/api';
import PolishGuidesPicker from './PolishGuidesPicker';

const { Text } = Typography;

interface PolishModalProps {
  open: boolean;
  originalText: string;
  onClose: () => void;
  onApply: (polishedText: string) => void;
}

export default function PolishModal({
  open,
  originalText,
  onClose,
  onApply,
}: PolishModalProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedGuides, setSelectedGuides] = useState<string[]>([]);
  const [polishing, setPolishing] = useState(false);
  const [polished, setPolished] = useState<string | null>(null);

  const handlePolish = useCallback(async () => {
    if (!originalText?.trim()) {
      message.warning('正文为空');
      return;
    }
    setPolishing(true);
    setPolished(null);
    try {
      const resp = await polishApi.polish({
        original_text: originalText,
        guide_ids: selectedGuides.length > 0 ? selectedGuides : undefined,
      });
      setPolished(resp.polished_text);
      message.success(`润色完成(${resp.word_count_before} → ${resp.word_count_after} 字)`);
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '润色失败';
      message.error(msg);
    } finally {
      setPolishing(false);
    }
  }, [originalText, selectedGuides]);

  const handleApply = () => {
    if (polished) {
      onApply(polished);
      onClose();
    }
  };

  const handleReset = () => {
    setPolished(null);
  };

  return (
    <>
      <Modal
        title={
          <Space>
            <HighlightOutlined />
            <span>AI 润色</span>
          </Space>
        }
        open={open}
        onCancel={onClose}
        width="80%"
        style={{ maxWidth: 1200 }}
        footer={
          <Space>
            <Button onClick={onClose}>取消</Button>
            {polished && (
              <Button onClick={handleReset} icon={<SyncOutlined />}>重新润色</Button>
            )}
            {!polished && (
              <Button
                type="primary"
                onClick={handlePolish}
                loading={polishing}
                icon={<HighlightOutlined />}
              >
                {selectedGuides.length > 0 ? `开始润色(${selectedGuides.length}个指南)` : '开始润色'}
              </Button>
            )}
            {polished && (
              <Button type="primary" onClick={handleApply} icon={<CheckOutlined />}>
                应用润色结果
              </Button>
            )}
          </Space>
        }
      >
        <Card size="small" style={{ marginBottom: 12 }}>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space>
              <Text type="secondary">润色指南:</Text>
              {selectedGuides.length === 0 ? (
                <Text type="secondary" italic>未选(走通用 AI 去味)</Text>
              ) : (
                selectedGuides.map(g => <Tag key={g} color="blue">{g}</Tag>)
              )}
            </Space>
            <Button size="small" onClick={() => setPickerOpen(true)}>
              {selectedGuides.length > 0 ? '修改选择' : '选择指南'}
            </Button>
          </Space>
        </Card>

        {polishing && (
          <div style={{ textAlign: 'center', padding: '60px 0' }}>
            <Spin tip="AI 润色中,请稍候…" size="large" />
          </div>
        )}

        {!polishing && !polished && (
          <Card size="small" title="原文预览">
            <div style={{ maxHeight: 400, overflowY: 'auto', whiteSpace: 'pre-wrap', fontSize: 14 }}>
              {originalText || <Text type="secondary" italic>(空)</Text>}
            </div>
          </Card>
        )}

        {!polishing && polished && (
          <div style={{ display: 'flex', gap: 12 }}>
            <Card size="small" title="原文" style={{ flex: 1 }}>
              <div style={{ maxHeight: 480, overflowY: 'auto', whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.8 }}>
                {originalText}
              </div>
            </Card>
            <Card
              size="small"
              title={<Space><Text strong>润色后</Text><Tag color="green">应用前请预览</Tag></Space>}
              style={{ flex: 1, borderColor: '#52c41a' }}
            >
              <div style={{ maxHeight: 480, overflowY: 'auto', whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.8 }}>
                {polished}
              </div>
            </Card>
          </div>
        )}

        {polished && (
          <Alert
            type="warning"
            showIcon
            icon={<CloseOutlined />}
            message="确认应用前请仔细阅读 - 应用后会覆盖原文,操作不可撤销"
            style={{ marginTop: 12 }}
          />
        )}
      </Modal>

      <PolishGuidesPicker
        open={pickerOpen}
        initialSelection={selectedGuides}
        onClose={() => setPickerOpen(false)}
        onConfirm={(ids) => setSelectedGuides(ids)}
      />
    </>
  );
}
