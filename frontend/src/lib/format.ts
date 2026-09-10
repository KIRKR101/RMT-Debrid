export function formatBytes(bytes: number, decimals = 1) {
	if (!bytes || bytes <= 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
	return `${parseFloat((bytes / 1024 ** unit).toFixed(Math.max(0, decimals)))} ${units[unit]}`;
}

export function formatAdaptiveMb(mb: number) {
	if (!(mb > 0)) return '';
	if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
	if (mb >= 100) return `${mb.toFixed(0)} MB`;
	return `${mb.toFixed(1)} MB`;
}

export function formatMb(value: number) {
	return value > 0 ? `${value.toFixed(value >= 100 ? 0 : 1)} MB` : '—';
}

export function formatDate(value?: string) {
	if (!value) return '';
	const parsed = new Date(value);
	return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString();
}

export function formatDateShort(value?: string) {
	if (!value) return 'N/A';
	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) return 'N/A';
	return parsed.toLocaleDateString(undefined, {
		day: 'numeric',
		month: 'short',
		year: 'numeric'
	});
}

export function formatDateTimeCompact(value?: string) {
	if (!value) return '';
	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) return '';
	return parsed.toLocaleString(undefined, {
		day: '2-digit',
		month: '2-digit',
		year: 'numeric',
		hour: '2-digit',
		minute: '2-digit'
	});
}

export function truncateMiddle(value: string, max = 40) {
	if (value.length <= max) return value;
	const head = Math.ceil((max - 1) / 2);
	const tail = Math.floor((max - 1) / 2);
	return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
}

export function pathLabel(path?: string | null) {
	return path ? path.replaceAll('\\', '/') : '';
}
