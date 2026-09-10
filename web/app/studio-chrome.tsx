'use client';

import Link from 'next/link';

export function StudioBrand() {
  return <Link href="/" className="studio-brand" aria-label="Handwrite Font Maker home">
    <span className="studio-brand-mark" aria-hidden="true">h<span>.</span></span>
    <span>handwrite<span className="studio-brand-caption">FONT STUDIO</span></span>
  </Link>;
}

export function StudioIcon({ name, className = '' }: { name: 'studio' | 'folder' | 'sheet' | 'help' | 'arrow' | 'menu'; className?: string }) {
  const paths = {
    studio: <><path d="m4 16-1 5 5-1L20 8l-4-4L4 16Z" /><path d="m13 7 4 4M4 16l4 4" /></>,
    folder: <path d="M3 7V5h6l2 2h10v13H3V7Z" />,
    sheet: <><path d="M5 3h10l4 4v14H5Z" /><path d="M14 3v5h5M8 12h8M8 16h6" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16h.01" /></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  };
  return <svg className={className} width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function StudioNavigation() {
  return <>
    <nav aria-label="Studio navigation" className="studio-nav">
      <span className="studio-nav-label">WORKSPACE</span>
      <a className="studio-nav-link is-current" href="#capture" aria-current="page"><StudioIcon name="studio" />Font studio</a>
      <a className="studio-nav-link" href="#projects" onClick={() => { const projects = document.getElementById('projects'); if (projects instanceof HTMLDetailsElement && !projects.open) projects.querySelector('summary')?.click(); }}><StudioIcon name="folder" />Saved projects</a>
      <span className="studio-nav-label mt-7">RESOURCES</span>
      <details className="studio-templates">
        <summary className="studio-nav-link"><StudioIcon name="sheet" />Templates<span className="ml-auto text-xs">⌄</span></summary>
        <div className="studio-template-links">
          <a href="/template-markerless.pdf" download>Download markerless A4 <span aria-hidden="true">↗</span></a>
          <a href="/template-v1.pdf" download>Legacy V1 PDF <span aria-hidden="true">↗</span></a>
          <p>Print at 100%. Keep the whole page in your photo.</p>
        </div>
      </details>
      <Link className="studio-nav-link" href="/help/install-fonts"><StudioIcon name="help" />Install your font</Link>
      <Link className="studio-nav-link" href="/pricing"><span className="w-[19px] text-center" aria-hidden="true">$</span>Pricing</Link>
    </nav>
    <div className="studio-sidebar-note"><span className="studio-status-dot" />Private alpha<span>Made for your own kind of letters.</span></div>
  </>;
}
