import type { InputPhotoRef } from './contracts';

export interface CaptureCandidate {
  id: string;
  label: string;
  maskDataUrl: string;
  svgDataUrl: string;
  width: number;
  height: number;
  method: string;
  polarity?: string;
  warnings: string[];
}
export interface CaptureCandidatesResponse {
  candidates: CaptureCandidate[];
  failures: { method: string; message: string }[];
  stage: 'ink' | 'objects';
}
export interface CaptureCandidatesRequest {
  inputPhoto: InputPhotoRef;
  rectangle: [number, number, number, number];
  stage: 'ink' | 'objects';
  context?: {
    character: string; baseline: number; threshold: number; invert: boolean;
    inkMaskMethod: string; foregroundMethod: string; foregroundStyle: string;
  };
}
