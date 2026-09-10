import { deploymentMode } from '@/lib/server-auth';
import { SessionGate } from '../session-gate';
import { UploadWorkbench } from '../upload-workbench';

export const dynamic = 'force-dynamic';

export default function MobileCapturePage() {
  const mode = deploymentMode();
  return (
    <SessionGate deploymentMode={mode} surface="mobile">
      <UploadWorkbench allowDelete={mode !== 'local'} presentation="mobile" />
    </SessionGate>
  );
}
