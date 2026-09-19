import { Button } from '@filigran/design-system';
import FiligranIcon from '@components/common/FiligranIcon';
import EEChip from '@components/common/entreprise_edition/EEChip';
import EETooltip from '@components/common/entreprise_edition/EETooltip';
import { CGUStatus } from '@components/settings/Experience';
import ValidateTermsOfUseDialog from '@components/settings/ValidateTermsOfUseDialog';
import { useTheme } from '@mui/styles';
import { LogoXtmOneIcon } from 'filigran-icon';
import React, { useEffect, useRef, useState } from 'react';
import type { Theme } from '../../../components/Theme';
import { useFormatter } from '../../../components/i18n';
import useAuth from '../../../utils/hooks/useAuth';
import useEnterpriseEdition from '../../../utils/hooks/useEnterpriseEdition';
import useGranted, { SETTINGS_SETPARAMETERS } from '../../../utils/hooks/useGranted';
import useHelper from '../../../utils/hooks/useHelper';
import AskArianePanel from './AskArianePanel';
import ChatbotManager from './ChatbotManager';
import { useChatbot } from './ChatbotContext';
import { useSettingsMessagesBannerHeight } from '../settings/settings_messages/SettingsMessagesBanner';
import useTopBanner from '../../../utils/hooks/useTopBanner';

const AskArianeButton = () => {
  const { t_i18n } = useFormatter();
  const { isChatbotAiEnabled } = useHelper();
  const { settings: { filigran_chatbot_ai_cgu_status }, bannerSettings: { bannerHeightNumber } } = useAuth();
  const theme = useTheme<Theme>();
  const isEnterpriseEdition = useEnterpriseEdition();
  const hasRightToValidateCGU = useGranted([SETTINGS_SETPARAMETERS]);
  const settingsMessagesBannerHeight = useSettingsMessagesBannerHeight();
  const { height: topBannerHeight } = useTopBanner();
  const {
    isOpen, mode, openChat, closeChat, setMode,
    setSidebarWidth, setIsResizing, xtmOneConfigured, localAgentMode,
  } = useChatbot();

  const isCGUStatusPending = filigran_chatbot_ai_cgu_status === CGUStatus.pending;
  const [openValidateTermsOfUse, setOpenValidateTermsOfUse] = useState(false);

  // Local opencti-agent chat: EE and Filigran CGU are not required — the chat
  // is served by the on-prem agent. XTM One chat keeps its full gate stack
  // (isChatbotAiEnabled() is the CGU status, a Filigran-services concept).
  const isChatbotEnabled = (isEnterpriseEdition && isChatbotAiEnabled()) || localAgentMode;
  const useLegacy = xtmOneConfigured === false && !localAgentMode;
  const localOnly = !isEnterpriseEdition && localAgentMode;

  // Total height of all floating banners stacked above the top bar.
  // Forwarded to the legacy chatbot so its window sticks under the real top bar.
  const totalBannerHeight = bannerHeightNumber + topBannerHeight + settingsMessagesBannerHeight;

  // Legacy v1 web-component management (only active when XTM One is NOT configured)
  const chatbotManager = useRef(ChatbotManager.getInstance());

  useEffect(() => {
    if (useLegacy && isChatbotEnabled) {
      chatbotManager.current.configure(theme, t_i18n, totalBannerHeight);
    }
  }, [useLegacy, isChatbotEnabled, theme, t_i18n, totalBannerHeight]);

  useEffect(() => {
    if (useLegacy && !isChatbotEnabled && chatbotManager.current.isReady()) {
      chatbotManager.current.destroy();
    }
  }, [useLegacy, isChatbotEnabled]);

  useEffect(() => {
    if (useLegacy && chatbotManager.current.isReady()) {
      chatbotManager.current.setOnClose(closeChat);
    }
  }, [useLegacy, chatbotManager.current.isReady(), closeChat]);

  // Sync open/close with legacy ChatbotManager
  useEffect(() => {
    if (!useLegacy) return;
    if (isOpen) {
      chatbotManager.current.open();
    } else if (chatbotManager.current.isReady()) {
      chatbotManager.current.close();
    }
  }, [useLegacy, isOpen]);

  const toggleChatbot = () => {
    // Local agent mode needs no Filigran CGU; XTM One mode does.
    const cguOk = localOnly || filigran_chatbot_ai_cgu_status === CGUStatus.enabled;
    if (cguOk) {
      if (isOpen) {
        closeChat();
      } else {
        openChat();
      }
    } else if (hasRightToValidateCGU) {
      setOpenValidateTermsOfUse(true);
    }
  };

  return (
    <>
      {/* `clickable={false}` keeps the chip a plain element inside the button —
          see fds-migration/MIGRATION-DECISIONS.md#ee-badge-inside-button */}
      <EETooltip
        bypassEE={localOnly}
        title={isCGUStatusPending && !hasRightToValidateCGU ? t_i18n('Ask Ariane isn\'t activated yet. Please reach out to your administrator to enable this feature.') : 'Open chatbot'}
      >
        <Button
          variant="ia"
          priority="tertiary"
          onClick={toggleChatbot}
          // The `ia` variant gradients the LABEL only; the icon keeps `currentColor`, near-black in light.
          startIcon={<FiligranIcon icon={LogoXtmOneIcon} size="small" style={{ color: 'var(--color-filigran-ia-primary)' }} />}
          endIcon={isEnterpriseEdition || localOnly
            ? undefined
            : <EEChip clickable={false} style={{ marginInlineStart: 0 }} />}
        >
          {t_i18n('Ask Ariane')}
        </Button>
      </EETooltip>

      {/* V3 XTM One panel (xtm_one_token configured) — same panel serves the
          local agent in localOnly mode; the backend /chatbot/* routes branch. */}
      {isChatbotEnabled && isOpen && !useLegacy && (xtmOneConfigured === true || localAgentMode) && (
        <AskArianePanel
          mode={mode}
          onClose={closeChat}
          onModeChange={setMode}
          onWidthChange={setSidebarWidth}
          onResizeStart={() => setIsResizing(true)}
          onResizeEnd={() => setIsResizing(false)}
          localOnly={localOnly}
        />
      )}

      {openValidateTermsOfUse && (
        <ValidateTermsOfUseDialog open={openValidateTermsOfUse} onClose={() => setOpenValidateTermsOfUse(false)} />
      )}
    </>
  );
};

AskArianeButton.displayName = 'AskArianeButton';

export default AskArianeButton;
