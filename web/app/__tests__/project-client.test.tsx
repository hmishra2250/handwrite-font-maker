import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useProjectClient } from '../projects/use-projects';
import type { FontProject, ProjectPayload } from '@/lib/projects';
const payload: ProjectPayload = { name: 'My font', font: { fontName: 'MyFont', familyName: 'My Font', styleName: 'Regular' }, mode: 'guided', targetCharacters: 'ABCDE', glyphs: [] };
const project: FontProject = { ...payload, id: 'proj_test', revision: 1, createdAt: '2026-09-10T00:00:00Z', updatedAt: '2026-09-10T00:00:00Z', retentionExpiresAt: '2026-09-17T00:00:00Z' };
beforeEach(() => { vi.restoreAllMocks(); });
async function setup() {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ projects: [project] }));
  const hook = renderHook(() => useProjectClient());
  await waitFor(() => expect(hook.result.current.projects).toHaveLength(1));
  return { ...hook, fetcher };
}
it('creates and saves with revision, preserving a conflict instead of overwriting', async () => {
  const { result, fetcher } = await setup();
  fetcher.mockResolvedValueOnce(Response.json(project, { status: 201 }));
  await act(async () => { await result.current.createProject(payload); });
  expect(result.current.activeProject?.id).toBe(project.id);
  fetcher.mockResolvedValueOnce(Response.json({ ...project, revision: 2 }));
  await act(async () => { await result.current.saveProject(project, payload); });
  expect(result.current.activeProject?.revision).toBe(2);
  expect(JSON.parse((fetcher.mock.calls.at(-1)?.[1] as RequestInit).body as string).revision).toBe(1);
  fetcher.mockResolvedValueOnce(Response.json({ error: {} }, { status: 409 }));
  await act(async () => { await result.current.saveProject({ ...project, revision: 2 }, payload); });
  expect(result.current.status).toBe('conflict');
  expect(result.current.activeProject?.revision).toBe(2);
});
it('network failure exits saving and keeps the active project', async () => {
  const { result, fetcher } = await setup();
  act(() => result.current.setActiveProject(project));
  fetcher.mockRejectedValueOnce(new Error('Network unavailable'));
  await act(async () => { await result.current.saveProject(project, payload); });
  expect(result.current.status).toBe('error');
  expect(result.current.activeProject?.id).toBe(project.id);
});
it('an old save response cannot replace a newly opened project', async () => {
  const { result, fetcher } = await setup();
  act(() => result.current.setActiveProject(project));
  let resolveSave!: (response: Response) => void;
  fetcher.mockImplementationOnce(() => new Promise(resolve => { resolveSave = resolve; }));
  let saving!: Promise<FontProject | null>;
  act(() => { saving = result.current.saveProject(project, payload); });
  const newer = { ...project, id: 'proj_other', name: 'Other' };
  fetcher.mockResolvedValueOnce(Response.json(newer));
  await act(async () => { await result.current.openProject(newer.id); });
  await act(async () => { resolveSave(Response.json({ ...project, revision: 2 })); await saving; });
  expect(result.current.activeProject?.id).toBe(newer.id);
});
