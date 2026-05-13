/**
 * 批量 AI 润色模态框
 *
 * 行为：
 *   1. 列出所有有正文的章节，用户多选目标章节
 *   2. 可选择结构化润色指南（与单章润色共用 PolishGuidesPicker）
 *   3. 串行调用 /polish + chapterApi.updateChapter，逐章落库
 *   4. 实时显示进度与每章状态（pending/running/success/failed）
 *   5. 运行中可中止，已完成章节不会回滚
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  List,
  Modal,
  Progress,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  HighlightOutlined,
  LoadingOutlined,
  StopOutlined,
} from '@ant-design/icons';
import type { Chapter, ChapterUpdate } from '../types';
import { chapterApi, polishApi, polishGuidesApi, type PolishGuide } from '../services/api';

const { Text } = Typography;

type RunStatus = 'pending' | 'running' | 'success' | 'failed';

interface ChapterRunState {
  status: RunStatus;
  before?: number;
  after?: number;
  error?: string;
}

interface BatchPolishModalProps {
  open: boolean;
  chapters: Chapter[];
  onClose: () => void;
  onChapterUpdated?: (chapterId: string) => void;
}

export default function BatchPolishModal({
  open,
  chapters,
  onClose,
  onChapterUpdated,
}: BatchPolishModalProps) {
  const eligible = useMemo(
    () => chapters.filter(c => (c.content || '').trim() !== ''),
    [chapters]
  );

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [guides, setGuides] = useState<PolishGuide[]>([]);
  const [guidesLoading, setGuidesLoading] = useState(false);
  const [selectedGuides, setSelectedGuides] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [runStates, setRunStates] = useState<Record<string, ChapterRunState>>({});
  const cancelRef = useRef(false);

  useEffect(() => {
    if (!open || guides.length > 0) return;
    setGuidesLoading(true);
    polishGuidesApi
      .list()
      .then(list => {
        setGuides(list);
        setSelectedGuides(list.map(g => g.id));
      })
      .catch(() => message.error('加载润色指南失败'))
      .finally(() => setGuidesLoading(false));
  }, [open, guides.length]);

  const toggleGuide = (id: string) => {
    setSelectedGuides(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const allSelected = selectedIds.length === eligible.length && eligible.length > 0;
  const someSelected = selectedIds.length > 0 && !allSelected;

  const toggleAll = useCallback(() => {
    setSelectedIds(allSelected ? [] : eligible.map(c => c.id));
  }, [allSelected, eligible]);

  const toggleOne = (id: string) => {
    setSelectedIds(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]));
  };

  const reset = () => {
    setSelectedIds([]);
    setSelectedGuides([]);
    setRunning(false);
    setDone(false);
    setRunStates({});
    cancelRef.current = false;
  };

  const handleClose = () => {
    if (running) {
      message.warning('正在润色中，请先停止或等待完成');
      return;
    }
    reset();
    onClose();
  };

  const handleStart = async () => {
    if (selectedIds.length === 0) {
      message.warning('请至少选择一章');
      return;
    }
    Modal.confirm({
      title: `批量润色 ${selectedIds.length} 章`,
      content: '润色完成后会立即覆盖各章正文，操作不可撤销。确定开始？',
      okText: '开始',
      cancelText: '取消',
      onOk: async () => {
        await runBatch();
      },
    });
  };

  const runBatch = async () => {
    cancelRef.current = false;
    setRunning(true);
    setDone(false);
    const initial: Record<string, ChapterRunState> = {};
    selectedIds.forEach(id => {
      initial[id] = { status: 'pending' };
    });
    setRunStates(initial);

    const targets = eligible.filter(c => selectedIds.includes(c.id));
    for (const ch of targets) {
      if (cancelRef.current) break;
      setRunStates(prev => ({ ...prev, [ch.id]: { status: 'running' } }));
      try {
        const resp = await polishApi.polish({
          original_text: ch.content || '',
          guide_ids: selectedGuides.length > 0 ? selectedGuides : undefined,
        });
        if (cancelRef.current) {
          setRunStates(prev => ({
            ...prev,
            [ch.id]: { status: 'failed', error: '已取消' },
          }));
          break;
        }
        await chapterApi.updateChapter(ch.id, {
          content: resp.polished_text,
        } as ChapterUpdate);
        setRunStates(prev => ({
          ...prev,
          [ch.id]: {
            status: 'success',
            before: resp.word_count_before,
            after: resp.word_count_after,
          },
        }));
        onChapterUpdated?.(ch.id);
      } catch (err) {
        const msg =
          (err as { response?: { data?: { detail?: string } }; message?: string })
            ?.response?.data?.detail ||
          (err as Error)?.message ||
          '润色失败';
        setRunStates(prev => ({
          ...prev,
          [ch.id]: { status: 'failed', error: msg },
        }));
      }
    }

    setRunning(false);
    setDone(true);
  };

  const handleCancel = () => {
    cancelRef.current = true;
    message.info('已请求停止，当前章节完成后将退出');
  };

  const completedCount = Object.values(runStates).filter(
    s => s.status === 'success' || s.status === 'failed'
  ).length;
  const successCount = Object.values(runStates).filter(s => s.status === 'success').length;
  const failedCount = Object.values(runStates).filter(s => s.status === 'failed').length;
  const totalCount = selectedIds.length;

  const renderStatusTag = (state: ChapterRunState | undefined) => {
    if (!state || state.status === 'pending') {
      return <Tag>待处理</Tag>;
    }
    if (state.status === 'running') {
      return <Tag icon={<LoadingOutlined />} color="processing">润色中</Tag>;
    }
    if (state.status === 'success') {
      return (
        <Tag icon={<CheckCircleFilled />} color="success">
          {state.before} → {state.after} 字
        </Tag>
      );
    }
    return (
      <Tag icon={<CloseCircleFilled />} color="error" title={state.error}>
        失败
      </Tag>
    );
  };

  return (
    <>
      <Modal
        title={
          <Space>
            <HighlightOutlined />
            <span>批量 AI 润色</span>
          </Space>
        }
        open={open}
        onCancel={handleClose}
        width="80%"
        style={{ maxWidth: 960 }}
        maskClosable={false}
        footer={
          <Space>
            {!running && !done && (
              <>
                <Button onClick={handleClose}>取消</Button>
                <Button
                  type="primary"
                  icon={<HighlightOutlined />}
                  disabled={selectedIds.length === 0}
                  onClick={handleStart}
                >
                  开始润色（{selectedIds.length}）
                </Button>
              </>
            )}
            {running && (
              <Button danger icon={<StopOutlined />} onClick={handleCancel}>
                停止
              </Button>
            )}
            {done && (
              <Button type="primary" onClick={handleClose}>
                完成
              </Button>
            )}
          </Space>
        }
      >
        {eligible.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="没有可润色的章节"
            description="批量润色仅对已有正文的章节生效。"
          />
        ) : (
          <>
            <Card
              size="small"
              style={{ marginBottom: 12 }}
              title={
                <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
                  <Space>
                    <Text>润色指南</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {selectedGuides.length === 0
                        ? '未选时走通用 AI 去味'
                        : `已选 ${selectedGuides.length}/${guides.length}`}
                    </Text>
                  </Space>
                  <Space size="small">
                    <Button
                      size="small"
                      type="link"
                      disabled={running || guides.length === 0}
                      onClick={() => setSelectedGuides(guides.map(g => g.id))}
                    >
                      全选
                    </Button>
                    <Button
                      size="small"
                      type="link"
                      disabled={running || selectedGuides.length === 0}
                      onClick={() => setSelectedGuides([])}
                    >
                      清空
                    </Button>
                  </Space>
                </Space>
              }
            >
              <Spin spinning={guidesLoading}>
                {guides.length === 0 && !guidesLoading ? (
                  <Text type="secondary">暂无可用指南</Text>
                ) : (
                  <Space size={[8, 8]} wrap>
                    {guides.map(g => {
                      const checked = selectedGuides.includes(g.id);
                      return (
                        <Tooltip key={g.id} title={g.focus} placement="top">
                          <Tag.CheckableTag
                            checked={checked}
                            onChange={() => !running && toggleGuide(g.id)}
                            style={{
                              padding: '4px 12px',
                              fontSize: 13,
                              cursor: running ? 'not-allowed' : 'pointer',
                            }}
                          >
                            {g.name}
                          </Tag.CheckableTag>
                        </Tooltip>
                      );
                    })}
                  </Space>
                )}
              </Spin>
            </Card>

            {(running || done) && (
              <Card size="small" style={{ marginBottom: 12 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Progress
                    percent={
                      totalCount === 0 ? 0 : Math.round((completedCount / totalCount) * 100)
                    }
                    status={
                      failedCount > 0 && done
                        ? 'exception'
                        : done
                          ? 'success'
                          : 'active'
                    }
                  />
                  <Text type="secondary">
                    进度 {completedCount}/{totalCount} · 成功 {successCount} · 失败 {failedCount}
                  </Text>
                </Space>
              </Card>
            )}

            <Card
              size="small"
              title={
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Checkbox
                    checked={allSelected}
                    indeterminate={someSelected}
                    disabled={running}
                    onChange={toggleAll}
                  >
                    全选（{eligible.length} 章有正文）
                  </Checkbox>
                  <Text type="secondary">已选 {selectedIds.length}</Text>
                </Space>
              }
              styles={{ body: { maxHeight: 420, overflowY: 'auto', padding: 0 } }}
            >
              <List
                size="small"
                dataSource={eligible}
                renderItem={item => {
                  const state = runStates[item.id];
                  const checked = selectedIds.includes(item.id);
                  return (
                    <List.Item style={{ padding: '8px 16px' }}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Space>
                          <Checkbox
                            checked={checked}
                            disabled={running}
                            onChange={() => toggleOne(item.id)}
                          />
                          <Text>第{item.chapter_number}章：{item.title}</Text>
                          <Tag>{item.word_count || 0} 字</Tag>
                        </Space>
                        {checked && renderStatusTag(state)}
                      </Space>
                    </List.Item>
                  );
                }}
              />
            </Card>

            {done && failedCount > 0 && (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 12 }}
                message={`有 ${failedCount} 章润色失败，原始内容保持不变`}
                description={
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {Object.entries(runStates)
                      .filter(([, s]) => s.status === 'failed')
                      .map(([id, s]) => {
                        const ch = eligible.find(c => c.id === id);
                        return (
                          <li key={id}>
                            第{ch?.chapter_number}章 {ch?.title}：{s.error}
                          </li>
                        );
                      })}
                  </ul>
                }
              />
            )}
          </>
        )}
      </Modal>
    </>
  );
}
