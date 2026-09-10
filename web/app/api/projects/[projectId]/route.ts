import { proxyWorkspace } from '@/lib/proxy-workspace';
type Context = { params: Promise<{ projectId: string }> };
async function path(context: Context) { return `/projects/${encodeURIComponent((await context.params).projectId)}`; }
export async function GET(request: Request, context: Context) { return proxyWorkspace(request, await path(context), 'GET'); }
export async function PUT(request: Request, context: Context) { return proxyWorkspace(request, await path(context), 'PUT'); }
export async function DELETE(request: Request, context: Context) { return proxyWorkspace(request, await path(context), 'DELETE'); }
