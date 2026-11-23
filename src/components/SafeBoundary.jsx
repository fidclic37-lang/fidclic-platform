import React from 'react';

/**
 * Keeps one broken piece from taking the whole page down (user, 2026-11-23:
 * a chart's crash showed « Une erreur d'affichage est survenue » in place of
 * the entire Tableau de bord). Wrapped around a chart or a picker, an error
 * inside it shows `fallback` in its place and the rest of the page stays.
 *
 * It tries again by itself when `resetKey` changes (new data, a new period),
 * and through the « Réessayer » the default fallback offers.
 */
export default class SafeBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
    this.retry = () => this.setState({ failed: false });
  }

  static getDerivedStateFromError() { return { failed: true }; }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error(`[${this.props.name || 'bloc'}] display error, page kept:`, error, info?.componentStack);
  }

  componentDidUpdate(prev) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.retry();
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const { fallback } = this.props;
    if (typeof fallback === 'function') return fallback(this.retry);
    if (fallback !== undefined) return fallback;
    return (
      <div role="alert" className="flex flex-col items-center justify-center gap-2 py-8 text-center">
        <p className="text-[13px] text-[#64748B]">Ce bloc n'a pas pu s'afficher.</p>
        <button type="button" onClick={this.retry}
                className="rounded-lg border border-[#E6EEFB] px-3 py-1.5 text-[12.5px] font-semibold text-[#2F6BFF] hover:bg-[#F5F8FE]">
          Réessayer
        </button>
      </div>
    );
  }
}
