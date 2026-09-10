import type { FontMetadata, InputPhotoRef, PageCorners } from './contracts';

export type ProjectMode = 'guided' | 'markerless' | 'legacy';
export interface ProjectGlyph {
  char: string;
  inputPhoto: InputPhotoRef;
  baseline: number;
  scale?: number;
  /** Additional advance width, in em units. Applied when rebuilding. */
  spacing?: number;
  width: number;
  height: number;
  foregroundRatio: number;
  filename: string;
}
export interface ProjectSheet {
  inputPhoto: InputPhotoRef;
  corners?: PageCorners;
  cornersConfirmed?: boolean;
}
export interface ProjectPayload {
  name: string;
  font: FontMetadata;
  mode: ProjectMode;
  targetCharacters: string;
  glyphs: ProjectGlyph[];
  sheet?: ProjectSheet | null;
  lastJobId?: string | null;
}
export interface FontProject extends ProjectPayload {
  id: string;
  revision: number;
  createdAt: string;
  updatedAt: string;
  retentionExpiresAt: string;
}
export interface ProjectListResponse { projects: FontProject[] }
export type ProjectUpdate = ProjectPayload & { revision: number };

export function projectObjectUrl(photo: InputPhotoRef): string {
  return `/api/objects/${photo.objectKey.split('/').map(encodeURIComponent).join('/')}`;
}
