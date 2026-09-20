import Button from '@common/button/Button';
import Dialog from '@common/dialog/Dialog';
import { Select, SelectContent, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@filigran/design-system';
import DialogActions from '@mui/material/DialogActions';
import Box from '@mui/material/Box';
import { FunctionComponent, useState } from 'react';
import { graphql } from 'react-relay';
import { v4 as uuid } from 'uuid';
import { useFormatter } from '../../../../components/i18n';
import useApiMutation from '../../../../utils/hooks/useApiMutation';
import { copyToClipboard } from '../../../../utils/utils';
import { EntityAiReportButtonThreatReportMutation } from './__generated__/EntityAiReportButtonThreatReportMutation.graphql';
import { EntityAiReportButtonVictimReportMutation } from './__generated__/EntityAiReportButtonVictimReportMutation.graphql';

const entityAiReportButtonThreatReportMutation = graphql`
  mutation EntityAiReportButtonThreatReportMutation(
    $id: ID!
    $threatId: String!
    $paragraphs: Int
    $tone: Tone
    $format: Format
  ) {
    aiThreatGenerateReport(
      id: $id
      threatId: $threatId
      paragraphs: $paragraphs
      tone: $tone
      format: $format
    )
  }
`;

const entityAiReportButtonVictimReportMutation = graphql`
  mutation EntityAiReportButtonVictimReportMutation(
    $id: ID!
    $victimId: String!
    $paragraphs: Int
    $tone: Tone
    $format: Format
  ) {
    aiVictimGenerateReport(
      id: $id
      victimId: $victimId
      paragraphs: $paragraphs
      tone: $tone
      format: $format
    )
  }
`;

interface EntityAiReportButtonProps {
  entityId: string;
  mode: 'threat' | 'victim';
  variant?: 'toggle' | 'button';
}

const EntityAiReportButton: FunctionComponent<EntityAiReportButtonProps> = ({
  entityId,
  mode,
  variant = 'button',
}) => {
  const { t_i18n } = useFormatter();
  const [displayOptions, setDisplayOptions] = useState(false);
  const [displayResult, setDisplayResult] = useState(false);
  const [paragraphs, setParagraphs] = useState('8');
  const [tone, setTone] = useState<'tactical' | 'operational' | 'strategic'>('tactical');
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState('');
  const [commitThreat] = useApiMutation<EntityAiReportButtonThreatReportMutation>(
    entityAiReportButtonThreatReportMutation,
  );
  const [commitVictim] = useApiMutation<EntityAiReportButtonVictimReportMutation>(
    entityAiReportButtonVictimReportMutation,
  );

  const handleOpenOptions = () => {
    if (variant === 'toggle') {
      setDisplayOptions((openState) => !openState);
    } else {
      setDisplayOptions(true);
    }
  };

  const handleCloseOptions = () => {
    if (!committing) {
      setDisplayOptions(false);
    }
  };

  const handleComplete = (response: string | null | undefined) => {
    setCommitting(false);
    setResult(response ?? '');
    setDisplayOptions(false);
    setDisplayResult(true);
  };

  const handleError = (error: Error) => {
    setCommitting(false);
    setResult(t_i18n(`An unknown error occurred, please ask your platform administrator: ${error.toString()}`));
    setDisplayOptions(false);
    setDisplayResult(true);
  };

  const handleGenerate = () => {
    setCommitting(true);
    const id = uuid();
    if (mode === 'threat') {
      commitThreat({
        variables: {
          id,
          threatId: entityId,
          paragraphs: Number(paragraphs),
          tone,
          format: 'text',
        },
        onCompleted: (response) => handleComplete(response.aiThreatGenerateReport),
        onError: handleError,
      });
    } else {
      commitVictim({
        variables: {
          id,
          victimId: entityId,
          paragraphs: Number(paragraphs),
          tone,
          format: 'text',
        },
        onCompleted: (response) => handleComplete(response.aiVictimGenerateReport),
        onError: handleError,
      });
    }
  };

  return (
    <>
      <Button
        variant="tertiary"
        size="small"
        disabled={committing}
        onClick={handleOpenOptions}
      >
        {t_i18n('Generate AI report')}
      </Button>
      <Dialog
        open={displayOptions}
        onClose={handleCloseOptions}
        title={t_i18n('Generate AI report')}
      >
        <Box sx={{ display: 'grid', gap: 2 }}>
          <Select value={paragraphs} onValueChange={(value) => setParagraphs(value)}>
            <SelectLabel>{t_i18n('Paragraphs')}</SelectLabel>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent aria-label={t_i18n('Paragraphs')}>
              <SelectItem value="4">4</SelectItem>
              <SelectItem value="8">8</SelectItem>
              <SelectItem value="12">12</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={tone}
            onValueChange={(value) => setTone(value as 'tactical' | 'operational' | 'strategic')}
          >
            <SelectLabel>{t_i18n('Tone')}</SelectLabel>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent aria-label={t_i18n('Tone')}>
              <SelectItem value="tactical">{t_i18n('Tactical')}</SelectItem>
              <SelectItem value="operational">{t_i18n('Operational')}</SelectItem>
              <SelectItem value="strategic">{t_i18n('Strategic')}</SelectItem>
            </SelectContent>
          </Select>
        </Box>
        <DialogActions>
          <Button variant="secondary" onClick={handleCloseOptions}>
            {t_i18n('Cancel')}
          </Button>
          <Button loading={committing} onClick={handleGenerate}>
            {t_i18n('Generate')}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={displayResult}
        onClose={() => setDisplayResult(false)}
        title={t_i18n('AI report')}
        size="large"
      >
        <pre
          style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: 400,
            overflowY: 'auto',
            margin: 0,
          }}
        >
          {result}
        </pre>
        <DialogActions>
          <Button variant="secondary" onClick={() => setDisplayResult(false)}>
            {t_i18n('Close')}
          </Button>
          <Button onClick={() => copyToClipboard(t_i18n, result)}>
            {t_i18n('Copy')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default EntityAiReportButton;
