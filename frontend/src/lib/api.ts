export async function apiFetch(path: string, init: RequestInit = {}) {
	const response = await fetch(path, init);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error((data as { detail?: string })?.detail || 'Request failed');
	}
	return data;
}
