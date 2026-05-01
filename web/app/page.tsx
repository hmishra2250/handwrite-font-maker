import Image from 'next/image';
import { JOB_RETENTION_HOURS, MAX_UPLOAD_BYTES } from '@/lib/contracts';
import { UploadWorkbench } from './upload-workbench';

const steps = [
  ['01', 'Print the marker template', 'Download the V1 PDF, print at 100 percent scale, and keep the ArUco corners visible.'],
  ['02', 'Photograph the completed sheet', 'Use bright even light, keep the full page in frame, and avoid glare over the QR block.'],
  ['03', 'Upload and build', 'The browser uploads to Supabase Storage, then the Render worker generates installable font files.']
] as const;

export default function Home() {
  const mode = process.env.NEXT_PUBLIC_APP_MODE ?? 'auto';
  return (
    <main className="shell">
      <section className="hero" aria-labelledby="hero-title">
        <div className="heroCopy">
          <p className="eyebrow">Marker Template V1</p>
          <h1 id="hero-title">Turn a photographed handwriting sheet into a test font.</h1>
          <p className="lede">
            A phone-friendly test bench for the marker-based pipeline. Vercel serves this interface, Supabase stores job data and files, and Render runs the native FontForge/potrace worker.
          </p>
          <div className="heroActions">
            <a className="primaryLink" href="/template-v1.pdf" download>Download V1 template</a>
            <a className="secondaryLink" href="/template-v1-preview.png">Preview template</a>
          </div>
          <dl className="facts" aria-label="Upload limits">
            <div><dt>Max photo</dt><dd>{Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB</dd></div>
            <div><dt>Retention</dt><dd>{JOB_RETENTION_HOURS} hours</dd></div>
            <div><dt>Mode</dt><dd>{mode}</dd></div>
          </dl>
        </div>
        <div className="templatePanel" aria-label="Template preview">
          <Image src="/template-v1-preview.png" alt="Preview of the marker handwriting template" width={1240} height={1754} priority />
          <div className="panelCaption">
            <span>Four ArUco corners</span>
            <span>QR layout metadata</span>
          </div>
        </div>
      </section>

      <section className="workflow" aria-label="Workflow steps">
        {steps.map(([number, title, detail]) => (
          <article key={number} className="stepCard">
            <span>{number}</span>
            <h2>{title}</h2>
            <p>{detail}</p>
          </article>
        ))}
      </section>

      <UploadWorkbench />
    </main>
  );
}
