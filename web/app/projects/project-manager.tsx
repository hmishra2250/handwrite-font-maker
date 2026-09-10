'use client';

import { useState } from 'react';
import type { FontProject } from '@/lib/projects';
import type { ProjectSaveState } from './use-projects';

export function ProjectManager({
  projects,
  activeProject,
  projectName,
  status,
  message,
  busy = false,
  onProjectName,
  onNew,
  onOpen,
  onDelete,
}: {
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
  const [expanded, setExpanded] = useState(false);
  const retentionDate = activeProject
    ? new Date(activeProject.retentionExpiresAt).toLocaleDateString()
    : null;
  const statusText =
    status === 'saving'
      ? 'Saving…'
      : status === 'conflict'
        ? 'Save conflict.'
        : status === 'error'
          ? 'Project error.'
          : activeProject
            ? `Saved rev ${activeProject.revision}`
            : 'Draft';
  return (
    <details
      id="projects"
      className="group rounded-[18px] border border-border bg-surface/90 p-3"
      aria-label="Saved project controls"
      open={expanded}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 outline-none focus-visible:ring-2 focus-visible:ring-teal" onClick={(event) => { event.preventDefault(); setExpanded((value) => !value); }}>
        <span className="min-w-0">
          <span className="font-mono text-[10px] font-semibold uppercase tracking-[.12em] text-text-tertiary">
            Project
          </span>
          <strong className="block truncate text-sm text-text-primary">
            {projectName || 'Untitled font'}
          </strong>
        </span>
        <span className="shrink-0 rounded-full border border-border bg-bg px-2.5 py-1 text-[11px] text-text-tertiary" role="status">
          {statusText}
        </span>
      </summary>
      {expanded && <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_auto]">
        <label className="grid min-w-0 gap-1">
          <span className="text-[11px] font-semibold text-text-tertiary">Project name</span>
          <input
            className="field h-10"
            value={projectName}
            onChange={(event) => onProjectName(event.target.value)}
            placeholder="My first handwriting font"
          />
        </label>
        <label className="grid min-w-0 gap-1">
          <span className="text-[11px] font-semibold text-text-tertiary">
            Open saved project
          </span>
          <select
            className="field h-10"
            value={activeProject?.id ?? ''}
            onChange={(event) => onOpen(event.target.value)}
            disabled={busy}
          >
            <option value="">Choose a saved project…</option>
            {(projects ?? []).map((project) => (
              <option key={project.id} value={project.id}>
                {project.name} · rev {project.revision}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap items-end gap-2 sm:justify-end">
          <button type="button" className="secondary-button h-10" onClick={onNew} disabled={busy}>
            New project
          </button>
          <button
            type="button"
            className="secondary-button h-10"
            onClick={onDelete}
            disabled={!activeProject || busy}
          >
            Delete project
          </button>
        </div>
        <p className="text-xs text-text-tertiary sm:col-span-full">
          {message ? `${message} ` : activeProject ? 'Autosave is on. ' : 'Create or open a project to enable autosave. '}
          Saved projects keep up to 10 projects and expire after 7 days of inactivity
          {retentionDate ? ` (current project: ${retentionDate})` : ''}.
        </p>
      </div>}
    </details>
  );
}
