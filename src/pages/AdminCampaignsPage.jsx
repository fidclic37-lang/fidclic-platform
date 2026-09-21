import React, { useEffect, useState } from 'react';
import { adminAPI } from '../lib/api';
import {
  Megaphone, Send, Users, AlertCircle, CheckCircle, Mail, Search,
  Radio, Zap, ArrowUpRight,
} from 'lucide-react';
import { PageHeader, C as C_PS } from '../components/PageShell';

// --------------------------------------------------------------
// Three tabs:
//   1. To a specific business (owner) — original flow
//   2. Broadcast to end-customers across tenants, under admin's chosen name
//   3. Upgrade-plan requests inbox
// --------------------------------------------------------------

const AdminCampaignsPage = () => {
  const [tab, setTab] = useState('business'); // 'business' | 'broadcast' | 'upgrades'

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Outbound"
        title="Campaigns"
        description="Messages to business owners, broadcasts to end-customers, and plan-upgrade requests — all in one place."
        role="super_admin"
      />

      <div className="flex gap-2 border-b border-[#E7E5E4]">
        {[
          { key: 'business', label: 'To a Business Owner', icon: Mail },
          { key: 'broadcast', label: 'Broadcast to End-Customers', icon: Radio },
          { key: 'upgrades', label: 'Upgrade Requests', icon: ArrowUpRight },
        ].map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 -mb-px border-b-2 text-sm font-medium inline-flex items-center gap-2 ${
                active
                  ? 'border-[#B85C38] text-[#B85C38]'
                  : 'border-transparent text-[#57534E] hover:text-[#1C1917]'
              }`}
            >
              <Icon size={16} />
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === 'business' && <BusinessCampaignSection />}
      {tab === 'broadcast' && <BroadcastSection />}
      {tab === 'upgrades' && <UpgradeRequestsSection />}
    </div>
  );
};

// --------------------------------------------------------------
// Original: send a message to a single business owner
// --------------------------------------------------------------
const BusinessCampaignSection = () => {
  const [tenants, setTenants] = useState([]);
  const [campaignHistory, setCampaignHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedTenant, setSelectedTenant] = useState(null);
  const [isComposing, setIsComposing] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [planFilter, setPlanFilter] = useState('');
  const [sectorFilter, setSectorFilter] = useState('');
  const [deptFilter, setDeptFilter] = useState('');
  const [campaignForm, setCampaignForm] = useState({ subject: '', body: '' });
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const tenantRes = await adminAPI.getTenants();
      setTenants(tenantRes.data || []);
    } catch (error) {
      setToast({ type: 'error', message: 'Failed to load businesses' });
    } finally {
      setLoading(false);
    }
  };

  const filteredTenants = tenants.filter((t) => {
    const q = searchTerm.trim().toLowerCase();
    const matchesSearch = !q ||
      (t.name || '').toLowerCase().includes(q) ||
      (t.slug || '').toLowerCase().includes(q);
    const matchesPlan = !planFilter || (t.plan || '').toLowerCase() === planFilter.toLowerCase();
    const matchesSector = !sectorFilter ||
      (t.sector || '').toLowerCase().includes(sectorFilter.toLowerCase());
    const matchesDept = !deptFilter ||
      String(t.department_code || t.dept_code || '').toLowerCase().includes(deptFilter.toLowerCase());
    return matchesSearch && matchesPlan && matchesSector && matchesDept;
  });

  const uniquePlans = Array.from(new Set(tenants.map((t) => t.plan).filter(Boolean))).sort();
  const uniqueSectors = Array.from(new Set(tenants.map((t) => t.sector).filter(Boolean))).sort();

  const handleSelectTenant = (tenant) => {
    setSelectedTenant(tenant);
    setIsComposing(true);
  };

  const handleSendCampaign = async () => {
    if (!selectedTenant || !campaignForm.subject.trim() || !campaignForm.body.trim()) {
      setToast({ type: 'error', message: 'Please fill in all fields' });
      return;
    }
    try {
      setSubmitting(true);
      await adminAPI.sendBusinessCampaign({
        tenant_id: selectedTenant.id,
        subject: campaignForm.subject,
        body: campaignForm.body,
      });
      setCampaignHistory([
        {
          id: Date.now(),
          tenantName: selectedTenant.name,
          subject: campaignForm.subject,
          sentAt: new Date().toISOString(),
          status: 'sent',
        },
        ...campaignHistory,
      ]);
      setToast({ type: 'success', message: `Campaign sent to ${selectedTenant.name}` });
      setIsComposing(false);
      setSelectedTenant(null);
      setCampaignForm({ subject: '', body: '' });
    } catch (error) {
      setToast({ type: 'error', message: 'Failed to send campaign' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = () => {
    setIsComposing(false);
    setSelectedTenant(null);
    setCampaignForm({ subject: '', body: '' });
  };

  if (loading) return <div className="text-[#57534E]">Loading businesses…</div>;

  return (
    <div className="space-y-8">
      {toast && (
        <div className={`fixed top-4 right-4 p-4 rounded-lg flex items-center gap-2 z-50 ${
          toast.type === 'success' ? 'bg-[#4A5D23] text-white' : 'bg-[#B85C38] text-white'
        }`}>
          {toast.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
          {toast.message}
        </div>
      )}

      {!isComposing ? (
        <div className="bg-white p-8 rounded-lg border border-[#E7E5E4]">
          <h2 className="text-2xl font-bold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond' }}>
            <Users className="inline-block mr-2 w-6 h-6 text-[#B85C38]" />
            Select a Business
          </h2>
          <div className="mb-6 space-y-3">
            <div className="relative">
              <Search className="absolute left-3 top-3 w-5 h-5 text-[#A8A29E]" />
              <input
                type="text"
                placeholder="Search by business name or slug..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 border border-[#E7E5E4] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#B85C38]"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <select
                value={planFilter}
                onChange={(e) => setPlanFilter(e.target.value)}
                className="px-3 py-2 border border-[#E7E5E4] rounded-lg text-sm"
              >
                <option value="">All plans</option>
                {uniquePlans.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
              <select
                value={sectorFilter}
                onChange={(e) => setSectorFilter(e.target.value)}
                className="px-3 py-2 border border-[#E7E5E4] rounded-lg text-sm"
              >
                <option value="">All sectors</option>
                {uniqueSectors.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <input
                type="text"
                value={deptFilter}
                onChange={(e) => setDeptFilter(e.target.value)}
                placeholder="Dept code (e.g. 37)"
                className="px-3 py-2 border border-[#E7E5E4] rounded-lg text-sm"
              />
              <div className="flex items-center justify-between px-3 py-2 border border-[#E7E5E4] rounded-lg text-sm text-[#57534E] bg-[#F3EFE7]">
                <span>{filteredTenants.length} of {tenants.length} matching</span>
                {(searchTerm || planFilter || sectorFilter || deptFilter) && (
                  <button
                    onClick={() => {
                      setSearchTerm('');
                      setPlanFilter('');
                      setSectorFilter('');
                      setDeptFilter('');
                    }}
                    className="text-[#B85C38] font-semibold hover:underline text-xs"
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          </div>
          {filteredTenants.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredTenants.map((tenant) => (
                <div
                  key={tenant.id}
                  className="p-4 border border-[#E7E5E4] rounded-lg hover:border-[#B85C38] hover:shadow-md transition-all cursor-pointer"
                  onClick={() => handleSelectTenant(tenant)}
                >
                  <div className="mb-3">
                    <h3 className="font-semibold text-[#1C1917]">{tenant.name}</h3>
                    <p className="text-sm text-[#A8A29E]">{tenant.slug}</p>
                  </div>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="text-xs text-[#57534E] uppercase font-semibold">Plan</p>
                      <p className="text-sm font-bold text-[#B85C38]">{tenant.plan}</p>
                    </div>
                    <div>
                      <p className="text-xs text-[#57534E] uppercase font-semibold">Customers</p>
                      <p className="text-sm font-bold text-[#1C1917]">{tenant.customer_count || 0}</p>
                    </div>
                  </div>
                  <button className="w-full py-2 bg-[#F3EFE7] hover:bg-[#E7E5E4] text-[#1C1917] rounded-lg font-semibold transition-colors flex items-center justify-center gap-2">
                    <Send className="w-4 h-4" />
                    Send Campaign
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 bg-[#F3EFE7] rounded-lg">
              <p className="text-[#57534E]">No businesses found</p>
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white p-8 rounded-lg border border-[#E7E5E4] max-w-2xl">
          <h2 className="text-2xl font-bold text-[#1C1917] mb-6" style={{ fontFamily: 'Cormorant Garamond' }}>
            <Mail className="inline-block mr-2 w-6 h-6 text-[#B85C38]" />
            Compose — To {selectedTenant?.name}
          </h2>
          <div className="mb-6">
            <label className="block text-sm font-semibold text-[#1C1917] mb-2">Subject</label>
            <input
              type="text"
              value={campaignForm.subject}
              onChange={(e) => setCampaignForm({ ...campaignForm, subject: e.target.value })}
              className="w-full px-4 py-3 border border-[#E7E5E4] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#B85C38]"
            />
          </div>
          <div className="mb-6">
            <label className="block text-sm font-semibold text-[#1C1917] mb-2">Message</label>
            <textarea
              rows="8"
              value={campaignForm.body}
              onChange={(e) => setCampaignForm({ ...campaignForm, body: e.target.value })}
              className="w-full px-4 py-3 border border-[#E7E5E4] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#B85C38] resize-none"
            />
          </div>
          <div className="flex gap-4 justify-end">
            <button
              onClick={handleCancel}
              disabled={submitting}
              className="px-6 py-2.5 border border-[#E7E5E4] text-[#1C1917] rounded-lg font-semibold hover:bg-[#F3EFE7] transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSendCampaign}
              disabled={submitting || !campaignForm.subject.trim() || !campaignForm.body.trim()}
              className="px-6 py-2.5 bg-[#B85C38] text-white rounded-lg font-semibold hover:bg-[#A34D2C] transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              <Send className="w-4 h-4" />
              {submitting ? 'Sending...' : 'Send Campaign'}
            </button>
          </div>
        </div>
      )}

      {campaignHistory.length > 0 && (
        <div className="bg-white p-6 rounded-lg border border-[#E7E5E4]">
          <h3 className="text-xl font-bold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond' }}>
            Recent sends (this session)
          </h3>
          <ul className="text-sm space-y-1">
            {campaignHistory.map((c) => (
              <li key={c.id} className="text-[#57534E]">
                <span className="font-medium text-[#1C1917]">{c.tenantName}</span> — {c.subject}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

// --------------------------------------------------------------
// Broadcast to all end-customers under admin-chosen sender name
// --------------------------------------------------------------
const BroadcastSection = () => {
  const [form, setForm] = useState({
    subject: '',
    body: '',
    sender_name: 'FidClic',
    tier: '',
    sector: '',
    department_code: '',
    acquisition: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState(null);
  const [history, setHistory] = useState([]);
  const [preview, setPreview] = useState(null);  // { count, with_email } | null
  const [previewLoading, setPreviewLoading] = useState(false);

  const fetchHistory = async () => {
    try {
      const res = await adminAPI.listBroadcasts();
      setHistory(res.data?.broadcasts || []);
    } catch (e) { /* ignore */ }
  };
  useEffect(() => { fetchHistory(); }, []);

  // Reset preview whenever a filter changes, so the stale number isn't shown.
  useEffect(() => {
    setPreview(null);
  }, [form.tier, form.sector, form.department_code, form.acquisition]);

  const runPreview = async () => {
    try {
      setPreviewLoading(true);
      const filters = {};
      if (form.tier) filters.tier = form.tier;
      if (form.sector) filters.sector = form.sector;
      if (form.department_code) filters.department_code = form.department_code;
      if (form.acquisition) filters.acquisition = form.acquisition;
      const res = await adminAPI.broadcastPreview(filters);
      setPreview(res.data || { count: 0, with_email: 0 });
    } catch (e) {
      setToast({ type: 'error', message: 'Preview failed: ' + (e?.response?.data?.detail || e?.message) });
    } finally {
      setPreviewLoading(false);
    }
  };

  const send = async () => {
    if (!form.subject.trim() || !form.body.trim() || !form.sender_name.trim()) {
      setToast({ type: 'error', message: 'Sujet, message et nom d\'expéditeur requis.' });
      return;
    }
    if (!window.confirm(`Envoyer à tous les clients finaux correspondant aux filtres ? Ce broadcast est immédiat.`)) return;
    try {
      setSubmitting(true);
      const filters = {};
      if (form.tier) filters.tier = form.tier;
      if (form.sector) filters.sector = form.sector;
      if (form.department_code) filters.department_code = form.department_code;
      if (form.acquisition) filters.acquisition = form.acquisition;
      const res = await adminAPI.broadcast({
        subject: form.subject,
        body: form.body,
        sender_name: form.sender_name,
        filters,
      });
      setToast({ type: 'success', message: `Broadcast envoyé à ${res.data.targeted_count} clients (${res.data.delivered_count} emails délivrés).` });
      setForm({ ...form, subject: '', body: '' });
      fetchHistory();
    } catch (e) {
      setToast({ type: 'error', message: 'Erreur: ' + (e?.response?.data?.detail || e?.message) });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {toast && (
        <div className={`fixed top-4 right-4 p-4 rounded-lg flex items-center gap-2 z-50 ${
          toast.type === 'success' ? 'bg-[#4A5D23] text-white' : 'bg-[#B85C38] text-white'
        }`}>
          {toast.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
          {toast.message}
        </div>
      )}
      <div className="bg-white p-8 rounded-lg border border-[#E7E5E4] max-w-3xl">
        <h2 className="text-2xl font-bold text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond' }}>
          <Radio className="inline mr-2 w-6 h-6 text-[#B85C38]" />
          Broadcast to End-Customers
        </h2>
        <p className="text-sm text-[#57534E] mb-5">
          Message every end-customer in the platform (optionally filtered). Sent under your chosen "from" name.
          Variables supported: <code>{'{first_name}'}</code>, <code>{'{name}'}</code>, <code>{'{tier}'}</code>, <code>{'{business_name}'}</code>, <code>{'{points_to_next_reward}'}</code>.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs font-semibold text-[#57534E] uppercase">Sender name (From)</label>
            <input
              type="text"
              value={form.sender_name}
              onChange={(e) => setForm({ ...form, sender_name: e.target.value })}
              className="w-full mt-1 px-3 py-2 border border-[#E7E5E4] rounded-lg"
            />
          </div>
          <div>
            <label className="text-xs font-semibold text-[#57534E] uppercase">Subject</label>
            <input
              type="text"
              value={form.subject}
              onChange={(e) => setForm({ ...form, subject: e.target.value })}
              className="w-full mt-1 px-3 py-2 border border-[#E7E5E4] rounded-lg"
            />
          </div>
        </div>

        <div className="mb-4">
          <label className="text-xs font-semibold text-[#57534E] uppercase">Message</label>
          <textarea
            rows={6}
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            className="w-full mt-1 px-3 py-2 border border-[#E7E5E4] rounded-lg font-['Manrope']"
            placeholder="Bonjour {first_name}, une actualité importante de {business_name}..."
          />
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <select
            value={form.tier}
            onChange={(e) => setForm({ ...form, tier: e.target.value })}
            className="px-2 py-2 border border-[#E7E5E4] rounded-lg text-sm"
          >
            <option value="">All tiers</option>
            <option value="bronze">Bronze</option>
            <option value="silver">Silver</option>
            <option value="gold">Gold</option>
          </select>
          <input
            type="text"
            value={form.sector}
            onChange={(e) => setForm({ ...form, sector: e.target.value })}
            placeholder="Sector (e.g. restaurant)"
            className="px-2 py-2 border border-[#E7E5E4] rounded-lg text-sm"
          />
          <input
            type="text"
            value={form.department_code}
            onChange={(e) => setForm({ ...form, department_code: e.target.value })}
            placeholder="Dept code (e.g. 37)"
            className="px-2 py-2 border border-[#E7E5E4] rounded-lg text-sm"
          />
          <select
            value={form.acquisition}
            onChange={(e) => setForm({ ...form, acquisition: e.target.value })}
            className="px-2 py-2 border border-[#E7E5E4] rounded-lg text-sm"
          >
            <option value="">Any source</option>
            <option value="qr_store">QR store</option>
            <option value="instagram">Instagram</option>
            <option value="facebook">Facebook</option>
            <option value="tiktok">TikTok</option>
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-3 justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={runPreview}
              disabled={previewLoading}
              className="px-4 py-2 border rounded-lg text-sm font-semibold inline-flex items-center gap-2"
              style={{ borderColor: '#B85C38', color: '#B85C38' }}
            >
              <Search size={14} /> {previewLoading ? 'Previewing…' : 'Preview audience'}
            </button>
            {preview && (
              <div className="text-sm text-[#57534E]">
                <span className="font-bold text-[#B85C38]">{preview.count}</span> customer{preview.count === 1 ? '' : 's'} match
                {' '}— <span className="font-semibold">{preview.with_email}</span> have an email on file
              </div>
            )}
          </div>
          <button
            disabled={submitting}
            onClick={send}
            className="px-6 py-2.5 bg-[#B85C38] text-white rounded-lg font-semibold hover:bg-[#A34D2C] disabled:opacity-50 inline-flex items-center gap-2"
          >
            <Zap size={16} /> {submitting ? 'Sending…' : 'Send Broadcast'}
          </button>
        </div>
      </div>

      {history.length > 0 && (
        <div className="bg-white p-6 rounded-lg border border-[#E7E5E4]">
          <h3 className="text-xl font-bold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond' }}>
            Recent Broadcasts
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-[#E7E5E4] text-[#57534E]">
                  <th className="py-2 px-3">Sent</th>
                  <th className="py-2 px-3">Sender</th>
                  <th className="py-2 px-3">Subject</th>
                  <th className="py-2 px-3 text-right">Targeted</th>
                  <th className="py-2 px-3 text-right">Delivered</th>
                </tr>
              </thead>
              <tbody>
                {history.map((b) => (
                  <tr key={b.id} className="border-b border-[#E7E5E4]">
                    <td className="py-2 px-3 text-[#57534E]">{new Date(b.sent_at).toLocaleString()}</td>
                    <td className="py-2 px-3 font-medium text-[#1C1917]">{b.sender_name}</td>
                    <td className="py-2 px-3 text-[#1C1917]">{b.subject}</td>
                    <td className="py-2 px-3 text-right">{b.targeted_count}</td>
                    <td className="py-2 px-3 text-right">{b.delivered_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

// --------------------------------------------------------------
// Upgrade-plan requests inbox
// --------------------------------------------------------------
const UpgradeRequestsSection = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const fetchRows = async () => {
    try {
      const res = await adminAPI.listUpgradeRequests();
      setRows(res.data?.requests || []);
    } catch (e) { /* ignore */ } finally { setLoading(false); }
  };
  useEffect(() => { fetchRows(); }, []);

  const resolve = async (id, status) => {
    try {
      await adminAPI.resolveUpgradeRequest(id, status);
      fetchRows();
    } catch (e) { alert('Error: ' + (e?.response?.data?.detail || e?.message)); }
  };

  if (loading) return <div className="text-[#57534E]">Loading upgrade requests…</div>;

  return (
    <div className="bg-white p-6 rounded-lg border border-[#E7E5E4]">
      <h2 className="text-2xl font-bold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond' }}>
        <ArrowUpRight className="inline mr-2 text-[#B85C38]" />
        Plan Upgrade Requests
      </h2>
      {rows.length === 0 ? (
        <div className="py-8 text-center text-[#8B8680]">
          No upgrade requests yet. Business owners nearing their plan cap will show up here.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-[#E7E5E4] text-[#57534E]">
                <th className="py-2 px-3">Requested</th>
                <th className="py-2 px-3">Business</th>
                <th className="py-2 px-3">Current</th>
                <th className="py-2 px-3">Requested</th>
                <th className="py-2 px-3">Status</th>
                <th className="py-2 px-3">Note</th>
                <th className="py-2 px-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-[#E7E5E4]">
                  <td className="py-2 px-3 text-[#57534E]">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="py-2 px-3 font-medium text-[#1C1917]">{r.tenant_name}</td>
                  <td className="py-2 px-3">{r.current_plan}</td>
                  <td className="py-2 px-3 font-semibold text-[#B85C38]">{r.requested_plan}</td>
                  <td className="py-2 px-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      r.status === 'pending' ? 'bg-[#F3EFE7] text-[#57534E]' :
                      r.status === 'approved' ? 'bg-[#4A5D23] text-white' :
                      r.status === 'declined' ? 'bg-[#B85C38] text-white' :
                      'bg-[#E7E5E4] text-[#57534E]'
                    }`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-[#57534E] text-xs max-w-xs">{r.message || '—'}</td>
                  <td className="py-2 px-3 text-right">
                    {r.status === 'pending' && (
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => resolve(r.id, 'approved')}
                          className="px-2 py-1 text-xs bg-[#4A5D23] text-white rounded hover:bg-[#3B4A1C]"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => resolve(r.id, 'declined')}
                          className="px-2 py-1 text-xs bg-[#B85C38] text-white rounded hover:bg-[#9C4E2F]"
                        >
                          Decline
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default AdminCampaignsPage;
