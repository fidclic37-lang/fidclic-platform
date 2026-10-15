/**
 * CatalogManager — owner-facing editor for the product / service catalog
 * that staff pick from on the scan page.
 *
 * Designed as a Settings section, not a wizard step (the owner can come
 * back and edit anytime). Layout: name + price + category per row, plus
 * an "+ Ajouter" button to add a row and a "Enregistrer" button to commit
 * all rows at once with a single PUT /api/owner/catalog call.
 *
 * The server assigns UUIDs to new rows, so the IDs are stable across
 * edits and visit records can reference items by ID forever.
 */
import React, { useEffect, useState, useRef } from 'react';
import { Plus, Trash2, Save, Camera } from 'lucide-react';
import { ownerAPI } from '../lib/api';
import { photoForUpload } from '../lib/photoForUpload';

const blankRow = () => ({ id: null, name: '', price: '', category: '' });

export default function CatalogManager() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [error, setError] = useState('');
  // OCR menu-photo upload state
  const [scanning, setScanning] = useState(false);
  const [scanInfo, setScanInfo] = useState('');
  const fileInputRef = useRef(null);

  useEffect(() => {
    let alive = true;
    ownerAPI.getCatalog?.()
      .then((r) => {
        if (!alive) return;
        const list = Array.isArray(r?.data?.items) ? r.data.items : [];
        // Seed with one blank row so the table is never empty.
        setItems(list.length > 0 ? list.map(it => ({ ...it, price: String(it.price ?? '') })) : [blankRow()]);
      })
      .catch((e) => { if (alive) setError(e?.response?.data?.detail || e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const updateRow = (i, field, value) => {
    setItems((prev) => prev.map((row, idx) => idx === i ? { ...row, [field]: value } : row));
  };
  const addRow = () => setItems((prev) => [...prev, blankRow()]);
  const deleteRow = (i) => {
    setItems((prev) => {
      const next = prev.filter((_, idx) => idx !== i);
      return next.length > 0 ? next : [blankRow()];
    });
  };

  // Photo → menu items. Reads the chosen file as base64, posts it to
  // the vision endpoint, and PRE-FILLS the catalog rows with what the
  // model extracted. The owner reviews and clicks "Enregistrer" to
  // persist — nothing saves automatically, so a misread doesn't ship.
  const handleMenuPhoto = async (file) => {
    if (!file) return;
    setScanning(true);
    setError('');
    setScanInfo('');
    try {
      const { dataUrl, mime } = await photoForUpload(file);   // light enough to send; HEIC converted server-side
      const r = await ownerAPI.parseMenuFromPhoto?.(dataUrl, mime, 'fr');
      const parsed = Array.isArray(r?.data?.items) ? r.data.items : [];
      if (parsed.length === 0) {
        setScanInfo("Aucun article détecté sur la photo. Essayez une photo plus nette ou ajoutez les lignes manuellement.");
        return;
      }
      // Append to existing items (preserve any rows the owner already
      // typed) rather than wiping them.
      setItems((prev) => {
        const meaningful = prev.filter((r) => (r.name || '').trim());
        const newRows = parsed.map((it) => ({
          id: null,
          name: String(it.name || '').trim(),
          price: String(it.price ?? ''),
          category: it.category || '',
        }));
        const combined = [...meaningful, ...newRows];
        return combined.length > 0 ? combined : [blankRow()];
      });
      setScanInfo(`✓ ${parsed.length} article${parsed.length > 1 ? 's' : ''} détecté${parsed.length > 1 ? 's' : ''}. Vérifiez la liste ci-dessus puis cliquez sur "Enregistrer".`);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = (typeof detail === 'string' && detail)
        || (detail && detail.message)
        || e.message
        || "Échec de l'analyse de la photo.";
      setError(msg);
    } finally {
      setScanning(false);
      // Reset the input so picking the same file again re-fires onChange.
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      // Skip rows where name is empty — they're scaffolding, not real items.
      const cleaned = items
        .filter((r) => (r.name || '').trim())
        .map((r) => ({
          id: r.id || undefined,
          name: r.name.trim(),
          price: Number(String(r.price).replace(',', '.')) || 0,
          category: (r.category || '').trim() || null,
        }));
      const r = await ownerAPI.putCatalog?.(cleaned);
      const list = Array.isArray(r?.data?.items) ? r.data.items : [];
      setItems(list.map((it) => ({ ...it, price: String(it.price ?? '') })));
      setSavedAt(new Date());
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Erreur d\'enregistrement');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div key="loading" style={{ padding: 24, textAlign: 'center', color: '#8D857D' }}>
        Chargement du catalogue…
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--flc-card, #FFFFFF)', borderRadius: 12, border: '1px solid var(--flc-line, #E9E5E0)', padding: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, marginBottom: 6 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: '#171412' }}>
          🧾 Catalogue produits &amp; services
        </h3>
        {savedAt && (
          <span style={{ fontSize: 11, color: '#4F7A36' }}>
            ✓ Enregistré à {savedAt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
      <p style={{ margin: '0 0 14px', fontSize: 12.5, color: '#57504A', lineHeight: 1.5 }}>
        Listez ici tout ce que vous vendez avec son prix. Lors du scan,
        votre équipe sélectionnera les articles du panier dans cette
        liste — pas de saisie manuelle de montant, et les rapports
        analytiques (panier moyen, chiffre d'affaires, top produits)
        se rempliront automatiquement.
      </p>

      {/* Header row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '2fr 1fr 1.2fr 36px',
        gap: 8, alignItems: 'center', marginBottom: 6,
        fontSize: 10.5, letterSpacing: '0.08em', textTransform: 'uppercase',
        color: '#8D857D', fontWeight: 600,
      }}>
        <span>Nom du produit / service</span>
        <span>Prix (€)</span>
        <span>Catégorie (optionnel)</span>
        <span></span>
      </div>

      {/* Rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((row, i) => (
          <div key={row.id || `new-${i}`} style={{
            display: 'grid',
            gridTemplateColumns: '2fr 1fr 1.2fr 36px',
            gap: 8, alignItems: 'center',
          }}>
            <input
              type="text"
              value={row.name}
              onChange={(e) => updateRow(i, 'name', e.target.value)}
              placeholder="Ex: Café crème"
              style={{ padding: '7px 10px', border: '1px solid var(--flc-line, #E9E5E0)', borderRadius: 8, fontSize: 13, fontFamily: 'inherit' }}
            />
            <input
              type="text"
              inputMode="decimal"
              value={row.price}
              onChange={(e) => updateRow(i, 'price', e.target.value)}
              placeholder="2,50"
              style={{ padding: '7px 10px', border: '1px solid var(--flc-line, #E9E5E0)', borderRadius: 8, fontSize: 13, fontFamily: 'inherit', fontVariantNumeric: 'tabular-nums' }}
            />
            <input
              type="text"
              value={row.category || ''}
              onChange={(e) => updateRow(i, 'category', e.target.value)}
              placeholder="Boisson"
              style={{ padding: '7px 10px', border: '1px solid var(--flc-line, #E9E5E0)', borderRadius: 8, fontSize: 13, fontFamily: 'inherit' }}
            />
            <button
              type="button"
              onClick={() => deleteRow(i)}
              aria-label="Supprimer cette ligne"
              title="Supprimer"
              style={{
                width: 36, height: 36, borderRadius: 8,
                border: '1px solid var(--flc-line, #E9E5E0)', background: 'var(--flc-card, #FFFFFF)', cursor: 'pointer',
                display: 'grid', placeItems: 'center', color: '#B85C38',
              }}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={addRow}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 8,
            border: '1px solid var(--flc-line, #E9E5E0)', background: 'var(--flc-card, #FFFFFF)',
            cursor: 'pointer', fontSize: 12.5, fontWeight: 500, color: '#171412',
            fontFamily: 'inherit',
          }}
        >
          <Plus size={14} /> Ajouter une ligne
        </button>

        {/* OCR menu upload — single button that opens the camera on
            mobile and a file picker on desktop. Image is sent to the
            vision LLM and parsed items are pre-filled into the table
            above for the owner to review before saving. */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          onChange={(e) => handleMenuPhoto(e.target.files?.[0])}
          style={{ display: 'none' }}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={scanning}
          title="Prendre une photo de votre menu pour le scanner avec l'IA"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 8,
            border: '1px solid #C9B6E2', background: '#F4ECFA',
            cursor: scanning ? 'wait' : 'pointer',
            fontSize: 12.5, fontWeight: 500, color: '#5B3FAB',
            fontFamily: 'inherit',
          }}
        >
          <Camera size={14} />
          {scanning ? 'Analyse en cours…' : 'Importer depuis une photo du menu'}
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 8,
            border: 'none', background: saving ? '#B85C3855' : '#B85C38',
            color: 'white', cursor: saving ? 'wait' : 'pointer',
            fontSize: 12.5, fontWeight: 600, fontFamily: 'inherit',
            marginLeft: 'auto',
          }}
        >
          <Save size={14} /> {saving ? 'Enregistrement…' : 'Enregistrer le catalogue'}
        </button>
      </div>

      {error && (
        <div style={{
          marginTop: 12, padding: '8px 12px', borderRadius: 8,
          background: 'color-mix(in srgb, var(--flc-accent, #C73E2C) 12%, var(--flc-card, #FFFFFF))', color: 'var(--flc-accent-deep, #7A2E20)', fontSize: 12,
        }}>
          ⚠ {error}
        </div>
      )}
      {scanInfo && !error && (
        <div style={{
          marginTop: 12, padding: '8px 12px', borderRadius: 8,
          background: '#E7F5E5', color: '#1E5A2A', fontSize: 12,
        }}>
          {scanInfo}
        </div>
      )}
    </div>
  );
}
