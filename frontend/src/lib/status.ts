export type StatusKind = 'success' | 'info' | 'warning' | 'destructive' | 'muted';

const DOWNLOAD_SUCCESS = new Set(['completed', 'downloaded', 'added_to_rd']);
const DOWNLOAD_ERROR = new Set(['failed', 'rd_error', 'error', 'magnet_error', 'virus', 'dead']);
const DOWNLOAD_WARNING = new Set(['paused']);
const DOWNLOAD_MUTED = new Set(['cancelled']);
const INFO_STATUSES = new Set(['downloading', 'rd_downloading', 'processing_torrent']);

/** Map any download / RD torrent status to a neutral semantic kind. */
export function statusKind(status: string): StatusKind {
	if (DOWNLOAD_SUCCESS.has(status)) return 'success';
	if (DOWNLOAD_ERROR.has(status)) return 'destructive';
	if (DOWNLOAD_WARNING.has(status)) return 'warning';
	if (DOWNLOAD_MUTED.has(status)) return 'muted';
	if (INFO_STATUSES.has(status)) return 'info';
	return 'info';
}

const LABELS: Record<string, string> = {
	processing_torrent: 'processing',
	waiting_rd: 'queued',
	rd_downloading: 'RD downloading',
	unrestricting: 'preparing files',
	selecting_files: 'select files',
	added_to_rd: 'added to RD'
};

export function statusLabel(value: string) {
	return LABELS[value] ?? value.replaceAll('_', ' ');
}

export function isTerminalStatus(status: string) {
	return ['completed', 'added_to_rd', 'failed', 'cancelled', 'rd_error'].includes(status);
}
