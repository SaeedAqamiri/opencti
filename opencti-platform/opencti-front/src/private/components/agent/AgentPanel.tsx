import React, { useState } from 'react';
import { Button, Input, Spinner } from '@filigran/design-system';
import MarkdownDisplay from '../../../components/markdownDisplay/MarkdownDisplay';
import { useFormatter } from '../../../components/i18n';
import { MESSAGING$ } from '../../../relay/environment';

const AGENT_TIMEOUT_MS = 180_000;

const AgentPanel: React.FC = () => {
  const { t_i18n } = useFormatter();
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState('');
  const [cited, setCited] = useState<string[]>([]);

  const askAgent = async () => {
    if (loading || question.trim().length < 5) return;
    setLoading(true);
    setAnswer('');
    setCited([]);
    try {
      const response = await fetch('/ai-agent/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        signal: AbortSignal.timeout(AGENT_TIMEOUT_MS),
        body: JSON.stringify({ question: question.trim() }),
      });
      const data = await response.json();
      if (!response.ok) {
        MESSAGING$.notifyError(data?.error ?? t_i18n('Agent request failed'));
      } else {
        setAnswer(data.answer ?? '');
        setCited(data.cited ?? []);
      }
    } catch (e) {
      MESSAGING$.notifyError(t_i18n('The agent could not be reached'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 900 }}>
      <Input
        label={t_i18n('Ask the threat-intel agent (read-only)')}
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        disabled={loading}
        placeholder={t_i18n('e.g. Which malware is shared between APT28 and APT29?')}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Button onClick={askAgent} disabled={loading || question.trim().length < 5}>
          {t_i18n('Ask')}
        </Button>
        {loading && <Spinner size="md" />}
      </div>
      {answer && (
        <div style={{
          border: '1px solid rgba(128,128,128,0.35)',
          borderRadius: 6,
          padding: 16,
        }}
        >
          <MarkdownDisplay content={answer} remarkGfmPlugin commonmark />
          {cited.length > 0 && (
            <div style={{ marginTop: 12, opacity: 0.75, fontSize: 12 }}>
              {t_i18n('Cited entities')}
              :
              {' '}
              {cited.join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default AgentPanel;
