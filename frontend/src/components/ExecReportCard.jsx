import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ChartCard from './ChartCard';
import { useLanguage } from '../context/LanguageContext';

/**
 * Consultant-style executive report emitted by the render_report tool:
 * title block, KPI tiles, sections with prose / tables / chart exhibits,
 * and a prioritized recommendations list. Styled like the Strategic
 * Reserve Monitor's editorial "control desk" look.
 */

const TONE = {
  ok:      { color: 'var(--green)', border: 'rgba(91,122,67,0.45)' },
  warn:    { color: 'var(--amber)', border: 'rgba(176,122,42,0.45)' },
  alarm:   { color: 'var(--gold)',  border: 'rgba(188,59,51,0.50)' },
  neutral: { color: 'var(--text)',  border: 'rgba(211,204,186,0.8)' },
};

const md = {
  p: ({node, ...props}) => <p className="my-1 leading-[1.75]" {...props} />,
  strong: ({node, ...props}) => <strong style={{ color: 'var(--gold)', fontWeight: 700 }} {...props} />,
  em: ({node, ...props}) => <em style={{ color: 'var(--gold-lo)' }} {...props} />,
  ul: ({node, ...props}) => <ul className="my-1.5 space-y-0.5 ps-5 list-disc" {...props} />,
  ol: ({node, ...props}) => <ol className="my-1.5 space-y-0.5 ps-5 list-decimal" {...props} />,
  li: ({node, ...props}) => <li className="leading-[1.7]" {...props} />,
};

