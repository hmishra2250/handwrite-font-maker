import { proxyWorkspace } from '@/lib/proxy-workspace';
export async function GET(request: Request) { return proxyWorkspace(request, '/projects', 'GET'); }
export async function POST(request: Request) { return proxyWorkspace(request, '/projects', 'POST'); }
