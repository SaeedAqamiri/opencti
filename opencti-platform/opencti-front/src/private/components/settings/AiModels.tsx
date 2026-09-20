import Button from '@common/button/Button';
import Dialog from '@common/dialog/Dialog';
import Tag from '@common/tag/Tag';
import { Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@filigran/design-system';
import { AiModels$key } from '@components/settings/__generated__/AiModels.graphql';
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import React, { FunctionComponent, useState } from 'react';
import { graphql, PreloadedQuery, useFragment, usePreloadedQuery } from 'react-relay';
import Breadcrumbs from '../../../components/Breadcrumbs';
import { useFormatter } from '../../../components/i18n';
import Loader, { LoaderVariant } from '../../../components/Loader';
import useApiMutation from '../../../utils/hooks/useApiMutation';
import useConnectedDocumentModifier from '../../../utils/hooks/useConnectedDocumentModifier';
import useQueryLoading from '../../../utils/hooks/useQueryLoading';
import { AiModelsQuery } from './__generated__/AiModelsQuery.graphql';
import { AiModelsProviderAddMutation } from './__generated__/AiModelsProviderAddMutation.graphql';
import { AiModelsProviderDeleteMutation } from './__generated__/AiModelsProviderDeleteMutation.graphql';
import { AiModelsProviderEditMutation } from './__generated__/AiModelsProviderEditMutation.graphql';
import { AiModelsProviderSetActiveMutation } from './__generated__/AiModelsProviderSetActiveMutation.graphql';

const ENV_PROVIDER_ID = 'env';

// Keep in sync with AI_PROVIDER_PRESETS in opencti-graphql/src/modules/ai/ai-config.ts
const AI_PROVIDER_PRESETS = [
  { id: 'avalai-deepseek-v4-1-flash', name: 'AvalAI · DeepSeek v4.1 Flash', endpoint: 'https://api.avalai.ir/v1', model: 'deepseek-v4.1-flash' },
  { id: 'zai-glm-5-3-flash', name: 'Z.AI · GLM 5.3 Flash', endpoint: 'https://api.z.ai/api/coding/paas/v4', model: 'glm-5.3-flash' },
];

const AiModelsFragment = graphql`
  fragment AiModels on Settings {
    id
    platform_ai_providers {
      id
      name
      endpoint
      model
      api_key_set
    }
    platform_ai_active_provider
  }
`;

const aiModelsQuery = graphql`
  query AiModelsQuery {
    settings {
      ...AiModels
    }
  }
`;

export const aiProviderAddMutation = graphql`
  mutation AiModelsProviderAddMutation($id: ID!, $input: AiProviderInput!) {
    settingsEdit(id: $id) {
      aiProviderAdd(input: $input) {
        ...AiModels
      }
    }
  }
`;

export const aiProviderEditMutation = graphql`
  mutation AiModelsProviderEditMutation($id: ID!, $providerId: ID!, $input: AiProviderInput!) {
    settingsEdit(id: $id) {
      aiProviderEdit(id: $providerId, input: $input) {
        ...AiModels
      }
    }
  }
`;

export const aiProviderDeleteMutation = graphql`
  mutation AiModelsProviderDeleteMutation($id: ID!, $providerId: ID!) {
    settingsEdit(id: $id) {
      aiProviderDelete(id: $providerId) {
        ...AiModels
      }
    }
  }
`;

export const aiProviderSetActiveMutation = graphql`
  mutation AiModelsProviderSetActiveMutation($id: ID!, $providerId: ID!) {
    settingsEdit(id: $id) {
      aiProviderSetActive(id: $providerId) {
        ...AiModels
      }
    }
  }
`;

interface ProviderForm {
  name: string;
  endpoint: string;
  model: string;
  api_key: string;
}

interface AiModelsComponentProps {
  queryRef: PreloadedQuery<AiModelsQuery>;
}

const AiModelsComponent: FunctionComponent<AiModelsComponentProps> = ({ queryRef }) => {
  const { t_i18n } = useFormatter();
  const { setTitle } = useConnectedDocumentModifier();
  setTitle(t_i18n('AI Models | Settings'));
  const data = usePreloadedQuery(aiModelsQuery, queryRef);
  const settings = useFragment<AiModels$key>(AiModelsFragment, data.settings);
  const [commitAdd] = useApiMutation<AiModelsProviderAddMutation>(aiProviderAddMutation);
  const [commitEdit] = useApiMutation<AiModelsProviderEditMutation>(aiProviderEditMutation);
  const [commitDelete] = useApiMutation<AiModelsProviderDeleteMutation>(aiProviderDeleteMutation);
  const [commitSetActive] = useApiMutation<AiModelsProviderSetActiveMutation>(aiProviderSetActiveMutation);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [presetId, setPresetId] = useState('custom');
  const [form, setForm] = useState<ProviderForm>({ name: '', endpoint: '', model: '', api_key: '' });
  const [error, setError] = useState<string | null>(null);

  const providers = settings.platform_ai_providers ?? [];
  const editingProvider = providers.find((p) => p.id === editingId);
  const deletingProvider = providers.find((p) => p.id === deletingId);
  const canSubmit = form.name.trim() !== '' && /^https?:\/\//i.test(form.endpoint.trim()) && form.model.trim() !== '';

  const openAddDialog = () => {
    setEditingId(null);
    setPresetId('custom');
    setForm({ name: '', endpoint: '', model: '', api_key: '' });
    setError(null);
    setFormOpen(true);
  };

  const openEditDialog = (provider: { id: string; name: string; endpoint: string; model: string }) => {
    setEditingId(provider.id);
    setPresetId('custom');
    setForm({ name: provider.name, endpoint: provider.endpoint, model: provider.model, api_key: '' });
    setError(null);
    setFormOpen(true);
  };

  const handlePresetChange = (value: string) => {
    setPresetId(value);
    const preset = AI_PROVIDER_PRESETS.find((p) => p.id === value);
    if (preset) {
      setForm((f) => ({ ...f, name: preset.name, endpoint: preset.endpoint, model: preset.model }));
    }
  };

  const submitForm = () => {
    const input = {
      name: form.name.trim(),
      endpoint: form.endpoint.trim(),
      model: form.model.trim(),
      api_key: form.api_key.trim(),
    };
    const onError = (e: Error) => setError(e.message);
    if (editingId) {
      commitEdit({
        variables: { id: settings.id, providerId: editingId, input },
        onError,
        onCompleted: () => setFormOpen(false),
      });
    } else {
      commitAdd({
        variables: { id: settings.id, input },
        onError,
        onCompleted: () => setFormOpen(false),
      });
    }
  };

  return (
    <div style={{ margin: 0, padding: '0 0 50px 0' }} data-testid="ai-models-page">
      <Breadcrumbs elements={[{ label: t_i18n('Settings') }, { label: t_i18n('AI Models'), current: true }]} />
      <Stack direction="row" alignItems="center" justifyContent="space-between" style={{ marginBottom: 16 }}>
        <Typography variant="h4" gutterBottom={true}>
          {t_i18n('AI Models')}
        </Typography>
        <Button onClick={openAddDialog}>{t_i18n('Add a model')}</Button>
      </Stack>
      <Typography variant="body2" color="textSecondary" style={{ marginBottom: 16 }}>
        {t_i18n('OpenAI-compatible endpoints only. The selected model is used for all AI features (insight, NLQ, summaries).')}
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>{t_i18n('Name')}</TableCell>
            <TableCell>{t_i18n('Model')}</TableCell>
            <TableCell>{t_i18n('Endpoint')}</TableCell>
            <TableCell>{t_i18n('API key')}</TableCell>
            <TableCell align="right">{t_i18n('Actions')}</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {providers.map((provider) => {
            const isActive = settings.platform_ai_active_provider === provider.id;
            return (
              <TableRow key={provider.id} hover={!isActive} selected={isActive}>
                <TableCell>
                  <Stack direction="row" alignItems="center" spacing={1}>
                    <span>{provider.name}</span>
                    {isActive && <Tag label={t_i18n('Active')} labelTextTransform="none" disableTooltip />}
                  </Stack>
                </TableCell>
                <TableCell>{provider.model}</TableCell>
                <TableCell>{provider.endpoint}</TableCell>
                <TableCell>
                  {provider.api_key_set
                    ? <Tag label={t_i18n('Configured')} color="success" labelTextTransform="none" disableTooltip />
                    : <Tag label={t_i18n('Not set')} labelTextTransform="none" disableTooltip />}
                </TableCell>
                <TableCell align="right">
                  <Stack direction="row" spacing={1} justifyContent="flex-end">
                    {!isActive && (
                      <Button
                        variant="secondary"
                        size="small"
                        onClick={() => commitSetActive({ variables: { id: settings.id, providerId: provider.id } })}
                      >
                        {t_i18n('Set active')}
                      </Button>
                    )}
                    {provider.id !== ENV_PROVIDER_ID && (
                      <>
                        <Button variant="secondary" size="small" onClick={() => openEditDialog(provider)}>
                          {t_i18n('Edit')}
                        </Button>
                        <Button variant="secondary" size="small" onClick={() => setDeletingId(provider.id)}>
                          {t_i18n('Delete')}
                        </Button>
                      </>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <Dialog
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editingId ? t_i18n('Edit an AI model') : t_i18n('Add an AI model')}
      >
        <Stack spacing={2}>
          {!editingId && (
            <Select value={presetId} onValueChange={handlePresetChange}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent aria-label={t_i18n('Start from a preset')}>
                <SelectItem value="custom">{t_i18n('Custom (OpenAI-compatible)')}</SelectItem>
                {AI_PROVIDER_PRESETS.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>{preset.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Input
            label={t_i18n('Name')}
            value={form.name}
            onChange={(event) => setForm((f) => ({ ...f, name: event.target.value }))}
          />
          <Input
            label={t_i18n('Endpoint (OpenAI-compatible base URL)')}
            placeholder="https://provider.example/v1"
            value={form.endpoint}
            onChange={(event) => setForm((f) => ({ ...f, endpoint: event.target.value }))}
          />
          <Input
            label={t_i18n('Model')}
            placeholder="gpt-4o / deepseek-v4.1-flash / glm-5.3-flash..."
            value={form.model}
            onChange={(event) => setForm((f) => ({ ...f, model: event.target.value }))}
          />
          <Input
            label={t_i18n('API key')}
            value={form.api_key}
            placeholder={editingProvider?.api_key_set ? t_i18n('Leave empty to keep the current key') : ''}
            onChange={(event) => setForm((f) => ({ ...f, api_key: event.target.value }))}
          />
          {error && <Typography color="error">{error}</Typography>}
        </Stack>
        <Box style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <Button variant="secondary" onClick={() => setFormOpen(false)}>
            {t_i18n('Cancel')}
          </Button>
          <Button onClick={submitForm} disabled={!canSubmit}>
            {editingId ? t_i18n('Update') : t_i18n('Create')}
          </Button>
        </Box>
      </Dialog>

      <Dialog
        open={deletingId !== null}
        onClose={() => setDeletingId(null)}
        title={t_i18n('Delete an AI model')}
      >
        <Typography>
          {t_i18n('Do you want to delete this AI model?')} {deletingProvider && `(${deletingProvider.name})`}
        </Typography>
        <Box style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <Button variant="secondary" onClick={() => setDeletingId(null)}>
            {t_i18n('Cancel')}
          </Button>
          <Button
            onClick={() => {
              if (deletingId) {
                commitDelete({
                  variables: { id: settings.id, providerId: deletingId },
                  onError: (e: Error) => setError(e.message),
                });
              }
              setDeletingId(null);
            }}
          >
            {t_i18n('Delete')}
          </Button>
        </Box>
      </Dialog>
    </div>
  );
};

const AiModels: FunctionComponent = () => {
  const queryRef = useQueryLoading<AiModelsQuery>(aiModelsQuery, {});
  return (
    <>
      {queryRef && (
        <React.Suspense fallback={<Loader variant={LoaderVariant.inElement} />}>
          <AiModelsComponent queryRef={queryRef} />
        </React.Suspense>
      )}
    </>
  );
};

export default AiModels;
