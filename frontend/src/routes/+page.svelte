<script lang="ts">
	import { onMount } from 'svelte';
	import {
		CircleAlert,
		Clipboard,
		Inbox,
		Link2,
		Loader2,
		Pause,
		Play,
		RotateCcw,
		Save,
		Search,
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
		name?: string;
		size?: number;
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
	};

	let downloads = $state<Record<string, Download>>({});
	let account = $state<Account | null>(null);
	let accountError = $state('');

	let settings = $state<SettingsData>({
		download_folder: '',
		max_concurrent_downloads: 1,
		rd_api_key_set: false,
		rd_api_key_hint: ''
	});

	let link = $state('');
	let apiKey = $state('');
	let settingsMessage = $state<{ type: 'success' | 'error'; text: string } | null>(null);
	let formMessage = $state('');

	let adding = $state(false);
	let saving = $state(false);
	let clearingCompleted = $state(false);
	let initialLoading = $state(true);
	let detailsDialogOpen = $state(false);
	let cancelDialogOpen = $state(false);
	let pendingCancelId = $state<string | null>(null);
	let actionInFlight = $state<string | null>(null);
	let expandedDownloads = $state<Record<string, boolean>>({});

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
		if (!response.ok) throw new Error(data.detail || 'Request failed');
		return data;
	}

	function connectWebSocket() {
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
			}
			if (data.type === 'update') downloads[data.download.id] = data.download;
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

	function clearLink() {
		link = '';
		formMessage = '';
	}

	async function downloadAction(id: string, action: 'pause' | 'resume' | 'cancel') {
		if (actionInFlight) return;
		actionInFlight = `${id}:${action}`;
		try {
			await request(`/api/download/${id}/${action}`, { method: 'POST' });
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Action failed');
		} finally {
			actionInFlight = null;
		}
	}

	function fileProgress(download: Download) {
		return download.total_files > 1
			? `${download.completed_files} / ${download.total_files} files done`
			: download.status === 'completed' ? 'Ready' : '1 file';
	}

	function isMultipart(download: Download) {
		return download.total_files > 1;
	}

	function currentProgress(download: Download) {
		if (!isMultipart(download)) return download.progress;
		return Math.max(0, Math.min(100, download.progress * download.total_files - download.completed_files * 100));
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

	function overallSummary(download: Download) {
		if (!isMultipart(download)) return '1 file';
		return `${download.completed_files} completed · ${download.total_files} total`;
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

	async function clearDownload(id: string) {
		try {
			await request(`/api/download/${id}`, { method: 'DELETE' });
			delete downloads[id];
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Delete failed');
		}
	}

	async function clearCompleted() {
		const targets = orderedDownloads.filter((d) => d.status === 'completed');
		if (!targets.length) return;
		clearingCompleted = true;
		await Promise.all(targets.map((d) => clearDownload(d.id)));
		clearingCompleted = false;
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
					max_concurrent_downloads: Number(settings.max_concurrent_downloads)
				})
			});
			settings = data;
			apiKey = '';
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
		connectWebSocket();
		fetchAccount();
		fetchSettings();
		const timer = setInterval(fetchAccount, 300000);
		return () => {
			clearInterval(timer);
			socket?.close();
		};
	});
</script>

<svelte:head>
	<title>RMT-Debrid</title>
	<meta name="description" content="Real-Debrid download manager." />
