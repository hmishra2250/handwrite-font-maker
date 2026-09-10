'use client';

import type { FontProject } from '@/lib/projects';
import type { ProjectSaveState } from './use-projects';

export function ProjectManager({ projects, activeProject, projectName, status, message, busy = false, onProjectName, onNew, onOpen, onDelete }: {
  projects: FontProject[];
  activeProject: FontProject | null;
  projectName: string;
  status: ProjectSaveState;
  message: string | null;
  busy?: boolean;
  onProjectName: (name: string) => void;
  onNew: () => void;
  onOpen: (projectId: string) => void;
  onDelete: () => void;
}) {
  const retentionDate = activeProject ? new Date(activeProject.retentionExpiresAt).toLocaleDateString() : null;
  return (
    <section className="grid min-w-0 gap-3 rounded-[22px] border border-border bg-surface p-5" aria-label="Saved project controls">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[.08em] text-text-tertiary">Project</p>
          <h3 className="text-lg font-semibold">Save and resume your font</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="secondary-button" onClick={onNew} disabled={busy}>New project</button>
          <button type="button" className="secondary-button" onClick={onDelete} disabled={!activeProject || busy}>Delete project</button>
        </div>
      </div>
      <label className="grid min-w-0 gap-1.5">
        <span className="text-[13px] font-semibold text-text-primary">Project name</span>
        <input className="field" value={projectName} onChange={(event) => onProjectName(event.target.value)} placeholder="My first handwriting font" />
      </label>
      <label className="grid min-w-0 gap-1.5">
        <span className="text-[13px] font-semibold text-text-primary">Open saved project</span>
        <select className="field" value={activeProject?.id ?? ''} onChange={(event) => onOpen(event.target.value)} disabled={busy}>
          <option value="">Choose a saved project…</option>
          {(projects ?? []).map((project) => <option key={project.id} value={project.id}>{project.name} · rev {project.revision}</option>)}
        </select>
      </label>
      <p className="text-xs text-text-tertiary" role="status">
        {status === 'saving' ? 'Saving…' : status === 'conflict' ? 'Save conflict.' : status === 'error' ? 'Project error.' : activeProject ? `Autosaves to revision ${activeProject.revision}.` : 'Create or open a project to enable autosave.'}
        {message ? ` ${message}` : ''}
      </p>
      <p className="text-xs text-text-tertiary">
        Saved projects keep up to 10 projects per account and expire after 7 days of inactivity{retentionDate ? ` (current project: ${retentionDate})` : ''}.
      </p>
    </section>
  );
}
