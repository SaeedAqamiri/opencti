import Button from '@common/button/Button';
import Dialog from '@common/dialog/Dialog';
import Tag from '@common/tag/Tag';
import TextList from '@common/text/TextList';
import { IndicatorDetails_indicator$data } from '@components/observations/indicators/__generated__/IndicatorDetails_indicator.graphql';
import { IndicatorDetailsAiConvertMutation } from '@components/observations/indicators/__generated__/IndicatorDetailsAiConvertMutation.graphql';
import { TroubleshootOutlined } from '@mui/icons-material';
import { Stack, Tooltip } from '@mui/material';
import Box from '@mui/material/Box';
import Grid from '@mui/material/Grid';
import DialogActions from '@mui/material/DialogActions';
import { Select, SelectContent, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@filigran/design-system';
import { InformationOutline } from 'mdi-material-ui';
import { FunctionComponent, useState } from 'react';
import { createFragmentContainer, graphql } from 'react-relay';
import { v4 as uuid } from 'uuid';
import Card from '../../../../components/common/card/Card';
import Label from '../../../../components/common/label/Label';
import ExpandableMarkdown from '../../../../components/ExpandableMarkdown';
import FieldOrEmpty from '../../../../components/FieldOrEmpty';
import { useFormatter } from '../../../../components/i18n';
import ItemBoolean from '../../../../components/ItemBoolean';
import ItemScore from '../../../../components/ItemScore';
import StixCoreObjectKillChainPhasesView from '../../common/stix_core_objects/StixCoreObjectKillChainPhasesView';
import DecayDialogContent from './DecayDialogContent';
import DecayExclusionDialogContent from './DecayExclusionDialogContent';
import IndicatorObservables from './IndicatorObservables';
import ExpandablePre from '../../../../components/ExpandablePre';
import useApiMutation from '../../../../utils/hooks/useApiMutation';
import { copyToClipboard } from '../../../../utils/utils';

const indicatorDetailsAiConvertMutation = graphql`
  mutation IndicatorDetailsAiConvertMutation(
    $id: ID!
    $indicatorId: String!
    $format: IndicatorFormat!
  ) {
    aiConvertIndicator(id: $id, indicatorId: $indicatorId, format: $format)
  }
`;

interface IndicatorDetailsComponentProps {
  indicator: IndicatorDetails_indicator$data;
}

const IndicatorDetailsComponent: FunctionComponent<IndicatorDetailsComponentProps> = ({
  indicator,
}) => {
  const { t_i18n, fldt } = useFormatter();
  const [isLifecycleOpen, setIsLifecycleOpen] = useState(false);
  const onDecayLifecycleClose = () => {
    setIsLifecycleOpen(false);
  };

  const openLifecycleDialog = () => {
    setIsLifecycleOpen(true);
  };

  const [displayConvert, setDisplayConvert] = useState(false);
  const [displayConvertResult, setDisplayConvertResult] = useState(false);
  const [convertFormat, setConvertFormat] = useState<'stix' | 'sigma' | 'yara'>('stix');
  const [converting, setConverting] = useState(false);
  const [convertResult, setConvertResult] = useState('');
  const [commitConvert] = useApiMutation<IndicatorDetailsAiConvertMutation>(
    indicatorDetailsAiConvertMutation,
  );

  const handleOpenConvert = () => {
    setConvertFormat('stix');
    setDisplayConvert(true);
  };

  const handleCloseConvert = () => {
    if (!converting) {
      setDisplayConvert(false);
    }
  };

  const handleConvert = () => {
    setConverting(true);
    const id = uuid();
    commitConvert({
      variables: {
        id,
        indicatorId: indicator.id,
        format: convertFormat,
      },
      onCompleted: (response) => {
        setConverting(false);
        setConvertResult(response.aiConvertIndicator ?? '');
        setDisplayConvert(false);
        setDisplayConvertResult(true);
      },
      onError: (error: Error) => {
        setConverting(false);
        setConvertResult(t_i18n(`An unknown error occurred, please ask your platform administrator: ${error.toString()}`));
        setDisplayConvert(false);
        setDisplayConvertResult(true);
      },
    });
  };

  return (
    <Box sx={{ height: '100%' }} className="break">
      <Card title={t_i18n('Details')} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div>
          <Label>
            {t_i18n('Description')}
          </Label>
          <ExpandableMarkdown
            source={indicator.description}
            limit={400}
            removeLinks
          />
        </div>
        <div>

          <Label>
            {t_i18n('Indicator pattern')}
          </Label>
          <FieldOrEmpty source={indicator.pattern}>
            <ExpandablePre source={indicator.pattern} limit={300} />
          </FieldOrEmpty>
        </div>

        <div>
          <Label>
            {t_i18n('Convert with AI')}
          </Label>
          <Button
            variant="tertiary"
            size="small"
            disabled={converting}
            onClick={handleOpenConvert}
          >
            {t_i18n('Convert with AI')}
          </Button>
          <Dialog
            open={displayConvert}
            onClose={handleCloseConvert}
            title={t_i18n('Convert with AI')}
          >
            <Select
              value={convertFormat}
              onValueChange={(value) => setConvertFormat(value as 'stix' | 'sigma' | 'yara')}
            >
              <SelectLabel>{t_i18n('Format')}</SelectLabel>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent aria-label={t_i18n('Format')}>
                <SelectItem value="stix">{t_i18n('STIX')}</SelectItem>
                <SelectItem value="sigma">{t_i18n('SIGMA')}</SelectItem>
                <SelectItem value="yara">{t_i18n('YARA')}</SelectItem>
              </SelectContent>
            </Select>
            <DialogActions>
              <Button variant="secondary" onClick={handleCloseConvert}>
                {t_i18n('Cancel')}
              </Button>
              <Button loading={converting} onClick={handleConvert}>
                {t_i18n('Convert')}
              </Button>
            </DialogActions>
          </Dialog>
          <Dialog
            open={displayConvertResult}
            onClose={() => setDisplayConvertResult(false)}
            title={t_i18n('Converted indicator')}
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
              {convertResult}
            </pre>
            <DialogActions>
              <Button variant="secondary" onClick={() => setDisplayConvertResult(false)}>
                {t_i18n('Close')}
              </Button>
              <Button onClick={() => copyToClipboard(t_i18n, convertResult)}>
                {t_i18n('Copy')}
              </Button>
            </DialogActions>
          </Dialog>
        </div>

        <Grid container={true} spacing={2} sx={{ mt: 0 }}>
          <Grid item xs={6}>
            <Label>
              {t_i18n('Valid from')}
            </Label>
            <span>{fldt(indicator.valid_from)}</span>
            <Label
              sx={{ mt: 2 }}
              action={indicator.decay_applied_rule && (
                <Tooltip
                  title={t_i18n(
                    'This score is updated with the decay rule applied to this indicator.',
                  )}
                >
                  <InformationOutline fontSize="small" color="primary" />
                </Tooltip>
              )}
            >
              {t_i18n('Score')}
            </Label>
            <Stack direction="row" gap={1}>
              <ItemScore score={indicator.x_opencti_score} />
              {(indicator.decay_applied_rule
                || !!indicator.decay_exclusion_applied_rule) && (
                <>
                  <Button
                    size="small"
                    variant="secondary"
                    onClick={openLifecycleDialog}
                    startIcon={<TroubleshootOutlined fontSize="small" />}
                    color={indicator.decay_exclusion_applied_rule ? 'warn' : 'primary'}
                    keepMui
                  >
                    {t_i18n('Lifecycle')}
                  </Button>
                  {indicator.decay_exclusion_applied_rule ? (
                    <DecayExclusionDialogContent
                      open={isLifecycleOpen}
                      indicator={indicator}
                      onClose={onDecayLifecycleClose}
                    />
                  ) : (
                    <DecayDialogContent
                      open={isLifecycleOpen}
                      indicator={indicator}
                      onClose={onDecayLifecycleClose}
                    />
                  )}
                </>
              )}
            </Stack>
          </Grid>
          <Grid item xs={6}>
            <Label>
              {t_i18n('Valid until')}
            </Label>
            <span>{fldt(indicator.valid_until)}</span>
            <Label
              sx={{ marginTop: 2 }}
            >
              {t_i18n('Detection')}
            </Label>
            <ItemBoolean
              label={
                indicator.x_opencti_detection ? t_i18n('Yes') : t_i18n('No')
              }
              status={indicator.x_opencti_detection}
            />
            <StixCoreObjectKillChainPhasesView
              killChainPhases={indicator.killChainPhases ?? []}
            />
          </Grid>
        </Grid>
        <Grid container={true} spacing={3} sx={{ marginBottom: '10px' }}>
          <Grid item xs={4}>
            <Label
              sx={{ marginTop: 2 }}
            >
              {t_i18n('Indicator types')}
            </Label>
            <FieldOrEmpty source={indicator.indicator_types}>
              <Stack direction="row" flexWrap="wrap" gap={1}>
                {indicator.indicator_types?.map((indicatorType) => (
                  <Tag
                    key={indicatorType}
                    label={indicatorType}
                  />
                ))}
              </Stack>
            </FieldOrEmpty>
          </Grid>
          <Grid item xs={4}>
            <Label
              sx={{ marginTop: 2 }}
            >
              {t_i18n('Main observable type')}
            </Label>
            <FieldOrEmpty source={indicator.x_opencti_main_observable_type}>
              <Tag
                label={indicator.x_opencti_main_observable_type}
              />
            </FieldOrEmpty>
          </Grid>
          <Grid item xs={4}>
            <Label
              sx={{ marginTop: 2 }}
            >
              {t_i18n('Platforms')}
            </Label>
            <TextList list={indicator.x_mitre_platforms} />
          </Grid>
        </Grid>
        <IndicatorObservables indicator={indicator} />
      </Card>
    </Box>
  );
};

const IndicatorDetails = createFragmentContainer(IndicatorDetailsComponent, {
  indicator: graphql`
    fragment IndicatorDetails_indicator on Indicator {
      id
      description
      pattern
      valid_from
      valid_until
      x_opencti_score
      x_opencti_detection
      x_opencti_main_observable_type
      x_opencti_reliability
      x_mitre_platforms
      indicator_types
      decay_base_score
      decay_base_score_date
      decay_history {
        score
        updated_at
      }
      decay_exclusion_applied_rule {
        decay_exclusion_name
      }
      decay_applied_rule {
        decay_rule_id
        decay_lifetime
        decay_pound
        decay_points
        decay_revoke_score
      }
      decayLiveDetails {
        live_score
        live_points {
          score
          updated_at
        }
      }
      decayChartData {
        live_score_serie {
          updated_at
          score
        }
      }
      objectLabel {
        id
        value
        color
      }
      killChainPhases {
        id
        entity_type
        kill_chain_name
        phase_name
        x_opencti_order
      }
      ...IndicatorObservables_indicator
    }
  `,
});

export default IndicatorDetails;
