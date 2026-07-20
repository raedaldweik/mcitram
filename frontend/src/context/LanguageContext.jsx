import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { translate } from '../services/i18n';

const LanguageContext = createContext();

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem('ui-lang') || 'en'; } catch { return 'en'; }
  });

  useEffect(() => {
    try { localStorage.setItem('ui-lang', lang); } catch { /* private mode */ }
    document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
    document.documentElement.lang = lang;
  }, [lang]);

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang]);
  const toggle = useCallback(() => setLang(l => (l === 'ar' ? 'en' : 'ar')), []);

  return (
    <LanguageContext.Provider value={{ lang, t, toggle, isRTL: lang === 'ar' }}>
      {children}
    </LanguageContext.Provider>
  );
}

export const useLanguage = () => useContext(LanguageContext);
