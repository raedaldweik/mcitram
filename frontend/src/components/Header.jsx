import { useState, useEffect } from 'react';
import { getHealth } from '../services/api';
import { useLanguage } from '../context/LanguageContext';

export default function Header() {
  const [health, setHealth] = useState(null);
  const { t, toggle, lang } = useLanguage();

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: 'down' }));
  }, []);

  const ok = health?.status === 'ok';

  return (
    <header className="app-header">
      {/* Title + accent line (no logo — text brand like the dashboard) */}
      <div className="title-block">
        <div className="title-row">
          <h1 className="app-title">{t('appTitle')}<span style={{ color: 'var(--gold)' }}>.</span></h1>
          <div className="accent-line" />
        </div>
      </div>

      {/* Language toggle + connection status — end side */}
      <div className="flex items-center gap-3">
        <button onClick={toggle}
          title={lang === 'ar' ? 'Switch to English' : 'التبديل إلى العربية'}
          className="px-3.5 py-1.5 rounded-full text-[11.5px] font-bold transition-all hover:scale-105"
          style={{
            background: 'rgba(255,255,255,0.65)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(188,59,51,0.30)', color: 'var(--gold-lo)',
          }}>
          {t('langButton')}
        </button>
        <div className="status-pill">
          <span className={`w-2 h-2 rounded-full ${ok ? '' : 'animate-pulse'}`}
            style={{ background: ok ? 'var(--green)' : health ? 'var(--red)' : 'var(--amber)' }} />
          <span>
            {health == null ? t('connecting')
              : ok ? t('connected')
              : health.status === 'unconfigured' ? t('notConfigured')
              : t('backendOffline')}
          </span>
        </div>
      </div>
    </header>
  );
}
