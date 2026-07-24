import { useCallback, useMemo, useState } from 'react';
import { BarChartOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Empty, Modal, Spin } from 'antd';
import styled from 'styled-components';
import { FlexLayout } from '@kabel/components-react';
import { i18n } from '@kabel/i18n';

import type { LabelStatistic } from '@/api/types';
import { useLabelStatistics } from '@/api/queries/task';
import { TOOL_NAME } from '@/constants/toolName';

const StyledFlexLayout = styled(FlexLayout)`
  max-height: 26.25rem;
  overflow-y: auto;

  > div:nth-child(odd) {
    background-color: var(--color-fill-quaternary);
  }
`;

const FlexLayoutItem = styled(FlexLayout.Item)`
  padding: 0.5rem;
`;

const ColorDot = styled.span<{ color?: string }>`
  width: 0.625rem;
  height: 0.625rem;
  flex: 0 0 auto;
  border: 1px solid var(--color-border-secondary);
  border-radius: 50%;
  background: ${({ color }) => color || 'var(--color-fill-secondary)'};
`;

const LabelMeta = styled.div`
  display: flex;
  min-width: 0;
  flex-direction: column;

  > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  small {
    overflow: hidden;
    color: var(--color-text-tertiary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
`;

const Count = styled.b`
  color: var(--color-primary);
  font-size: 1rem;
  font-variant-numeric: tabular-nums;
`;

interface LabelStatisticsModalProps {
  taskId: number;
}

const LabelStatisticsModal = ({ taskId }: LabelStatisticsModalProps) => {
  const [open, setOpen] = useState(false);
  const t = useCallback(
    (key: string, options?: Record<string, unknown>) => String(options ? i18n.t(key, options) : i18n.t(key)),
    [],
  );
  const statisticsQuery = useLabelStatistics(taskId, open);
  const statistics: LabelStatistic[] = useMemo(() => statisticsQuery.data ?? [], [statisticsQuery.data]);
  const totalCount = useMemo(
    () => statistics.reduce((total: number, item: LabelStatistic) => total + item.count, 0),
    [statistics],
  );

  const getLabelSource = useCallback(
    (record: LabelStatistic) => {
      if (record.scope === 'common') {
        return t('genericLabels');
      }

      if (record.scope === 'tag') {
        return record.category ? `${t('tag')} · ${record.category}` : t('tag');
      }

      return TOOL_NAME[record.tool ?? ''] ?? record.tool ?? '';
    },
    [t],
  );

  return (
    <>
      <Button type="text" icon={<BarChartOutlined />} onClick={() => setOpen(true)}>
        {t('viewAnnotationStatistics')}
      </Button>
      <Modal title={t('annotationStatistics')} open={open} footer={null} onCancel={() => setOpen(false)}>
        <FlexLayout flex="column" gap="1rem" items="stretch">
          {statistics.length > 0 && (
            <Alert
              type="info"
              message={t('annotationStatisticsSummary', {
                labels: statistics.length,
                count: totalCount,
              })}
            />
          )}
          <FlexLayout flex="row" justify="space-between">
            <FlexLayout.Item flex="row" gap=".5rem" items="center">
              {t('label')}
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                loading={statisticsQuery.isFetching}
                onClick={() => statisticsQuery.refetch()}
              />
            </FlexLayout.Item>
            <FlexLayout.Item>{t('markedCount')}</FlexLayout.Item>
          </FlexLayout>
          {statisticsQuery.isFetching && statistics.length === 0 ? (
            <FlexLayout flex="row" justify="center">
              <Spin />
            </FlexLayout>
          ) : statisticsQuery.isError ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('loadAnnotationStatisticsFailed')}>
              <Button icon={<ReloadOutlined />} onClick={() => statisticsQuery.refetch()}>
                {t('retryAnnotationStatistics')}
              </Button>
            </Empty>
          ) : statistics.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('noConfiguredLabels')} />
          ) : (
            <StyledFlexLayout flex="column">
              {statistics.map((record) => (
                <FlexLayoutItem
                  flex="row"
                  key={`${record.scope}-${record.tool ?? ''}-${record.category ?? ''}-${record.value}`}
                  items="center"
                  justify="space-between"
                  gap="1rem"
                >
                  <FlexLayout flex="row" items="center" gap=".625rem" style={{ minWidth: 0 }}>
                    <ColorDot color={record.color ?? undefined} />
                    <LabelMeta>
                      <span>{record.label}</span>
                      <small>
                        {getLabelSource(record)} · {record.value}
                      </small>
                    </LabelMeta>
                  </FlexLayout>
                  <Count>{record.count}</Count>
                </FlexLayoutItem>
              ))}
            </StyledFlexLayout>
          )}
        </FlexLayout>
      </Modal>
    </>
  );
};

export default LabelStatisticsModal;
