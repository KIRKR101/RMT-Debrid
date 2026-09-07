<script lang="ts">
	import { onMount } from 'svelte';
	import {
		CircleAlert,
		Clipboard,
		Inbox,
		Link2,
		Loader2,
		FolderOpen,
		Pause,
		Play,
		RotateCcw,
		Search,
		Trash2,
		Check,
		X,
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
	import SiteHeader from '$lib/components/site-header.svelte';

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

	let downloads = $state<Record<string, Download>>({});

	let link = $state('');
	let formMessage = $state('');

	let adding = $state(false);
	let clearingCompleted = $state(false);
	let initialLoading = $state(true);
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
		} catch (error) {
			loginError = error instanceof Error ? error.message : 'Login failed';
		} finally {
			loggingIn = false;
		}
	}

	function handleLogout() {
		socket?.close();
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

	async function confirmCancel() {
		if (!pendingCancelId) return;
		await downloadAction(pendingCancelId, 'cancel');
		cancelDialogOpen = false;
		pendingCancelId = null;
	}

	onMount(() => {
		request('/api/auth/session').then((data) => {
			authenticated = data.authenticated;
			authChecked = true;
			if (authenticated) {
				connectWebSocket();
			}
		}).catch(() => {
			authChecked = true;
			loginError = 'Unable to contact the server.';
		});
		return () => {
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
		<SiteHeader onLogout={handleLogout} />

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
