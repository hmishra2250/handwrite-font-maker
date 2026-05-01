import { NextResponse } from 'next/server';
import { isLiveMode, retentionExpiry } from '@/lib/contracts';
import { getSupabaseAdmin, storageBucket } from '@/lib/supabase-server';

export async function POST(request: Request, { params }: { params: Promise<{ artifactId: string }> }) {
  const { artifactId } = await params;
  const body = (await request.json().catch(() => ({}))) as { objectKey?: string };
  const objectKey = body.objectKey ?? artifactId;

  if (!isLiveMode()) {
    return NextResponse.json({ url: objectKey.startsWith('/') ? objectKey : `/sample-output/template-v1-synthetic/${objectKey}`, expiresAt: retentionExpiry(1) });
  }

  const supabase = getSupabaseAdmin();
  if (!supabase) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Supabase is not configured.' } }, { status: 500 });
  }
  const { data, error } = await supabase.storage.from(storageBucket()).createSignedUrl(objectKey, 60 * 30);
  if (error || !data?.signedUrl) {
    return NextResponse.json({ error: { code: 'ARTIFACT_PUBLISH_FAILED', message: error?.message ?? 'Could not sign artifact URL.' } }, { status: 500 });
  }
  return NextResponse.json({ url: data.signedUrl, expiresAt: retentionExpiry(0.5) });
}
