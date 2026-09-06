<script lang="ts">
	import { onMount } from 'svelte';
	import {
		CircleAlert,
		Clipboard,
		Box,
		Inbox,
		Link2,
		Loader2,
		Database,
		FolderOpen,
		HardDrive,
		Pause,
		Play,
		RotateCcw,
		RefreshCw,
		Save,
		Search,
		Server,
		Settings,
		Trash2,
		Check,
		X,
		Zap,
		ChevronRight
	} from '@lucide/svelte';

	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Progress } from '$lib/components/ui/progress';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { toast } from 'svelte-sonner';

	type Download = {
		id: string;
		name: string;
		type: string;
		original_link?: string | null;
		status: string;
		progress: number;
		added_time?: number;
		added_time_str: string;
		size_mb: number;
		total_size_mb: number;
		current_file_size_mb: number;
		current_file_name?: string | null;
		speed_mbps: number;
		rd_total_size_bytes: number;
		rd_speed_bps: number;
		error_message?: string | null;
		error_code?: number | null;
		total_files: number;
		completed_files: number;
		output_path?: string | null;
		seeders?: number | null;
		rd_status?: string | null;
		files?: FileEntry[];
	};

	type FileEntry = {
		id?: number;
		name?: string;
		size?: number;
		selected?: number;
		progress?: number;
		speed_mbps?: number;
		status?: string;
	};

	type Account = {
		username: string;
		type: string;
		expiration?: string;
		points: number;
	};

	type SettingsData = {
		download_folder: string;
		max_concurrent_downloads: number;
		rd_api_key_set: boolean;
		rd_api_key_hint: string;
		webhook_url: string;
		webhook_token_set: boolean;
		webhook_events: string[];
	};

	type StorageData = {
		total_bytes: number;
		used_bytes: number;
		free_bytes: number;
		used_percent: number;
		volumes: StorageVolume[];
	};

	type StorageVolume = {
		path: string;
		name: string;
		filesystem: string;
		total_bytes: number;
		used_bytes: number;
		free_bytes: number;
		used_percent: number;
	};

	let downloads = $state<Record<string, Download>>({});
	let account = $state<Account | null>(null);
	let accountError = $state('');
	let accountMenuOpen = $state(false);
	let accountMenuElement = $state<HTMLDivElement | undefined>(undefined);

	let settings = $state<SettingsData>({
		download_folder: '',
		max_concurrent_downloads: 1,
		rd_api_key_set: false,
		rd_api_key_hint: '',
		webhook_url: '',
		webhook_token_set: false,
		webhook_events: ['download.completed']
	});

	let link = $state('');
	let apiKey = $state('');
	let webhookToken = $state('');
	const webhookEventOptions = [
		['download.started', 'Download started'],
		['download.paused', 'Download paused'],
		['download.resumed', 'Download resumed'],
		['download.rd_completed', 'Real-Debrid download finished'],
		['download.completed', 'Local download completed'],
		['download.failed', 'Download failed'],
		['download.cancelled', 'Download cancelled']
	] as const;
	let settingsMessage = $state<{ type: 'success' | 'error'; text: string } | null>(null);
	let storage = $state<StorageData | null>(null);
	let storageError = $state('');
	let refreshingStorage = $state(false);
	let formMessage = $state('');

	let adding = $state(false);
	let saving = $state(false);
	let clearingCompleted = $state(false);
	let initialLoading = $state(true);
	let detailsDialogOpen = $state(false);
	let storageDialogOpen = $state(false);
	let cancelDialogOpen = $state(false);
	let pendingCancelId = $state<string | null>(null);
	let clearCompletedDialogOpen = $state(false);
	let actionInFlight = $state<string | null>(null);
	let expandedDownloads = $state<Record<string, boolean>>({});
	let authenticated = $state(false);
	let authChecked = $state(false);
	let password = $state('');
	let loginError = $state('');
	let loggingIn = $state(false);
	let selectionDialogOpen = $state(false);
	let selectionDownload = $state<Download | null>(null);
	let selectedFileIds = $state<number[]>([]);
	let loadingSelection = $state(false);
	let submittingSelection = $state(false);
	let deleteDialogOpen = $state(false);
	let pendingDeleteId = $state<string | null>(null);
	let deleteLocalFiles = $state(false);
	let copiedLinkId = $state<string | null>(null);
	let copiedPathId = $state<string | null>(null);

	let socket: WebSocket | null = null;
	let reconnectAttempts = 0;
	let socketConnected = $state(false);

	let activeFilter = $state<'all' | 'active' | 'completed' | 'failed'>('all');
	let query = $state('');

	const orderedDownloads = $derived(
		Object.values(downloads).sort((a, b) => (b.added_time ?? 0) - (a.added_time ?? 0))
	);
	const activeDownloads = $derived(orderedDownloads.filter((d) => isActive(d.status)).length);
	const completedDownloads = $derived(orderedDownloads.filter((d) => d.status === 'completed').length);
	const failedDownloads = $derived(
		orderedDownloads.filter((d) => d.status === 'failed' || d.status === 'rd_error').length
	);

	const filteredDownloads = $derived(
		orderedDownloads
			.filter((d) => {
				if (activeFilter === 'active') return isActive(d.status);
				if (activeFilter === 'completed') return d.status === 'completed';
				if (activeFilter === 'failed') return d.status === 'failed' || d.status === 'rd_error';
				return true;
			})
			.filter((d) => {
				const q = query.trim().toLowerCase();
				if (!q) return true;
				return d.name.toLowerCase().includes(q) || d.status.toLowerCase().includes(q);
			})
	);

	const linkType = $derived(classifyLink(link));
	const canAdd = $derived(linkType === 'magnet' || linkType === 'direct');

	function showError(message: string) {
		toast.error(message);
	}

	function showSuccess(message: string) {
		toast.success(message);
	}

	function closeAccountMenuOnOutsideClick(event: PointerEvent) {
		const target = event.target;
		if (accountMenuOpen && accountMenuElement && target instanceof Node && !accountMenuElement.contains(target)) {
			accountMenuOpen = false;
		}
	}

	function formatBytes(bytes: number, decimals = 1) {
		if (!bytes || bytes <= 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
		return `${parseFloat((bytes / 1024 ** unit).toFixed(Math.max(0, decimals)))} ${units[unit]}`;
	}

	function formatSpeed(d: Download) {
		const mbps = (d.speed_mbps || 0) + (d.rd_speed_bps || 0) / 1024 / 1024;
		if (mbps <= 0) return '';
		if (mbps < 1) return `${(mbps * 1024).toFixed(0)} KB/s`;
		return `${mbps.toFixed(1)} MB/s`;
	}

	function formatSize(d: Download) {
		if (d.size_mb > 0) return `${d.size_mb.toFixed(1)} MB`;
		if (d.rd_total_size_bytes > 0) return formatBytes(d.rd_total_size_bytes);
		return '';
	}

	function formatMb(value: number) {
		return value > 0 ? `${value.toFixed(value >= 100 ? 0 : 1)} MB` : '—';
	}

	function date(value?: string) {
		return value ? new Date(value).toLocaleDateString() : 'N/A';
	}

	function statusLabel(value: string) {
		const labels: Record<string, string> = {
			processing_torrent: 'processing', waiting_rd: 'queued', rd_downloading: 'RD downloading',
			unrestricting: 'preparing files', selecting_files: 'select files'
		};
		return labels[value] ?? value.replaceAll('_', ' ');
	}

	function classifyLink(value: string) {
		const trimmed = value.trim();
		if (!trimmed) return 'empty' as const;
		if (/^magnet:\?/i.test(trimmed)) return 'magnet' as const;
		if (/^https?:\/\/.+/i.test(trimmed)) return 'direct' as const;
		return 'invalid' as const;
	}

	function isActive(status: string) {
		return !['completed', 'failed', 'cancelled', 'rd_error'].includes(status);
	}

	function statusClass(status: string) {
		if (status === 'completed') return 'text-emerald-400';
		if (status === 'failed' || status === 'rd_error') return 'text-red-400';
		if (status === 'paused' || status === 'cancelled') return 'text-zinc-400';
		if (status === 'rd_downloading') return 'text-violet-300';
		return 'text-sky-300';
	}

	function dotClass(status: string) {
		if (status === 'completed') return 'bg-emerald-400';
		if (status === 'failed' || status === 'rd_error') return 'bg-red-400';
		if (status === 'paused' || status === 'cancelled') return 'bg-zinc-500';
		if (status === 'rd_downloading') return 'bg-violet-400';
		return 'bg-sky-400';
	}

	function barClass(status: string) {
		if (status === 'completed') return '[&_[data-slot=progress-indicator]]:bg-emerald-400';
		if (status === 'failed' || status === 'rd_error') return '[&_[data-slot=progress-indicator]]:bg-red-400';
		if (status === 'paused' || status === 'cancelled') return '[&_[data-slot=progress-indicator]]:bg-zinc-500';
		if (status === 'rd_downloading') return '[&_[data-slot=progress-indicator]]:bg-violet-400';
		return '[&_[data-slot=progress-indicator]]:bg-sky-400';
	}

	async function request(path: string, init: RequestInit = {}) {
		const response = await fetch(path, init);
		const data = await response.json().catch(() => ({}));
		if (!response.ok) {
			if (response.status === 401) authenticated = false;
			throw new Error(data.detail || 'Request failed');
		}
		return data;
	}

	async function login() {
		if (!password || loggingIn) return;
		loggingIn = true;
		loginError = '';
		try {
			await request('/api/auth/login', {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ password })
			});
			authenticated = true;
			password = '';
			connectWebSocket();
			fetchAccount();
			fetchSettings();
		} catch (error) {
			loginError = error instanceof Error ? error.message : 'Login failed';
		} finally {
			loggingIn = false;
		}
	}

	async function logout() {
		await request('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
		socket?.close();
		accountMenuOpen = false;
		authenticated = false;
	}

	function connectWebSocket() {
		if (!authenticated) return;
		const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
		socket = new WebSocket(`${protocol}//${location.host}/ws`);

		socket.onopen = () => {
			reconnectAttempts = 0;
			socketConnected = true;
		};
		socket.onmessage = (event) => {
			const data = JSON.parse(event.data);
			if (data.type === 'full_state') {
				downloads = data.downloads;
				initialLoading = false;
				const pendingSelection = (Object.values(data.downloads) as Download[]).find((download) => download.status === 'selecting_files');
				if (pendingSelection && !selectionDialogOpen) void openSelection(pendingSelection);
			}
			if (data.type === 'update') {
				downloads[data.download.id] = data.download;
				if (data.download.status === 'selecting_files' && !selectionDialogOpen) void openSelection(data.download);
			}
		};
		socket.onclose = () => {
			socket = null;
			socketConnected = false;
			if (reconnectAttempts < 10) {
				reconnectAttempts += 1;
				setTimeout(connectWebSocket, Math.min(1000 * 2 ** reconnectAttempts, 30000));
			} else {
				showError('Disconnected. Refresh the page to reconnect.');
			}
		};
	}

	async function fetchAccount() {
		try {
			const data = await request('/api/account/info');
			if (!data.user || typeof data.user.username !== 'string') throw new Error('Invalid account response');
			account = data.user;
			accountError = '';
		} catch {
			account = null;
			accountError = 'Account unavailable';
		}
	}

	async function fetchSettings() {
		try {
			settings = await request('/api/settings');
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Settings unavailable');
		}
	}

	async function loadStorage(refresh = false) {
		storageError = '';
		if (refresh) refreshingStorage = true;
		try {
			storage = await request(`/api/storage${refresh ? '?refresh=true' : ''}`);
		} catch (error) {
			storageError = error instanceof Error ? error.message : 'Storage unavailable';
		} finally {
			refreshingStorage = false;
		}
	}

	async function openStorage() {
		storageDialogOpen = true;
		await loadStorage();
	}

	async function addDownload() {
		if (!canAdd || adding) return;
		adding = true;
		formMessage = '';
		try {
			const body = new FormData();
			body.append('link', link.trim());
			await request('/api/download', { method: 'POST', body });
			link = '';
		} catch (error) {
			formMessage = error instanceof Error ? error.message : 'Failed to add download';
		} finally {
			adding = false;
		}
	}

	async function openSelection(download: Download) {
		selectionDownload = download;
		selectionDialogOpen = true;
		loadingSelection = true;
		try {
			const data = await request(`/api/download/${download.id}/files`);
			selectionDownload = { ...download, files: data.files ?? [] };
			selectedFileIds = (data.files ?? []).filter((file: FileEntry) => file.selected).map((file: FileEntry) => file.id).filter((id: number | undefined): id is number => id != null);
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Could not load torrent files');
			selectionDialogOpen = false;
		} finally {
			loadingSelection = false;
		}
	}

	function toggleFile(id?: number) {
		if (id == null) return;
		selectedFileIds = selectedFileIds.includes(id)
			? selectedFileIds.filter((value) => value !== id)
			: [...selectedFileIds, id];
	}

	async function submitSelection() {
		if (!selectionDownload || !selectedFileIds.length || submittingSelection) return;
		submittingSelection = true;
		try {
			await request(`/api/download/${selectionDownload.id}/files`, {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selectedFileIds })
			});
			selectionDownload = { ...selectionDownload, status: 'starting' };
			selectionDialogOpen = false;
			showSuccess('Torrent selection saved.');
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Could not select files');
		} finally {
			submittingSelection = false;
		}
	}

	async function pasteLink() {
		try {
			const text = await navigator.clipboard.readText();
			if (text) {
				link = text.trim();
				formMessage = '';
			}
		} catch {
			formMessage = 'Clipboard access is unavailable.';
		}
	}

	async function copyOriginalLink(download: Download) {
		if (!download.original_link) {
			showError('No link available for this download.');
			return;
		}
		try {
			await navigator.clipboard.writeText(download.original_link);
		} catch {
			const textarea = document.createElement('textarea');
			textarea.value = download.original_link;
			textarea.style.position = 'fixed';
			textarea.style.opacity = '0';
			document.body.appendChild(textarea);
			textarea.select();
			try {
				document.execCommand('copy');
			} catch {
				textarea.remove();
				showError('Could not copy link.');
				return;
			}
			textarea.remove();
		}
		copiedLinkId = download.id;
		showSuccess(download.type === 'magnet' ? 'Magnet link copied.' : 'Download link copied.');
		setTimeout(() => {
			if (copiedLinkId === download.id) copiedLinkId = null;
		}, 1500);
	}

	async function copySavePath(download: Download) {
		if (!download.output_path) {
			showError('No save path for this download.');
			return;
		}
		try {
			await navigator.clipboard.writeText(pathLabel(download.output_path));
			copiedPathId = download.id;
			showSuccess('Save path copied.');
			setTimeout(() => {
				if (copiedPathId === download.id) copiedPathId = null;
			}, 1500);
		} catch {
			showError('Could not copy save path.');
		}
	}

	function clearLink() {
		link = '';
		formMessage = '';
	}

	async function downloadAction(id: string, action: 'pause' | 'resume' | 'cancel') {
		if (actionInFlight) return;
		actionInFlight = `${id}:${action}`;
		try {
			await request(`/api/download/${id}/${action}`, { method: 'POST' });
			showSuccess(action === 'pause' ? 'Download paused.' : action === 'resume' ? 'Download resumed.' : 'Download cancelled.');
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Action failed');
		} finally {
			actionInFlight = null;
		}
	}

	function isMultipart(download: Download) {
		return download.total_files > 1;
	}

	function formatAdaptiveMb(mb: number) {
		if (!(mb > 0)) return '';
		if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
		if (mb >= 100) return `${mb.toFixed(0)} MB`;
		return `${mb.toFixed(1)} MB`;
	}

	function sizeLabel(download: Download) {
		const total = download.total_size_mb || download.size_mb;
		return (
			formatAdaptiveMb(total) ||
			formatAdaptiveMb(download.current_file_size_mb) ||
			(download.rd_total_size_bytes > 0 ? formatBytes(download.rd_total_size_bytes) : '')
		);
	}

	function rowMeta(download: Download) {
		const parts: string[] = [];
		if (isMultipart(download)) {
			parts.push(
				download.status === 'completed'
					? `${download.total_files} files`
					: `${download.completed_files} of ${download.total_files} files`
			);
		}
		const size = isMultipart(download)
			? sizeLabel(download)
			: formatAdaptiveMb(download.current_file_size_mb || download.size_mb) || sizeLabel(download);
		if (size) parts.push(size);
		const speed = formatSpeed(download);
		if (speed) parts.push(speed);
		if (download.seeders != null && (download.status === 'rd_downloading' || download.status === 'processing_torrent')) {
			parts.push(`${download.seeders} seeders`);
		}
		return parts.join(' · ');
	}

	function showRightPercent(download: Download) {
		return download.status !== 'completed' && isActive(download.status) && download.status !== 'paused';
	}

	function metaLine(download: Download) {
		const base = rowMeta(download);
		if (download.status === 'completed' || showRightPercent(download)) return base;
		const percent = `${download.progress.toFixed(0)}%`;
		return base ? `${base} · ${percent}` : percent;
	}

	function toggleExpanded(id: string) {
		expandedDownloads[id] = !expandedDownloads[id];
	}

	function fileName(file: FileEntry) {
		return (file.name ?? 'Unnamed file').split('/').pop() ?? 'Unnamed file';
	}

	function fileSize(file: FileEntry) {
		return file.size && file.size > 0 ? formatBytes(file.size) : 'Size unknown';
	}

	function errorLabel(download: Download) {
		if (!download.error_message) return '';
		const clean = download.error_message
			.replace(/^RD Error:\s*/i, '')
			.replace(/\s*\(Code:\s*\d+\)/gi, '')
			.replace(/\s*\(RD error code\s*\d+\)/gi, '')
			.replaceAll('_', ' ')
			.trim();
		const message = clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : 'Real-Debrid error';
		return `${message}${download.error_code != null ? ` (RD error code ${download.error_code})` : ''}`;
	}

	function pathLabel(path?: string | null) {
		return path ? path.replaceAll('\\', '/') : '';
	}

	function truncateMiddle(value: string, max = 40) {
		if (value.length <= max) return value;
		const head = Math.ceil((max - 1) / 2);
		const tail = Math.floor((max - 1) / 2);
		return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
	}

	async function clearDownload(id: string, deleteLocal = false) {
		try {
			const data = await request(`/api/download/${id}${deleteLocal ? '?delete_local=true' : ''}`, { method: 'DELETE' });
			delete downloads[id];
			if (data.warnings?.length) showError(data.warnings.join(' '));
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Delete failed');
		}
	}

	function requestDelete(id: string) {
		pendingDeleteId = id;
		deleteLocalFiles = false;
		deleteDialogOpen = true;
	}

	async function confirmDelete() {
		if (!pendingDeleteId) return;
		await clearDownload(pendingDeleteId, deleteLocalFiles);
		deleteDialogOpen = false;
		pendingDeleteId = null;
	}

	async function clearCompleted() {
		const targets = orderedDownloads.filter((d) => d.status === 'completed');
		if (!targets.length) return;
		clearingCompleted = true;
		await Promise.all(targets.map((d) => clearDownload(d.id)));
		clearingCompleted = false;
	}

	async function confirmClearCompleted() {
		clearCompletedDialogOpen = false;
		await clearCompleted();
	}

	function requestCancel(id: string) {
		pendingCancelId = id;
		cancelDialogOpen = true;
	}

	function openDetails() {
		apiKey = '';
		settingsMessage = null;
		detailsDialogOpen = true;
		fetchSettings();
	}

	async function confirmCancel() {
		if (!pendingCancelId) return;
		await downloadAction(pendingCancelId, 'cancel');
		cancelDialogOpen = false;
		pendingCancelId = null;
	}

	async function saveSettings() {
		if (saving) return;
		saving = true;
		settingsMessage = null;
		try {
			const data = await request('/api/settings', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					rd_api_key: apiKey || null,
					download_folder: settings.download_folder,
					max_concurrent_downloads: Number(settings.max_concurrent_downloads),
					webhook_url: settings.webhook_url,
					webhook_token: webhookToken || null,
					webhook_events: settings.webhook_events
				})
			});
			settings = data;
			apiKey = '';
			webhookToken = '';
			detailsDialogOpen = false;
			showSuccess('Settings saved.');
			fetchAccount();
		} catch (error) {
			settingsMessage = { type: 'error', text: error instanceof Error ? error.message : 'Failed to save settings.' };
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		let timer: ReturnType<typeof setInterval> | undefined;
		document.addEventListener('pointerdown', closeAccountMenuOnOutsideClick);
		request('/api/auth/session').then((data) => {
			authenticated = data.authenticated;
			authChecked = true;
			if (authenticated) {
				connectWebSocket();
				fetchAccount();
				fetchSettings();
				timer = setInterval(fetchAccount, 300000);
			}
		}).catch(() => {
			authChecked = true;
			loginError = 'Unable to contact the server.';
		});
		return () => {
			if (timer) clearInterval(timer);
			document.removeEventListener('pointerdown', closeAccountMenuOnOutsideClick);
			socket?.close();
		};
	});