</svelte:head>

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
						<Button
							variant="ghost"
							size="sm"
							class="h-9 gap-2 px-2"
							onclick={() => openDetails()}
							aria-label="Open account details"
						>
							<span class="hidden text-right leading-tight sm:block">
								<span class="block text-xs font-semibold capitalize">{account.type}</span>
								<span class="block font-mono text-[10px] text-muted-foreground">expires {date(account.expiration)}</span>
							</span>
							<span class="grid size-8 place-items-center rounded-full border border-border bg-muted font-mono text-[10px] text-muted-foreground">
								{account.username.slice(0, 2).toUpperCase()}
							</span>
						</Button>
					{:else if accountError}
						<span class="hidden text-xs text-muted-foreground sm:block">{accountError}</span>
					{/if}
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
						class="flex flex-col gap-2 sm:flex-row sm:items-center"
						onsubmit={(e) => {
							e.preventDefault();
							addDownload();
						}}
					>
						<div class="relative min-w-0 flex-1">
							<Link2 class="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
							<Input
								id="link-input"
								class={`h-10 pr-9 pl-9 font-mono text-[13px] ${linkType === 'invalid' ? 'border-red-500/50' : ''}`}
								bind:value={link}
								placeholder="Magnet or direct link"
								aria-label="Magnet or direct link"
								autocomplete="off"
								spellcheck="false"
							/>
							{#if link}
								<button type="button" onclick={clearLink} aria-label="Clear link" class="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded text-muted-foreground transition hover:text-foreground cursor-pointer">
									<X class="size-3.5" />
								</button>
							{/if}
						</div>
						<div class="flex shrink-0 items-center gap-2">
							<Button type="button" variant="outline" class="h-10" onclick={pasteLink}>
								<Clipboard class="size-4" /> Paste
							</Button>
							<Button type="submit" class="h-10 flex-1 sm:flex-none" disabled={!canAdd || adding}>
								{#if adding}<Loader2 class="size-4 animate-spin" /> Adding…{:else}Add{/if}
							</Button>
						</div>
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
					<CardHeader class="border-b border-border/60 px-3 py-2">
						<div class="flex flex-wrap items-center justify-between gap-3">
							<CardTitle id="downloads-heading" class="text-sm font-semibold text-foreground">
								Download Queue
							</CardTitle>
							{#if completedDownloads > 0}
								<Button variant="ghost" size="xs" disabled={clearingCompleted} onclick={clearCompleted}>
									{#if clearingCompleted}<Loader2 class="size-3 animate-spin" />{/if}
									Clear completed
								</Button>
							{/if}
						</div>
						<div class="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
							<div class="relative min-w-0 flex-1">
								<Search class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
								<Input bind:value={query} placeholder="Search" aria-label="Search downloads" class="h-8 pl-8 text-[13px]" />
							</div>
							<div class="flex items-center gap-1" role="group" aria-label="Filter downloads">
								{#each [{ k: 'all', label: 'All', n: orderedDownloads.length }, { k: 'active', label: 'Active', n: activeDownloads }, { k: 'completed', label: 'Completed', n: completedDownloads }, { k: 'failed', label: 'Failed', n: failedDownloads }] as f}
									<Button
										variant={activeFilter === f.k ? 'secondary' : 'ghost'}
										size="xs"
										aria-pressed={activeFilter === f.k}
										onclick={() => (activeFilter = f.k as typeof activeFilter)}
									>
										{f.label} <span class="font-mono text-[10px] text-muted-foreground">{f.n}</span>
									</Button>
								{/each}
							</div>
						</div>
					</CardHeader>

					<CardContent class="p-0">
						{#if initialLoading}
							<div class="divide-y divide-border/50" aria-label="Loading downloads">
								{#each [0, 1, 2] as i}
									<div class="flex items-center gap-4 px-3 py-3">
										<div class="size-9 animate-pulse rounded bg-muted"></div>
										<div class="min-w-0 flex-1">
											<div class="h-3 w-2/3 animate-pulse rounded bg-muted"></div>
											<div class="mt-2 h-1.5 w-full animate-pulse rounded bg-muted"></div>
										</div>
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
							<ul class="divide-y divide-border/50">
								{#each filteredDownloads as download (download.id)}
									<li class="px-3 py-2.5">
										<div class="flex items-start gap-3">
											<div class="mt-0.5 flex w-5 shrink-0 items-center">
												{#if isMultipart(download)}
													<button type="button" class="grid size-5 shrink-0 cursor-pointer place-items-center rounded text-muted-foreground transition hover:bg-muted hover:text-foreground" aria-label={`${expandedDownloads[download.id] ? 'Collapse' : 'Expand'} file list`} aria-expanded={expandedDownloads[download.id] ?? false} onclick={() => toggleExpanded(download.id)}>
															<ChevronRight class={`size-3.5 transition-transform ${expandedDownloads[download.id] ? 'rotate-90' : ''}`} />
													</button>
												{:else}
													<span class="size-5 shrink-0"></span>
												{/if}
													</div>

											<div class="min-w-0 flex-1">
												<div class="flex items-start justify-between gap-2">
															<div class="flex min-w-0 items-center gap-2">
																<p class="min-w-0 truncate text-[13px] font-medium" title={download.name}>{download.name}</p>
																<span class={`inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border/70 px-1.5 py-0.5 text-[10px] font-medium capitalize ${statusClass(download.status)}`}>
																	<span class={`size-1.5 rounded-full ${dotClass(download.status)}`}></span>
																	{statusLabel(download.status)}
																</span>
															</div>
													<div class="flex shrink-0 items-center">
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
															<Button {...props} variant="ghost" size="icon-sm" aria-label="Remove download" onclick={() => clearDownload(download.id)}><Trash2 class="size-3.5" /></Button>
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

											<div class="-mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 font-mono text-[11px] text-muted-foreground">
												{#if isMultipart(download) && formatSpeed(download)}<span>{formatSpeed(download)}</span>{/if}
										{#if download.seeders != null && (download.status === 'rd_downloading' || download.status === 'processing_torrent')}<span>{download.seeders} seeders</span>{/if}
									</div>

													<div class="mt-3 flex items-end justify-between gap-3">
														{#if isMultipart(download)}
															<div>
																<p class="text-[11px] font-semibold tracking-wide text-foreground uppercase">Overall progress</p>
																<p class="mt-0.5 font-mono text-[10px] text-muted-foreground">{overallSummary(download)} · {formatMb(download.total_size_mb || download.size_mb)}</p>
															</div>
														{:else}
															<div>
																<p class="text-[11px] font-semibold tracking-wide text-foreground uppercase">Progress</p>
																<p class="mt-0.5 font-mono text-[10px] text-muted-foreground">{formatMb(download.current_file_size_mb || download.size_mb)}{#if formatSpeed(download)} · {formatSpeed(download)}{/if}</p>
															</div>
														{/if}
														<strong class="font-mono text-xs text-foreground">{download.progress.toFixed(0)}%</strong>
													</div>
													<div class="mt-1.5 flex items-center gap-2.5">
														<Progress value={download.progress} max={100} class={`h-1 flex-1 ${barClass(download.status)}`} aria-label={`${download.name} progress`} />
													</div>
													{#if isMultipart(download)}
														{#if expandedDownloads[download.id]}
														<div class="mt-3 flex items-end justify-between gap-3">
															<div class="min-w-0">
																<p class="text-[11px] font-semibold tracking-wide text-foreground uppercase">Current file</p>
																<p class="mt-0.5 truncate font-mono text-[10px] text-muted-foreground" title={download.current_file_name ?? ''}>{download.current_file_name ?? 'Preparing next file'} · {formatMb(download.current_file_size_mb)}</p>
															</div>
															<strong class="font-mono text-xs text-foreground">{currentProgress(download).toFixed(0)}%</strong>
														</div>
														<div class="mt-1.5 flex items-center gap-2.5">
															<Progress value={currentProgress(download)} max={100} class={`h-1 flex-1 ${barClass(download.status)}`} aria-label={`${download.current_file_name ?? download.name} progress`} />
														</div>
														<div class="mt-3 grid gap-1.5 rounded border border-border/70 bg-muted/15 p-2">
															{#each download.files ?? [] as file, index}
																<div class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-[10px]">
																	<div class="flex min-w-0 items-center gap-1.5">
																		<span class={`size-1.5 shrink-0 rounded-full ${file.status === 'completed' ? 'bg-emerald-400' : file.status === 'downloading' ? 'bg-sky-400' : 'bg-muted-foreground/40'}`}></span>
																		<span class="truncate font-mono text-muted-foreground" title={file.name}>{index + 1}. {fileName(file)}</span>
																	</div>
																	<span class="font-mono text-muted-foreground">{fileSize(file)} · {(file.progress ?? 0).toFixed(0)}%{#if file.speed_mbps && file.speed_mbps > 0} · {file.speed_mbps.toFixed(1)} MB/s{/if}</span>
																	<Progress value={file.progress ?? 0} max={100} class={`col-span-2 h-1 ${barClass(file.status ?? download.status)}`} aria-label={`${fileName(file)} progress`} />
																</div>
															{/each}
														</div>
														{/if}
													{/if}
											<div class="mt-3 flex min-w-0 items-center gap-1.5 border-t border-border/60 pt-2 font-mono text-[10px]">
												<span class="shrink-0 text-muted-foreground">Saved to:</span>
												{#if download.output_path}<p class="min-w-0 truncate text-foreground" title={download.output_path}>{pathLabel(download.output_path)}</p>{:else}<p class="text-muted-foreground">Choosing destination…</p>{/if}
											</div>

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
</Tooltip.Provider>

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
