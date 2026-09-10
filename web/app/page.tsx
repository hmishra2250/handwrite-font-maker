import { deploymentMode } from '@/lib/server-auth';
import { SessionGate } from './session-gate';
import { UploadWorkbench } from './upload-workbench';
import { FeedbackPanel } from './feedback-panel';

export const dynamic = 'force-dynamic';

export default function Home() {
  const mode = deploymentMode();
  return (
    <SessionGate deploymentMode={mode}>
      <UploadWorkbench allowDelete={mode !== 'local'} />
      <details className="studio-feedback">
        <summary>Help shape Handwrite <span>Share feedback or report a problem ↗</span></summary>
        <FeedbackPanel />
      </details>
    </SessionGate>
  );
}