</script>

<svelte:head>
	<title>RMT-Debrid</title>
	<meta name="description" content="Real-Debrid download manager." />
</svelte:head>

{#if authChecked && authenticated}
	<Tooltip.Provider>
	<main class="min-h-screen bg-background text-foreground">
		<header class="border-b border-border">
			<div class="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-8">
				<a href="/" class="flex items-center gap-2 text-foreground no-underline" aria-label="RMT-Debrid home">
					<Zap class="size-4" strokeWidth={2} />
					<span class="text-sm font-semibold tracking-tight">RMT-Debrid</span>
				</a>

				<div class="flex items-center gap-1">
			{#if account}
						<div class="relative" bind:this={accountMenuElement}>
							<button
								type="button"
								class="flex h-9 cursor-pointer items-center gap-2 rounded-md px-2 text-left transition hover:bg-muted"
								aria-label="Open account menu"
								aria-haspopup="menu"
								aria-expanded={accountMenuOpen}
								onclick={() => (accountMenuOpen = !accountMenuOpen)}
							>
								<span class="hidden leading-tight sm:block">
									<span class="block text-xs font-semibold capitalize">{account.type}</span>
									<span class="block font-mono text-[10px] text-muted-foreground">expires {date(account.expiration)}</span>
								</span>
								<span class="grid size-8 place-items-center rounded-full border border-border bg-muted font-mono text-[10px] text-muted-foreground">
									{account.username.slice(0, 2).toUpperCase()}
								</span>
							</button>
							{#if accountMenuOpen}
								<div class="absolute top-11 right-0 z-50 min-w-28 rounded-md border border-border bg-card p-1 shadow-xl" role="menu" aria-label="Account menu">
									<button type="button" class="flex w-full cursor-pointer items-center rounded px-2 py-1.5 text-left text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground" role="menuitem" onclick={logout}>Sign out</button>
								</div>
							{/if}
						</div>
					{:else if accountError}
						<span class="hidden text-xs text-muted-foreground sm:block">{accountError}</span>
					{/if}
					<Button variant="ghost" size="icon-sm" aria-label="Open storage diagnostics" onclick={openStorage}>
						<Server class="size-4" />
					</Button>
					<Button variant="ghost" size="icon-sm" aria-label="Open settings" onclick={() => openDetails()}>
						<Settings class="size-4" />
					</Button>
				</div>
			</div>
		</header>

		<div class="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8">

			<!-- add download -->
			<Card class="mt-4 gap-0 rounded-md py-0">
				<CardContent class="px-3 py-2">
					<form
						class="flex items-center gap-2"
						onsubmit={(e) => {
							e.preventDefault();
							addDownload();
						}}
					>
						<div class="relative min-w-0 flex-1">
							<Link2 class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="link-input"
								class={`h-10 pr-16 pl-9 font-mono text-[13px] ${linkType === 'invalid' ? 'border-red-500/50' : ''}`}
								bind:value={link}
								placeholder="Paste magnet or direct link"
								aria-label="Magnet or direct link"
								autocomplete="off"
								spellcheck="false"
							/>
							<div class="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-0.5">
								<button type="button" onclick={pasteLink} aria-label="Paste from clipboard" title="Paste from clipboard" class="grid size-6 cursor-pointer place-items-center rounded text-foreground/60 transition hover:text-foreground">
									<Clipboard class="size-3.5" />
								</button>
								{#if link}
									<button type="button" onclick={clearLink} aria-label="Clear link" class="grid size-6 cursor-pointer place-items-center rounded text-muted-foreground transition hover:text-foreground">
										<X class="size-3.5" />
									</button>
								{/if}
							</div>
						</div>
						<Button type="submit" class="h-10 shrink-0 disabled:opacity-30" disabled={!canAdd || adding}>
							{#if adding}<Loader2 class="size-4 animate-spin" /> Adding…{:else}Add{/if}
						</Button>
					</form>
					{#if formMessage}
						<p class="mt-2 text-xs text-red-400" role="alert">{formMessage}</p>
					{:else if linkType === 'invalid'}
						<p class="mt-2 text-xs text-red-400" role="alert">Enter a valid magnet or http(s) link.</p>
					{/if}
				</CardContent>
			</Card>

			<!-- queue -->
			<section aria-labelledby="downloads-heading" class="mt-4">
				<Card class="gap-0 rounded-md py-0">
					<CardHeader class="border-b border-border/60 px-4 py-3">
						<div class="flex flex-wrap items-center justify-between gap-2">
							<CardTitle id="downloads-heading" class="text-sm font-semibold text-foreground">
								Download Queue
							</CardTitle>
							{#if completedDownloads > 0}
								<Button variant="ghost" size="xs" disabled={clearingCompleted} onclick={() => (clearCompletedDialogOpen = true)}>
									{#if clearingCompleted}<Loader2 class="size-3 animate-spin" />{/if}
									Clear completed
								</Button>
							{/if}
						</div>
						<div class="mt-2.5 grid items-center gap-2 sm:grid-cols-5">
							<div class="relative min-w-0 sm:col-span-3">
								<Search class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
								<Input bind:value={query} placeholder="Search downloads..." aria-label="Search downloads" class="h-8 pl-8 text-[13px]" />
							</div>
							<div class="flex items-center gap-1 rounded-lg border border-border/50 bg-muted p-1 sm:col-span-2" role="group" aria-label="Filter downloads">
								{#each [{ k: 'all', label: 'All', n: orderedDownloads.length }, { k: 'active', label: 'Active', n: activeDownloads }, { k: 'completed', label: 'Completed', n: completedDownloads }, { k: 'failed', label: 'Failed', n: failedDownloads }] as f}
									<button
										type="button"
										aria-pressed={activeFilter === f.k}
										onclick={() => (activeFilter = f.k as typeof activeFilter)}
										class={`flex h-6 flex-1 cursor-pointer items-center justify-center gap-1 rounded-md px-1.5 text-[11px] font-medium whitespace-nowrap transition-colors duration-75 ${activeFilter === f.k ? 'bg-foreground/10 text-foreground shadow-sm' : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'}`}
									>
										<span class="leading-none">{f.label} <span class="relative -top-px font-mono text-[10px] opacity-70">{f.n}</span></span>
									</button>
								{/each}
							</div>
						</div>
					</CardHeader>

					<CardContent class="px-4 pb-2">
						{#if initialLoading}
							<div class="grid gap-1 py-2" aria-label="Loading downloads">
								{#each [0, 1, 2] as i}
									<div class="py-2">
										<div class="h-3.5 w-2/3 animate-pulse rounded bg-muted"></div>
										<div class="mt-2 h-[5px] w-full animate-pulse rounded bg-muted"></div>
									</div>
								{/each}
							</div>
						{:else if orderedDownloads.length === 0}
							<div class="flex flex-col items-center px-6 py-10 text-center">
								<Inbox class="size-6 text-muted-foreground" />
								<p class="mt-3 text-sm text-muted-foreground">Queue is empty</p>
							</div>
						{:else if filteredDownloads.length === 0}
							<div class="px-6 py-10 text-center text-sm text-muted-foreground">No matches</div>
						{:else}
							<ul class="divide-y divide-border/30">
								{#each filteredDownloads as download (download.id)}
									<li class="group py-3.5">
										<div class="flex items-start gap-1.5">
											<div class="flex h-8 w-5 shrink-0 items-center justify-center">
										{#if isMultipart(download)}
													<button type="button" class="grid size-5 shrink-0 cursor-pointer place-items-center rounded text-muted-foreground transition hover:bg-muted hover:text-foreground" aria-label={`${expandedDownloads[download.id] ? 'Collapse' : 'Expand'} file list`} aria-expanded={expandedDownloads[download.id] ?? false} onclick={() => toggleExpanded(download.id)}>
															<ChevronRight class={`size-3.5 transition-transform ${expandedDownloads[download.id] ? 'rotate-90' : ''}`} />
													</button>
												{:else}
													<span class="size-5 shrink-0"></span>
												{/if}
													</div>

											<div class="min-w-0 flex-1">
												<div class="flex items-center justify-between gap-3">
															<div class="flex min-w-0 items-center gap-1.5">
																<p class="min-w-0 truncate text-sm font-semibold" title={download.name}>{download.name}</p>
																<span class={`inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium whitespace-nowrap capitalize ${statusClass(download.status)}`}>
																	<span class={`size-1.5 rounded-full ${dotClass(download.status)}`}></span>
																	{statusLabel(download.status)}
																</span>
																{#if download.original_link}
																	<Tooltip.Root>
																		<Tooltip.Trigger>
																			{#snippet child({ props })}
																				<Button {...props} variant="ghost" size="icon-sm" class="hidden size-6 shrink-0 group-hover:inline-flex" aria-label={download.type === 'magnet' ? 'Copy magnet link' : 'Copy download link'} onclick={() => copyOriginalLink(download)}>
																					{#if copiedLinkId === download.id}<Check class="size-3.5 text-emerald-400" />{:else}<Link2 class="size-3.5" />{/if}
																				</Button>
																			{/snippet}
																		</Tooltip.Trigger>
																		<Tooltip.Content>{download.type === 'magnet' ? 'Copy magnet link' : 'Copy download link'}</Tooltip.Content>
																	</Tooltip.Root>
																{/if}
															</div>
													<div class="flex shrink-0 items-center gap-0.5">
														{#if !isActive(download.status)}
															{#if download.status === 'failed' || download.status === 'rd_error'}
																<Tooltip.Root>
																	<Tooltip.Trigger>
																		{#snippet child({ props })}
															<Button {...props} variant="ghost" size="icon-sm" aria-label="Retry download" onclick={() => downloadAction(download.id, 'resume')}><RotateCcw class="size-3.5" /></Button>
																		{/snippet}
																	</Tooltip.Trigger>
																	<Tooltip.Content>Retry</Tooltip.Content>
																</Tooltip.Root>
															{/if}
															<Tooltip.Root>
																<Tooltip.Trigger>
																	{#snippet child({ props })}
									{#if download.status === 'completed' && download.output_path}
															<Tooltip.Root>
																<Tooltip.Trigger>
																	{#snippet child({ props })}
																		<Button {...props} variant="ghost" size="icon-sm" aria-label="Copy save path" onclick={() => copySavePath(download)}>{#if copiedPathId === download.id}<Check class="size-3.5 text-emerald-400" />{:else}<FolderOpen class="size-3.5" />{/if}</Button>
																	{/snippet}
																</Tooltip.Trigger>
																<Tooltip.Content>Copy save path</Tooltip.Content>
															</Tooltip.Root>
														{/if}
														<Button {...props} variant="ghost" size="icon-sm" aria-label="Remove download" onclick={() => requestDelete(download.id)}><Trash2 class="size-3.5" /></Button>
																	{/snippet}
																</Tooltip.Trigger>
																<Tooltip.Content>Remove</Tooltip.Content>
															</Tooltip.Root>
								{:else}
									{#if download.status === 'downloading'}
											<Tooltip.Root>
																		<Tooltip.Trigger>
																			{#snippet child({ props })}
																				<Button {...props} variant="ghost" size="icon-sm" disabled={actionInFlight?.startsWith(`${download.id}:`)} aria-label="Pause download" onclick={() => downloadAction(download.id, 'pause')}><Pause class="size-3.5" /></Button>
																			{/snippet}
																		</Tooltip.Trigger>
																		<Tooltip.Content>Pause</Tooltip.Content>
																	</Tooltip.Root>
									{:else if download.status === 'paused'}
											<Tooltip.Root>
																		<Tooltip.Trigger>
																			{#snippet child({ props })}
																				<Button {...props} variant="ghost" size="icon-sm" disabled={actionInFlight?.startsWith(`${download.id}:`)} aria-label="Resume download" onclick={() => downloadAction(download.id, 'resume')}><Play class="size-3.5" /></Button>
																			{/snippet}
																		</Tooltip.Trigger>
																		<Tooltip.Content>Resume</Tooltip.Content>
																	</Tooltip.Root>
									{/if}
															<Tooltip.Root>
																<Tooltip.Trigger>
																	{#snippet child({ props })}
															<Button {...props} variant="ghost" size="icon-sm" disabled={actionInFlight?.startsWith(`${download.id}:`)} aria-label="Cancel download" onclick={() => requestCancel(download.id)}><X class="size-4" /></Button>
																	{/snippet}
																</Tooltip.Trigger>
																<Tooltip.Content>Cancel</Tooltip.Content>
															</Tooltip.Root>
														{/if}
													</div>
												</div>

										<div class="mt-1 flex items-baseline justify-between gap-3">
											<p class="min-w-0 truncate font-mono text-xs text-muted-foreground">{metaLine(download)}</p>
											{#if showRightPercent(download)}
												<span class="w-11 shrink-0 text-right font-mono text-xs text-foreground">{download.progress.toFixed(0)}%</span>
											{/if}
										</div>
										{#if download.status !== 'completed'}
											<div class="mt-1.5">
												<Progress value={download.progress} max={100} class={`h-[5px] flex-1 ${barClass(download.status)}`} aria-label={`${download.name} progress`} />
											</div>
										{/if}
									{#if isMultipart(download) && expandedDownloads[download.id]}
										{#if download.status === 'completed'}
											<div class="mt-1.5 grid gap-1">
												{#each download.files ?? [] as file}
													<div class="flex items-center gap-2 text-xs">
														<Check class="size-3.5 shrink-0 text-emerald-400" />
														<span class="min-w-0 truncate font-mono text-muted-foreground" title={file.name}>{fileName(file)}</span>
														<span class="ml-auto shrink-0 font-mono text-muted-foreground">{fileSize(file)}</span>
													</div>
												{/each}
											</div>
										{:else}
											<div class="mt-1.5 grid gap-1">
												{#each download.files ?? [] as file}
													<div>
														<div class="flex items-baseline gap-2 text-xs">
															<span class="min-w-0 truncate font-mono text-muted-foreground" title={file.name}>{fileName(file)}</span>
															<span class="ml-auto shrink-0 font-mono text-muted-foreground">{fileSize(file)}{#if download.status !== 'rd_downloading'} · {(file.progress ?? 0).toFixed(0)}%{/if}</span>
														</div>
														{#if download.status !== 'rd_downloading'}
															<Progress value={file.progress ?? 0} max={100} class={`mt-0.5 h-[3px] ${barClass(file.status ?? download.status)}`} aria-label={`${fileName(file)} progress`} />
														{/if}
													</div>
												{/each}
											</div>
										{/if}
									{/if}
										{#if download.output_path}
											<p class="mt-1.5 truncate font-mono text-[11px] text-muted-foreground/50" title={pathLabel(download.output_path)}>{truncateMiddle(pathLabel(download.output_path))}</p>
										{/if}

													{#if download.error_message && download.status !== 'cancelled'}
															<Alert.Root variant="destructive" class="mt-2">
																<Alert.Description class="text-xs">{errorLabel(download)}</Alert.Description>
													</Alert.Root>
												{/if}
											</div>
										</div>
									</li>
								{/each}
							</ul>
						{/if}
					</CardContent>
				</Card>
			</section>
		</div>

	</main>
<Dialog.Root bind:open={storageDialogOpen}>
	<Dialog.Content class="gap-0 p-0 sm:max-w-[560px]">
		<div class="border-b border-border px-6 pt-5 pr-14 pb-4">
			<Dialog.Header class="gap-1">
				<div class="flex items-center gap-2"><Dialog.Title>Storage</Dialog.Title><Button variant="ghost" size="icon-sm" class="size-7" onclick={() => loadStorage(true)} disabled={refreshingStorage} aria-label="Refresh storage details"><RefreshCw class={`size-3.5 ${refreshingStorage ? 'animate-spin' : ''}`} /></Button></div>
			</Dialog.Header>
		</div>

		<div class="max-h-[70vh] overflow-y-auto bg-muted/20 px-6 py-5">
			{#if storageError}
				<Alert.Root variant="destructive"><Alert.Description>{storageError}</Alert.Description></Alert.Root>
			{:else if storage}
				<div class="grid gap-4">
					<div class="grid grid-cols-4 gap-2 rounded-lg border border-border bg-background p-3 text-center">
						<div><strong class="block text-base tabular-nums">{storage.used_percent}%</strong><span class="text-[10px] uppercase text-muted-foreground">used</span></div>
						<div><strong class="block text-base tabular-nums">{storage.volumes.length}</strong><span class="text-xs text-muted-foreground">Volumes</span></div>
						<div><strong class="block text-base tabular-nums">{formatBytes(storage.total_bytes)}</strong><span class="text-xs text-muted-foreground">Total capacity</span></div>
						<div><strong class="block text-base tabular-nums">{formatBytes(storage.free_bytes)}</strong><span class="text-xs text-muted-foreground">Free overall</span></div>
					</div>
					{#each storage.volumes as volume}
						<div class="rounded-lg border border-border bg-background p-4">
							<div class="mb-3 flex items-center gap-3"><span class="grid size-9 place-items-center rounded-lg bg-muted">
								{#if volume.total_bytes < 1024 ** 4}<Box class="size-4 text-muted-foreground" />
								{:else if volume.total_bytes < 4 * 1024 ** 4}<HardDrive class="size-4 text-muted-foreground" />
								{:else}<Database class="size-4 text-muted-foreground" />{/if}
							</span><div class="min-w-0"><strong class="block truncate text-sm">{volume.name}</strong><span class="font-mono text-xs text-muted-foreground">{volume.path} · {volume.filesystem}</span></div></div>
							<div class="h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-foreground" style={`width: ${Math.min(volume.used_percent, 100)}%`}></div></div>
							<div class="mt-2 flex justify-between text-xs text-muted-foreground"><span>{formatBytes(volume.used_bytes)} used</span><span>{formatBytes(volume.free_bytes)} free</span></div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="flex items-center justify-center gap-2 rounded-lg border border-border bg-background px-4 py-12 text-sm text-muted-foreground"><Loader2 class="size-4 animate-spin" /> Loading storage…</div>
			{/if}
		</div>
	</Dialog.Content>
</Dialog.Root>



<Dialog.Root bind:open={detailsDialogOpen}>
	<Dialog.Content class="gap-0 p-0 sm:max-w-[440px]">
		<div class="border-b border-border px-6 pt-5 pr-14 pb-4">
			<Dialog.Header class="gap-1">
				<Dialog.Title>Settings</Dialog.Title>
			</Dialog.Header>
		</div>

		<div class="max-h-[60vh] overflow-y-auto px-6 py-5">
			<div class="grid gap-6">
				<section aria-labelledby="settings-account-heading" class="grid gap-2.5">
					<h3 id="settings-account-heading" class="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Account</h3>
					{#if account}
						<dl class="divide-y divide-border overflow-hidden rounded-lg border border-border bg-muted/30 text-[13px] leading-5">
							<div class="flex items-center justify-between gap-4 px-4 py-2.5">
								<dt class="text-muted-foreground">Username</dt>
								<dd class="min-w-0 truncate font-medium">{account.username}</dd>
							</div>
							<div class="flex items-center justify-between gap-4 px-4 py-2.5">
								<dt class="text-muted-foreground">Plan</dt>
								<dd class="font-medium capitalize">{account.type}</dd>
							</div>
							<div class="flex items-center justify-between gap-4 px-4 py-2.5">
								<dt class="text-muted-foreground">Expires</dt>
								<dd class="font-medium tabular-nums">{date(account.expiration)}</dd>
							</div>
							<div class="flex items-center justify-between gap-4 px-4 py-2.5">
								<dt class="text-muted-foreground">Fidelity points</dt>
								<dd class="font-medium tabular-nums">{account.points.toLocaleString()}</dd>
							</div>
						</dl>
					{:else if accountError}
						<Alert.Root variant="destructive">
							<Alert.Description class="text-[13px]">{accountError}. Check your API key below.</Alert.Description>
						</Alert.Root>
					{:else}
						<div class="flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-6 text-[13px] text-muted-foreground">
							<Loader2 class="size-4 animate-spin" /> Loading account…
						</div>
					{/if}
				</section>

				<form
					id="settings-form"
					aria-labelledby="settings-preferences-heading"
					class="grid gap-2.5"
					onsubmit={(e) => {
						e.preventDefault();
						saveSettings();
					}}
				>
					<h3 id="settings-preferences-heading" class="text-xs font-semibold tracking-wide text-muted-foreground uppercase mb-2">Preferences</h3>
					<div class="grid gap-5">
						<div class="grid gap-2">
							<label for="api-key" class="text-[13px] leading-none font-medium">Real-Debrid API key</label>
							<Input
								id="api-key"
								type="password"
								bind:value={apiKey}
								disabled={saving}
								placeholder="Leave blank to keep current"
								autocomplete="new-password"
								aria-describedby="api-key-hint"
								class="h-9 font-mono text-[13px]"
							/>
							<p id="api-key-hint" class="flex items-center gap-1.5 text-xs leading-4 text-muted-foreground">
								{#if settings.rd_api_key_set}
									<span>Key set: <span class="font-mono">•••{settings.rd_api_key_hint.slice(-4)}</span></span>
								{:else}
									<span>No key configured yet</span>
								{/if}
							</p>
						</div>
						<div class="grid gap-2">
							<label for="download-folder" class="text-[13px] leading-none font-medium">Download folder</label>
							<Input
								id="download-folder"
								bind:value={settings.download_folder}
								disabled={saving}
								required
								autocomplete="off"
								spellcheck="false"
								placeholder="/downloads"
								class="h-9 font-mono text-[13px]"
							/>
						</div>
						<div class="grid gap-2">
							<label for="max-concurrent" class="text-[13px] leading-none font-medium">Concurrent downloads</label>
							<Input
								id="max-concurrent"
								type="number"
								min="1"
								max="20"
								inputmode="numeric"
								bind:value={settings.max_concurrent_downloads}
								disabled={saving}
								required
								class="h-9 w-24 tabular-nums"
							/>
						</div>
						<div class="grid gap-2">
							<label for="webhook-url" class="text-[13px] leading-none font-medium">Completion webhook</label>
							<Input
								id="webhook-url"
								bind:value={settings.webhook_url}
								disabled={saving}
								type="url"
								placeholder="https://ntfy.example.com/downloads"
								autocomplete="off"
								class="h-9 font-mono text-[13px]"
							/>
							<p class="text-xs leading-4 text-muted-foreground">POSTs when a download completes.</p>
						</div>
						<div class="grid gap-2">
							<label for="webhook-token" class="text-[13px] leading-none font-medium">Webhook bearer token</label>
							<Input
								id="webhook-token"
								type="password"
								bind:value={webhookToken}
								disabled={saving}
								placeholder={settings.webhook_token_set ? 'Leave blank to keep current' : 'Optional'}
								autocomplete="new-password"
								class="h-9 font-mono text-[13px]"
							/>
						</div>
						<fieldset class="grid gap-2">
							<legend class="pb-2 text-[13px] leading-none font-medium">Notify me about</legend>
							<div class="grid gap-2 rounded-lg border border-border bg-muted/30 p-3">
								{#each webhookEventOptions as [event, label]}
									<label class="flex items-center gap-2 text-[13px]">
										<input
											type="checkbox"
										checked={settings.webhook_events.includes(event)}
										 onchange={(e) => {
											const events = new Set(settings.webhook_events);
											if (e.currentTarget.checked) events.add(event);
											else events.delete(event);
											settings.webhook_events = [...events];
										}}
										 disabled={saving}
										/>
										{label}
									</label>
								{/each}
							</div>
							<p class="text-xs leading-4 text-muted-foreground">Leave all unchecked to disable notifications.</p>
						</fieldset>
					</div>
				</form>
			</div>
		</div>

		<div class="flex min-h-16 items-center gap-3 border-t border-border bg-muted/30 px-6 py-4">
			<div class="min-w-0 flex-1">
				{#if settingsMessage}
					<p
						class="flex items-center gap-1.5 text-xs leading-4 {settingsMessage.type === 'success' ? 'text-emerald-500' : 'text-destructive'}"
						role={settingsMessage.type === 'error' ? 'alert' : 'status'}
						aria-live={settingsMessage.type === 'error' ? 'assertive' : 'polite'}
					>
						{#if settingsMessage.type === 'success'}
							<Check class="size-3.5 shrink-0" />
						{:else}
							<CircleAlert class="size-3.5 shrink-0" />
						{/if}
						<span class="truncate">{settingsMessage.text}</span>
					</p>
				{/if}
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<Button type="submit" form="settings-form" size="sm" class="h-8 min-w-28" disabled={saving}>
					{#if saving}<Loader2 class="size-3.5 animate-spin" /> Saving…{:else}<Save class="size-3.5" /> Save changes{/if}
				</Button>
			</div>
		</div>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={clearCompletedDialogOpen}>
	<Dialog.Content class="sm:max-w-[380px]">
		<div class="px-5 pt-5 pr-12 pb-4">
			<Dialog.Header>
				<div class="flex items-start gap-3">
					<span class="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
						<Trash2 class="size-4" />
					</span>
					<div class="grid gap-1 pt-0.5">
						<Dialog.Title>Clear completed?</Dialog.Title>
						<Dialog.Description>{completedDownloads} completed {completedDownloads === 1 ? 'download' : 'downloads'} will be removed from the queue. Local files are kept.</Dialog.Description>
					</div>
				</div>
			</Dialog.Header>
		</div>
		<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
			<Dialog.Close>
				{#snippet child({ props })}
					<Button variant="outline" size="sm" class="h-8" {...props}>Keep</Button>
				{/snippet}
			</Dialog.Close>
			<Button size="sm" class="h-8" onclick={confirmClearCompleted}>Clear completed</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={cancelDialogOpen}>
	<Dialog.Content class="sm:max-w-[380px]">
		<div class="px-5 pt-5 pr-12 pb-4">
			<Dialog.Header>
				<div class="flex items-start gap-3">
					<span class="grid size-9 shrink-0 place-items-center rounded-full bg-destructive/10 text-destructive">
						<CircleAlert class="size-4" />
					</span>
					<div class="grid gap-1 pt-0.5">
						<Dialog.Title>Cancel download?</Dialog.Title>
						<Dialog.Description>This stops the download but keeps it in the list.</Dialog.Description>
					</div>
				</div>
			</Dialog.Header>
		</div>
		<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
			<Dialog.Close>
				{#snippet child({ props })}
					<Button variant="outline" size="sm" class="h-8" {...props}>Keep</Button>
				{/snippet}
			</Dialog.Close>
			<Button variant="destructive" size="sm" class="h-8" onclick={confirmCancel}>Cancel download</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

	<Dialog.Root bind:open={selectionDialogOpen} onOpenChange={(open) => {
		if (!open && selectionDownload?.status === 'selecting_files') selectionDialogOpen = true;
	}}>
		<Dialog.Content showCloseButton={false} class="gap-4 p-6 sm:max-w-[560px]">
			<Dialog.Header>
				<Dialog.Title>Select files for {selectionDownload?.name ?? 'torrent'}</Dialog.Title>
				<Dialog.Description>You must choose at least one file before this torrent can start.</Dialog.Description>
			</Dialog.Header>
			<div class="max-h-[55vh] overflow-y-auto">
				{#if loadingSelection}
					<div class="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 class="size-4 animate-spin" /> Loading files…</div>
				{:else}
					<div class="grid gap-1">
						{#each selectionDownload?.files ?? [] as file}
							<label class="flex cursor-pointer items-center gap-3 rounded px-2 py-2 text-sm hover:bg-muted">
								<input type="checkbox" checked={file.id != null && selectedFileIds.includes(file.id)} onchange={() => toggleFile(file.id)} />
								<span class="min-w-0 flex-1 truncate" title={file.name}>{fileName(file)}</span>
								<span class="shrink-0 font-mono text-xs text-muted-foreground">{fileSize(file)}</span>
							</label>
						{/each}
					</div>
				{/if}
			</div>
			<Dialog.Footer>
				<Button size="sm" disabled={loadingSelection || submittingSelection || !selectedFileIds.length} onclick={submitSelection}>{submittingSelection ? 'Starting…' : `Start with ${selectedFileIds.length} selected`}</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>

	<Dialog.Root bind:open={deleteDialogOpen}>
		<Dialog.Content class="gap-0 p-0 sm:max-w-[420px]">
			<div class="px-5 pt-5 pr-12 pb-4">
				<Dialog.Header>
					<Dialog.Title>Remove download?</Dialog.Title>
					<Dialog.Description>The queue entry will be removed. Local files are kept unless you choose to delete them.</Dialog.Description>
				</Dialog.Header>
			</div>
			<div class="px-5 pb-4">
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" bind:checked={deleteLocalFiles} /> Delete local files and partial data
				</label>
			</div>
			<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
				<Dialog.Close>
					{#snippet child({ props })}<Button variant="outline" size="sm" {...props}>Keep</Button>{/snippet}
				</Dialog.Close>
				<Button variant="destructive" size="sm" onclick={confirmDelete}>Remove</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>

	</Tooltip.Provider>
{:else if authChecked}
	<main class="grid min-h-screen place-items-center bg-background px-4 text-foreground">
		<Card class="w-full max-w-sm">
			<CardHeader>
				<CardTitle>RMT-Debrid</CardTitle>
				<p class="text-sm text-muted-foreground">Enter the household password to continue.</p>
			</CardHeader>
			<CardContent>
				<form class="grid gap-3" onsubmit={(event) => { event.preventDefault(); login(); }}>
					<label for="login-password" class="text-sm font-medium">Password</label>
					<Input id="login-password" type="password" bind:value={password} autocomplete="current-password" autofocus />
					{#if loginError}<p class="text-xs text-red-400" role="alert">{loginError}</p>{/if}
					<Button type="submit" disabled={loggingIn || !password}>{loggingIn ? 'Signing in…' : 'Sign in'}</Button>
				</form>
			</CardContent>
		</Card>
	</main>
{:else}
	<main class="grid min-h-screen place-items-center bg-background px-4 text-foreground">
		<Loader2 class="size-5 animate-spin text-muted-foreground" aria-label="Loading" />
	</main>
{/if}
