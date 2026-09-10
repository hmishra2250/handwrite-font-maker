import Link from 'next/link';
export const metadata = {
  title: 'Install fonts for Word and PowerPoint | Handwrite Font Maker',
  description: 'Accurate desktop TTF/OTF installation notes for using generated fonts in Microsoft Word and PowerPoint.',
};

const sourceNotes = [
  'Microsoft Office uses fonts installed in the operating system; the browser does not install fonts into Word or PowerPoint.',
  'Microsoft recommends TrueType (.ttf) or OpenType (.otf) fonts for custom Office fonts and embedding; WOFF2 is a web-font format, not the Office install format.',
  'Documents shared with another computer may substitute a default font unless the recipient installs the same font or the document embeds it successfully.',
] as const;

export default function InstallFontsHelp() {
  return (
    <main className="mx-auto w-full max-w-[920px] px-5 pt-12 pb-24 md:px-10">
      <nav className="mb-8 text-sm text-text-secondary"><Link href="/" className="hover:text-text-primary">← Back to capture</Link></nav>
      <span className="mb-5 inline-block rounded-[4px] bg-teal-muted px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[.12em] text-teal">Install help</span>
      <h1 className="text-[clamp(2.2rem,4.5vw,3.6rem)] font-bold leading-none tracking-[-0.045em]">Use a generated TTF/OTF in Word or PowerPoint</h1>
      <p className="mt-5 max-w-[68ch] text-base leading-relaxed text-text-secondary">Download the real generated font file first. There is no one-click browser install: install the font in Windows or macOS, then reopen Office if the font list does not refresh.</p>

      <section className="mt-8 rounded-[22px] border border-border bg-surface p-6">
        <h2 className="text-xl font-semibold">Start with the download bundle</h2>
        <p className="mt-3 text-sm text-text-secondary">After a successful build, download the ZIP bundle and extract it. It contains the TTF/OTF, a character map of the characters actually generated, and installation notes. Install one format first; you do not need both copies of the same font.</p>
        <p className="mt-3 text-sm text-text-secondary">Test a short document using your captured characters. If spacing or size looks wrong, reopen the saved project, adjust the affected character, and rebuild. Reinstall the new export; an already downloaded font does not update itself.</p>
        <p className="mt-3 text-xs text-text-tertiary">Missing characters are not synthesized. Object silhouettes are ornament glyphs assigned to keys, not an automatically readable alphabet. Rights to the font depend on your source material.</p>
      </section>

      <section className="mt-10 grid gap-4 md:grid-cols-2">
        <article className="rounded-[22px] border border-border bg-surface p-6">
          <h2 className="text-xl font-semibold tracking-[-.02em]">Windows</h2>
          <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-text-secondary">
            <li>Download the generated <strong>.ttf</strong> or <strong>.otf</strong> file.</li>
            <li>Open the file and choose <strong>Install</strong>, or right-click it in File Explorer and choose <strong>Install</strong>. Windows Settings also has a Fonts area for installing fonts.</li>
            <li>Close and reopen Word or PowerPoint if the font is not visible.</li>
            <li>Pick the font family name used during generation.</li>
          </ol>
        </article>
        <article className="rounded-[22px] border border-border bg-surface p-6">
          <h2 className="text-xl font-semibold tracking-[-.02em]">macOS</h2>
          <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-text-secondary">
            <li>Download the generated <strong>.ttf</strong> or <strong>.otf</strong> file.</li>
            <li>Open it with <strong>Font Book</strong> and choose <strong>Install</strong>.</li>
            <li>Resolve any Font Book validation warning before relying on the font in Office.</li>
            <li>Restart Word or PowerPoint if the newly installed family does not appear.</li>
          </ol>
        </article>
      </section>

      <section className="mt-6 rounded-[22px] border border-border bg-surface p-6">
        <h2 className="text-xl font-semibold tracking-[-.02em]">Sharing Word and PowerPoint files</h2>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-text-secondary">
          <li>Installable on your computer does not mean installed on someone else’s computer.</li>
          <li>Word and PowerPoint desktop versions can embed some custom fonts, but embedding depends on the font’s embedding rights and the Office version.</li>
          <li>If the document must remain editable on another machine, avoid “embed only characters used” because that can prevent typing new characters later.</li>
          <li>Verify a shared test document on the target Windows or macOS Office version before treating it as portable.</li>
        </ul>
      </section>

      <section className="mt-6 rounded-[22px] border border-border bg-bg p-6">
        <h2 className="text-lg font-semibold tracking-[-.02em]">Source-grounded limits</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-text-secondary">
          {sourceNotes.map((note) => <li key={note}>{note}</li>)}
        </ul>
        <p className="mt-4 text-xs text-text-tertiary">Summarized from docs/research/technology.md, which cites Microsoft Office custom-font installation, Microsoft font embedding guidance, Windows font management, and W3C WOFF2 guidance.</p>
      </section>
    </main>
  );
}
