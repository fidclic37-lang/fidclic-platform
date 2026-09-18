import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import SocialAuthButtons, { routeAfterAuth } from '../components/SocialAuthButtons';

const LoginPage = () => {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [formData, setFormData] = useState({ email: '', password: '' });
  const [error, setError] = useState('');
  const [showForgot, setShowForgot] = useState(false);
  const [resetEmail, setResetEmail] = useState('');
  const [resetSent, setResetSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const res = await login(formData);
      // An owner who never finished step 2 goes back to it, everyone else to their home.
      routeAfterAuth(navigate, res);
    } catch (err) {
      // The backend explains OAuth-only accounts ("utilisez le bouton Google") —
      // surface that; keep the generic message for a plain wrong password.
      const detail = err?.response?.data?.detail;
      setError(detail && detail !== 'Incorrect credentials' ? detail : t('auth.invalid_credentials'));
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7] flex items-center justify-center p-4">
      <div className="bg-white p-8 rounded-3xl shadow-sm border border-[#E7E5E4] w-full max-w-md">
        <div className="text-center mb-8">
          <Link to="/" className="font-['Cormorant_Garamond'] text-3xl font-bold ft-gradient-text">FidéliTour</Link>
          <h2 className="text-2xl font-bold text-[#1C1917] mt-6">{t('auth.login_title')}</h2>
        </div>

        {error && <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('auth.email')}</label>
            <input required type="email" className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.email} onChange={e => setFormData({...formData, email: e.target.value})} />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1 text-[#57534E]">{t('auth.password')}</label>
            <input required type="password" className="w-full border border-[#E7E5E4] rounded-lg p-3 focus:ring-[#B85C38]/20 focus:border-[#B85C38]" value={formData.password} onChange={e => setFormData({...formData, password: e.target.value})} />
          </div>
          {/* Forgot password — honest v1. Email-based reset needs a mail
              provider (S3 backlog); until then this panel routes each kind of
              user to the recovery path that ALREADY works, instead of a dead
              link or a fake "check your inbox". */}
          <div className="text-right">
            <button type="button" onClick={() => setShowForgot(!showForgot)}
                    className="text-xs font-medium text-[#B85C38] hover:underline">
              Mot de passe oublié ?
            </button>
          </div>
          {showForgot && (
            <div className="rounded-xl border p-3 text-xs space-y-2"
                 style={{ borderColor: '#EFE2D4', background: '#FBF6EE', color: '#57534E' }}>
              <div>
                <span className="font-semibold text-[#1C1917]">Employé d'un cabinet ?</span>{' '}
                Demandez à votre expert-comptable : page Équipe → « Réinitialiser MDP ».
                Vous recevrez un mot de passe temporaire à changer à la connexion.
              </div>
              <div>
                <span className="font-semibold text-[#1C1917]">Employé d'un commerce ?</span>{' '}
                Votre gérant peut recréer votre accès depuis ses Paramètres.
              </div>
              <div>
                <span className="font-semibold text-[#1C1917]">Gérant ou expert-comptable ?</span>{' '}
                Recevez un lien de réinitialisation par email (valable 30 min) :
                {resetSent ? (
                  <div key="reset-sent" className="mt-1.5 font-semibold" style={{ color: '#2F7A52' }}>
                    ✓ Si un compte existe pour cette adresse, l'email est parti — vérifiez
                    votre boîte (et les spams).
                  </div>
                ) : (
                  <div className="flex gap-1.5 mt-1.5">
                    <input type="email" value={resetEmail}
                           onChange={(e) => setResetEmail(e.target.value)}
                           placeholder="votre@email.fr"
                           className="flex-1 border border-[#E7E5E4] rounded-lg px-2 py-1.5 text-xs" />
                    <button type="button"
                            disabled={!resetEmail.includes('@')}
                            onClick={async () => {
                              try {
                                const api = (await import('../lib/api')).default;
                                await api.post('/auth/forgot-password', { email: resetEmail });
                              } catch (e) { /* neutral by design */ }
                              setResetSent(true);
                            }}
                            className="px-3 py-1.5 rounded-lg text-white text-xs font-semibold disabled:opacity-40"
                            style={{ background: '#B85C38' }}>
                      Envoyer
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          <button type="submit" className="w-full bg-[#B85C38] text-white py-3 rounded-full font-medium hover:bg-[#9C4E2F] transition-colors mt-6">
            {t('auth.login_button')}
          </button>
        </form>

        <div className="mt-5">
          <SocialAuthButtons onError={setError} />
        </div>

        <div className="mt-6 pt-6 border-t border-[#E7E5E4] text-center">
          <p className="text-[#57534E] text-sm mb-2">{t('auth.no_account')}</p>
          <Link
            to="/register"
            className="inline-flex items-center justify-center gap-2 w-full text-white px-5 py-3 rounded-full text-sm font-semibold transition-all hover:-translate-y-0.5"
            style={{ background: 'linear-gradient(135deg, #B85C38 0%, #E8917C 100%)', boxShadow: '0 6px 18px -6px rgba(184,92,56,0.55)' }}
          >
            ✨ {t('auth.sign_up')}
          </Link>
        </div>
      </div>
    </div>
  );
};
export default LoginPage;
