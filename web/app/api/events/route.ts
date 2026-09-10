import { proxyWorkspace } from '@/lib/proxy-workspace';
export async function POST(request: Request) { return proxyWorkspace(request, '/events', 'POST', 1024); }
