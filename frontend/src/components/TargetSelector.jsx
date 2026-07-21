import { useState } from 'react';
import { useLanguage } from '../context/LanguageContext';

/**
 * Dropdown to pick which agent the chat talks to,
 * with optional extra target groups.
 */
export default function TargetSelector({ agents, collections, target, onChange, loading, error }) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);

  const all = [
    ...agents.map(a => ({ ...a, type: 'agent' })),
    ...collections.map(c => ({ ...c, type: 'collection' })),
  ];
  const selected = target ? all.find(x => x.type === target.type && x.id === target.id) : null;

  const pick = (item) => {
    onChange({ type: item.type, id: item.id, name: item.name });
    setOpen(false);
  };

  const Group = ({ label, items, type }) => items.length > 0 && (
    <div>
      <p className="px-3 pt-2.5 pb-1 text-[9px] font-bold tracking-widest uppercase" style={{ color: 'var(--text-dim)' }}>{label}</p>
      {items.map(item => {
        const isActive = target && target.type === type && target.id === item.id;
        return (
          <button key={item.id} onClick={() => pick({ ...item, type })}
            className="w-full text-left px-3 py-2 transition-all hover:bg-[rgba(188,59,51,0.06)]"
            style={isActive ? { background: 'rgba(188,59,51,0.10)', borderInlineStart: '3px solid var(--gold)' } : { borderInlineStart: '3px solid transparent' }}>
            <p className="text-[12px] font-semibold truncate" style={{ color: isActive ? 'var(--gold-lo)' : 'var(--text)' }}>{item.name}</p>
            {item.description && (
              <p className="text-[10.5px] truncate" style={{ color: 'var(--text-dim)' }}>{item.description}</p>
            )}
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)}
        className="flex items-center gap-2 pl-3 pr-2.5 py-1.5 rounded-lg text-[12px] font-semibold transition-all"
        style={{
          background: 'rgba(250,246,236,0.75)', backdropFilter: 'blur(12px)',
          border: '1px solid rgba(188,59,51,0.22)', color: 'var(--text)', minWidth: 220,
        }}>
        {/* status dot */}
        <span className="w-2 h-2 rounded-full shrink-0"
          style={{ background: error ? 'var(--red)' : selected ? 'var(--green)' : 'var(--amber)' }} />
        <span className="flex-1 text-left truncate">
          {loading ? t('connecting')
            : error ? t('serviceUnreachable')
            : selected ? selected.name
            : t('selectAgent')}
        </span>
        {selected && (
          <span className="text-[8.5px] font-bold tracking-wider uppercase px-1.5 py-0.5 rounded shrink-0"
            style={{ background: 'rgba(188,59,51,0.10)', color: 'var(--gold)' }}>
            {selected.type}
          </span>
        )}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="2.5"
          style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 rounded-xl shadow-xl overflow-hidden z-50 w-[300px] max-h-[340px] overflow-y-auto animate-fade-up"
            style={{ background: 'rgba(250,246,236,0.98)', border: '1px solid rgba(188,59,51,0.2)', backdropFilter: 'blur(20px)' }}>
            {error ? (
              <p className="px-3 py-3 text-[11.5px]" style={{ color: 'var(--red)' }}>{error}</p>
            ) : all.length === 0 ? (
              <p className="px-3 py-3 text-[11.5px]" style={{ color: 'var(--text-dim)' }}>
                {t('noAgents')}
              </p>
            ) : (
              <div className="pb-1.5">
                <Group label={t('agents')} items={agents} type="agent" />
                <Group label={t('collections')} items={collections} type="collection" />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
