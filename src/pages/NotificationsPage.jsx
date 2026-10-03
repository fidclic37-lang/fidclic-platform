import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Bell, Settings } from 'lucide-react';
import {
  AlertRow, EmptyAlerts, FilterChips, StorePicker, byFilter, categoryOf, ofStore, useNotifications,
} from '../components/NotificationBell';

/**
 * Notifications — every alert of one establishment, at once (user, 2026-10-03:
 * « Voir toutes les notifications de cette boutique » opens the alerts
 * themselves, nothing to look for). Same design and links as the bell's panel;
 * ?store= and ?filter= say which establishment and which chip.
 */
export default function NotificationsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const n = useNotifications();
  const many = n.stores.length > 1;
  const store = params.get('store') || (many ? 'all' : (n.stores[0]?.id || 'all'));
  const filter = ['all', 'unread', 'campagnes', 'clients'].includes(params.get('filter')) ? params.get('filter') : 'all';
  const set = (k, v, dflt) => setParams((p) => { if (v === dflt) p.delete(k); else p.set(k, v); return p; }, { replace: true });

  const scoped = useMemo(() => ofStore(n.alerts, store), [n.alerts, store]);
  const counts = useMemo(() => ({
    all: scoped.length,
    unread: scoped.filter(n.isUnread).length,
    campagnes: scoped.filter((a) => categoryOf(a) === 'campagnes').length,
    clients: scoped.filter((a) => categoryOf(a) === 'clients').length,
  }), [scoped, n.isUnread]);
  const shown = byFilter(scoped, filter, n.isUnread);
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 60000); return () => clearInterval(t); }, []);   // « Il y a … » stays true

  const go = (a, href) => { n.markRead([a]); navigate(href); };

  return (
    <div className="ntf mx-auto max-w-[920px]">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EAF1FF] text-[#2F6BFF]"><Bell size={20} /></span>
          <div>
            <h1 className="text-[24px] font-bold text-[#0B1C3F]">Notifications</h1>
            <p className="text-[13px] text-[#64748B]">Toutes les alertes de votre boutique, et ce qu’il y a à faire pour chacune.</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {counts.unread > 0 && (
            <button type="button" onClick={() => n.markRead(scoped)} className="text-[13px] font-semibold text-[#2F6BFF] hover:underline">
              Tout marquer comme lu
            </button>
          )}
          <button type="button" onClick={() => navigate('/dashboard/parametres/notifications')}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-[#E6EEFB] bg-white px-3 py-2 text-[13px] font-semibold text-[#334155] hover:border-[#C9D8F5]">
            <Settings size={15} /> Réglages
          </button>
        </div>
      </header>

      <section className="rounded-2xl border border-[#E6EEFB] bg-white p-5 shadow-[0_18px_40px_-34px_rgba(11,28,63,.45)]">
        <div className="mb-4 grid gap-3 md:grid-cols-[minmax(0,340px)_1fr] md:items-center">
          <StorePicker stores={n.stores} value={store} onChange={(v) => { set('store', v, many ? 'all' : (n.stores[0]?.id || 'all')); set('filter', 'all', 'all'); }}
                       logo={n.logo} accountName={n.accountName} />
          <div className="md:justify-self-end"><FilterChips value={filter} onChange={(v) => set('filter', v, 'all')} counts={counts} /></div>
        </div>
        {n.loading && n.alerts.length === 0 ? (
          <div key="loading" className="py-12 text-center text-[13px] text-[#64748B]">Chargement…</div>
        ) : shown.length === 0 ? <EmptyAlerts /> : (
          <div>
            {shown.map((a, i) => (
              <AlertRow key={a.id || i} a={a} unread={n.isUnread(a)} when={n.seenAt(a)} onGo={go} onHide={n.hide} showBranch={store === 'all' && many} wideLabel={many && store !== 'all'} />
            ))}
          </div>
        )}
        {n.hiddenCount > 0 && (
          <p className="mt-3 text-center text-[12px] text-[#64748B]">
            <button type="button" onClick={n.showHidden} className="font-semibold text-[#2F6BFF] hover:underline">
              Réafficher {n.hiddenCount} alerte{n.hiddenCount > 1 ? 's' : ''} masquée{n.hiddenCount > 1 ? 's' : ''}
            </button>
          </p>
        )}
      </section>
    </div>
  );
}