export default function ExecReportCard({ spec }) {
  const { t } = useLanguage();
  if (!spec?.sections?.length) return null;

  return (
    <div className="rounded-xl overflow-hidden animate-slide-up"
      style={{
        border: '1px solid rgba(211,204,186,0.8)',
        background: 'linear-gradient(180deg, rgba(251,247,238,0.97) 0%, rgba(244,238,225,0.94) 100%)',
        boxShadow: 'var(--glass-shadow-lg)',
      }}>

      {/* Title block — red top rule like the dashboard hero */}
      <div style={{ borderTop: '4px solid var(--gold)' }} className="px-6 pt-4 pb-4">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <span className="text-[9.5px] font-bold tracking-[0.16em] uppercase"
            style={{ color: 'var(--gold)' }}>
            {t('execReport')}
          </span>
          {spec.date && (
            <span className="text-[10px] font-mono" style={{ color: 'var(--text-faint)' }}>{spec.date}</span>
          )}
        </div>
        <h1 className="text-[19px] font-bold leading-tight mt-1.5"
          style={{ color: 'var(--text)', letterSpacing: '-0.02em' }}>
          {spec.title}
        </h1>
        {spec.subtitle && (
          <p className="text-[12px] mt-1" style={{ color: 'var(--text-dim)' }}>{spec.subtitle}</p>
        )}
        {spec.preparedFor && (
          <p className="text-[10.5px] mt-1.5 font-semibold" style={{ color: 'var(--gold-lo)' }}>{spec.preparedFor}</p>
        )}
      </div>

      {/* KPI tiles */}
      {spec.kpis?.length > 0 && (
        <div className="px-6 pb-4 grid gap-2.5"
          style={{ gridTemplateColumns: `repeat(${Math.min(spec.kpis.length, 3)}, minmax(0,1fr))` }}>
          {spec.kpis.map((k, i) => {
            const tone = TONE[k.tone] || TONE.neutral;
            return (
              <div key={i} className="rounded-lg px-3 py-2.5"
                style={{ background: 'rgba(251,250,245,0.85)', border: `1px solid ${tone.border}` }}>
                <div className="text-[10px] font-semibold mb-1" style={{ color: 'var(--text-dim)' }}>{k.label}</div>
                <div className="text-[16px] font-bold font-mono leading-none" style={{ color: tone.color }}>{k.value}</div>
                {k.sub && <div className="text-[10px] mt-1 leading-snug" style={{ color: 'var(--text-dim)' }}>{k.sub}</div>}
              </div>
            );
          })}
        </div>
      )}

      {/* Sections */}
      <div className="px-6 pb-2">
        {spec.sections.map((sec, i) => (
          <div key={i} className="mb-4">
            <h2 className="text-[11px] font-bold tracking-[0.1em] uppercase pb-1.5 mb-2 flex items-center gap-2"
              style={{ color: 'var(--text)', borderBottom: '1px solid rgba(211,204,186,0.8)' }}>
              <span className="inline-block w-[3px] h-3.5 rounded" style={{ background: 'var(--gold)' }} />
              {sec.heading}
            </h2>
            <div className="text-[12.5px] leading-relaxed" style={{ color: 'var(--text)' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={md}>{sec.body}</ReactMarkdown>
            </div>

            {sec.table?.columns && (
              <div className="my-2.5 overflow-x-auto rounded-lg" style={{ border: '1px solid rgba(211,204,186,0.9)' }}>
                <table className="border-collapse text-[11.5px] w-full">
                  <thead style={{ background: 'rgba(188,59,51,0.06)' }}>
                    <tr>
                      {sec.table.columns.map((c, ci) => (
                        <th key={ci} className="px-2.5 py-1.5 text-start font-semibold whitespace-nowrap"
                          style={{ color: 'var(--gold)', borderBottom: '1px solid rgba(211,204,186,0.9)' }}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sec.table.rows.map((row, ri) => (
                      <tr key={ri} style={ri % 2 ? { background: 'rgba(232,227,213,0.35)' } : undefined}>
                        {row.map((cell, ci) => (
                          <td key={ci} className="px-2.5 py-1.5 font-mono text-[11px]"
                            style={{ color: 'var(--text)' }}>{String(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {sec.chart && <div className="my-2.5"><ChartCard spec={{ ...sec.chart, kind: 'chart' }} /></div>}
          </div>
        ))}
      </div>

      {/* Recommendations */}
      {spec.recommendations?.length > 0 && (
        <div className="px-6 pb-4">
          <h2 className="text-[11px] font-bold tracking-[0.1em] uppercase pb-1.5 mb-2 flex items-center gap-2"
            style={{ color: 'var(--gold)', borderBottom: '1px solid rgba(211,204,186,0.8)' }}>
            <span className="inline-block w-[3px] h-3.5 rounded" style={{ background: 'var(--gold)' }} />
            {t('reportRecommendations')}
          </h2>
          <div className="space-y-2">
            {spec.recommendations.map((r, i) => (
              <div key={i} className="flex gap-2.5 items-start rounded-lg px-3 py-2.5"
                style={{ background: 'rgba(188,59,51,0.05)', border: '1px solid rgba(188,59,51,0.16)' }}>
                <span className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5"
                  style={{ background: 'var(--gold)', color: '#FBFAF5' }}>{i + 1}</span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[12.5px] font-bold" style={{ color: 'var(--text)' }}>{r.title}</span>
                    {r.priority && (
                      <span className="text-[9px] font-bold tracking-wider uppercase px-1.5 py-0.5 rounded-full"
                        style={{ background: 'rgba(188,59,51,0.12)', color: 'var(--gold-lo)' }}>{r.priority}</span>
                    )}
                  </div>
                  {r.detail && <p className="text-[11.5px] mt-0.5 leading-relaxed" style={{ color: 'var(--text-md)' }}>{r.detail}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      {(spec.sources || true) && (
        <div className="px-6 py-2.5 text-[10px] flex items-center justify-between gap-3 flex-wrap"
          style={{ borderTop: '1px solid rgba(211,204,186,0.7)', color: 'var(--text-faint)', background: 'rgba(232,227,213,0.4)' }}>
          <span>{spec.sources || ''}</span>
          <span className="font-semibold shrink-0">{t('reportGeneratedBy')}</span>
        </div>
      )}
    </div>
  );
}
