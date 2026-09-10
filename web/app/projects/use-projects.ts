'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { FontProject, ProjectListResponse, ProjectPayload, ProjectUpdate } from '@/lib/projects';

export type ProjectSaveState = 'idle' | 'loading' | 'saving' | 'saved' | 'conflict' | 'error';

export interface ProjectClientState {
  projects: FontProject[];
  activeProject: FontProject | null;
  status: ProjectSaveState;
  message: string | null;
}

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null) as T | { error?: { message?: string } } | null;
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'error' in payload ? payload.error?.message : null;
    throw new Error(message ?? `Project request failed (${response.status}).`);
  }
  return payload as T;
}

export function useProjectClient() {
  const [state, setState] = useState<ProjectClientState>({ projects: [], activeProject: null, status: 'idle', message: null });
  const listRequestSeq = useRef(0);
  const mutationSeq = useRef(0);

  const refreshProjects = useCallback(async () => {
    const requestId = ++listRequestSeq.current;
    setState((previous) => ({ ...previous, status: 'loading', message: null }));
    try {
      const data = await readJson<ProjectListResponse>(await fetch('/api/projects', { cache: 'no-store' }));
      if (requestId !== listRequestSeq.current) return;
      setState((previous) => ({ ...previous, projects: Array.isArray(data.projects) ? data.projects : [], status: 'idle', message: null }));
    } catch (err) {
      if (requestId !== listRequestSeq.current) return;
      setState((previous) => ({ ...previous, status: 'error', message: err instanceof Error ? err.message : 'Could not load projects.' }));
    }
  }, []);

  useEffect(() => { void refreshProjects(); }, [refreshProjects]);

  const createProject = useCallback(async (payload: ProjectPayload) => {
    const requestId = ++mutationSeq.current;
    setState((previous) => ({ ...previous, status: 'saving', message: 'Creating project…' }));
    try {
      const project = await readJson<FontProject>(await fetch('/api/projects', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      }));
      if (requestId !== mutationSeq.current) return null;
      setState((previous) => ({ ...previous, activeProject: project, projects: [project, ...previous.projects.filter((item) => item.id !== project.id)], status: 'saved', message: 'Project created.' }));
      return project;
    } catch (err) {
      if (requestId === mutationSeq.current) setState((previous) => ({ ...previous, status: 'error', message: err instanceof Error ? err.message : 'Could not create the project.' }));
      return null;
    }
  }, []);

  const openProject = useCallback(async (projectId: string) => {
    if (!projectId) return null;
    const requestId = ++mutationSeq.current;
    setState((previous) => ({ ...previous, status: 'loading', message: 'Opening project…' }));
    try {
      const project = await readJson<FontProject>(await fetch(`/api/projects/${encodeURIComponent(projectId)}`, { cache: 'no-store' }));
      if (requestId !== mutationSeq.current) return null;
      setState((previous) => ({ ...previous, activeProject: project, projects: [project, ...previous.projects.filter((item) => item.id !== project.id)], status: 'idle', message: 'Project opened.' }));
      return project;
    } catch (err) {
      if (requestId === mutationSeq.current) setState((previous) => ({ ...previous, status: 'error', message: err instanceof Error ? err.message : 'Could not open the project.' }));
      return null;
    }
  }, []);

  const saveProject = useCallback(async (project: FontProject, payload: ProjectPayload) => {
    const requestId = ++mutationSeq.current;
    setState((previous) => ({ ...previous, status: 'saving', message: 'Saving project…' }));
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(project.id)}`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...payload, revision: project.revision } satisfies ProjectUpdate),
      });
      if (response.status === 409) {
        if (requestId === mutationSeq.current) setState((previous) => ({ ...previous, status: 'conflict', message: 'Project changed in another tab. Open the latest version before saving again.' }));
        return null;
      }
      const saved = await readJson<FontProject>(response);
      if (requestId !== mutationSeq.current) return null;
      setState((previous) => ({ ...previous, activeProject: saved, projects: [saved, ...previous.projects.filter((item) => item.id !== saved.id)], status: 'saved', message: 'Project saved.' }));
      return saved;
    } catch (err) {
      if (requestId === mutationSeq.current) setState((previous) => ({ ...previous, status: 'error', message: err instanceof Error ? err.message : 'Could not save the project.' }));
      return null;
    }
  }, []);

  const deleteProject = useCallback(async (projectId: string) => {
    const requestId = ++mutationSeq.current;
    setState((previous) => ({ ...previous, status: 'loading', message: 'Deleting project…' }));
    try {
      await readJson<{ ok: true }>(await fetch(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' }));
      if (requestId !== mutationSeq.current) return false;
      setState((previous) => ({ ...previous, activeProject: previous.activeProject?.id === projectId ? null : previous.activeProject, projects: previous.projects.filter((project) => project.id !== projectId), status: 'idle', message: 'Project deleted.' }));
      return true;
    } catch (err) {
      if (requestId === mutationSeq.current) setState((previous) => ({ ...previous, status: 'error', message: err instanceof Error ? err.message : 'Could not delete the project.' }));
      return false;
    }
  }, []);

  const setActiveProject = useCallback((project: FontProject | null) => {
    mutationSeq.current += 1;
    setState((previous) => ({ ...previous, activeProject: project, status: 'idle', message: project ? 'Project opened.' : null }));
  }, []);

  const markDirty = useCallback(() => setState((previous) => previous.status === 'saving' ? previous : ({ ...previous, status: 'idle', message: previous.activeProject ? 'Unsaved changes.' : previous.message })), []);

  return { ...state, refreshProjects, createProject, openProject, saveProject, deleteProject, setActiveProject, markDirty };
}
