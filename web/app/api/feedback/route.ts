import { proxyWorkspace } from '@/lib/proxy-workspace';
export async function POST(request: Request) { return proxyWorkspace(request, '/feedback', 'POST', 8 * 1024); }
