import { useState } from 'react';
import { useLanguage } from '../context/LanguageContext';

/**
 * Live snapshot of a SAS Visual Analytics report (or one section of it),
 * rendered server-side through the VA REST APIs and served from the backend
 * image cache. Click the snapshot to zoom; the footer link opens the real
 * report in SAS Visual Analytics.
 */
export default function ReportCard({ spec }) {
  const { t } = useLanguage();
  const [zoom, setZoom] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!spec?.imageUrl || failed) return null;

  return (
    <div className="rounded-xl overflow-hidden animate-slide-up"
      style={{ border: '1px solid rgba(7,102,209,0.18)', background: 'rgba(255,255,255,0.75)' }}>
      {/* Title bar */}
      <div className="flex items-center gap-2 px-3.5 py-2.5"
        style={{ background: 'rgba(7,102,209,0.06)', borderBottom: '1px solid rgba(7,102,209,0.12)' }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="2" className="shrink-0">
          <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>
        </svg>
        <span className="text-[12px] font-bold truncate" style={{ color: 'var(--text)' }}>
          {spec.reportName || 'Visual Analytics report'}
        </span>
        {spec.sectionName && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold shrink-0"
            style={{ background: 'rgba(7,102,209,0.10)', color: 'var(--gold-lo)' }}>
            {spec.sectionName}
          </span>
        )}
        <span className="text-[9px] font-bold tracking-wider uppercase px-1.5 py-0.5 rounded shrink-0 ms-auto"
          style={{ background: 'rgba(59,155,232,0.12)', color: '#0e7490' }}>
          SAS VA
        </span>
      </div>

      {/* Snapshot */}
      <button onClick={() => setZoom(true)} className="block w-full cursor-zoom-in"
        title={t('clickToZoom')}>
        <img src={spec.imageUrl} alt={spec.reportName || 'report'}
          onError={() => setFailed(true)}
          className="w-full h-auto block" style={{ maxHeight: 420, objectFit: 'contain', background: '#fff' }} />
      </button>

      {/* Footer */}
      {spec.viewerUrl && (
        <div className="px-3.5 py-2" style={{ borderTop: '1px solid rgba(7,102,209,0.10)' }}>
          <a href={spec.viewerUrl} target="_blank" rel="noreferrer"
            className="text-[11px] font-semibold hover:underline" style={{ color: 'var(--gold)' }}>
            {t('openInVA')}
          </a>
        </div>
      )}

      {/* Zoom overlay */}
      {zoom && (
        <div className="fixed inset-0 z-[400] flex items-center justify-center p-8 cursor-zoom-out"
          style={{ background: 'rgba(10,22,40,0.75)', backdropFilter: 'blur(4px)' }}
          onClick={() => setZoom(false)}>
          <img src={spec.imageUrl} alt="" className="max-w-full max-h-full rounded-lg shadow-2xl"
            style={{ background: '#fff' }} />
        </div>
      )}
    </div>
  );
}
