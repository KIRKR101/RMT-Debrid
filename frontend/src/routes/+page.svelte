<script lang="ts">
	import { onMount } from 'svelte';
	import {
		WarningCircle,
		Clipboard,
		Tray,
		Link,
		CircleNotch,
		FolderOpen,
		Pause,
		Play,
		Eye,
		EyeSlash,
		ArrowCounterClockwise,
		ArrowFatLineUp,
		MagnifyingGlass,
		Trash,
		Check,
		X,
		CaretRight
	} from 'phosphor-svelte';

	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Progress } from '$lib/components/ui/progress';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import * as Tabs from '$lib/components/ui/tabs';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import StatusBadge from '$lib/components/status-badge.svelte';
	import EmptyState from '$lib/components/empty-state.svelte';
	import { statusKind } from '$lib/status';
	import { formatBytes, formatAdaptiveMb, truncateMiddle, pathLabel } from '$lib/format';
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
	let showPassword = $state(false);
	let capsLockOn = $state(false);
	let loginError = $state('');
	let loggingIn = $state(false);
	let selectionDialogOpen = $state(false);
	let selectionDownload = $state<Download | null>(null);
	let selectionDismissedId = $state<string | null>(null);
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
	const completedDownloads = $derived(
		orderedDownloads.filter((d) => d.status === 'completed').length
	);
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

	function classifyLink(value: string) {
		const trimmed = value.trim();
		if (!trimmed) return 'empty' as const;
		if (/^magnet:\?/i.test(trimmed)) return 'magnet' as const;
		if (/^https?:\/\/.+/i.test(trimmed)) return 'direct' as const;
		return 'invalid' as const;
	}

	function isActive(status: string) {
		return !['completed', 'added_to_rd', 'failed', 'cancelled', 'rd_error'].includes(status);
	}

	function barClass(status: string) {
		const kind = statusKind(status);
		if (kind === 'destructive') return '[&_[data-slot=progress-indicator]]:bg-destructive';
		return '[&_[data-slot=progress-indicator]]:bg-foreground';
	}

	function railClass(status: string) {
		const kind = statusKind(status);
		if (kind === 'success') return 'ledger-rail is-done';
		if (kind === 'destructive') return 'ledger-rail is-failed';
		if (status === 'paused') return 'ledger-rail is-paused';
		return 'ledger-rail';
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
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ password })
			});
			authenticated = true;
			password = '';
			connectWebSocket();
		} catch (error) {
			const raw = error instanceof Error ? error.message : 'Login failed';
			loginError = raw === 'Invalid password' ? 'Incorrect password. Try again.' : raw;
		} finally {
			loggingIn = false;
		}
	}

	function handleLogout() {
		socket?.close();
		authenticated = false;
	}

	function handlePasswordKey(event: KeyboardEvent) {
		capsLockOn = event.getModifierState?.('CapsLock') ?? false;
	}

	function handlePasswordPointer(event: MouseEvent) {
		capsLockOn = event.getModifierState?.('CapsLock') ?? false;
	}

	function handlePasswordFocus(event: FocusEvent) {
		// Focus events don't expose modifier state in most browsers, but try
		// anyway — the click and key handlers cover the rest.
		const query = (event as unknown as Partial<KeyboardEvent>).getModifierState;
		if (typeof query === 'function') {
			try {
				capsLockOn = query.call(event, 'CapsLock');
			} catch {
				// Ignore; state stays as-is until a key or pointer event arrives.
			}
		}
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
				const pendingSelection = (Object.values(data.downloads) as Download[]).find(
					(download) => download.status === 'selecting_files'
				);
				if (
					pendingSelection &&
					!selectionDialogOpen &&
					selectionDismissedId !== pendingSelection.id
				)
					void openSelection(pendingSelection);
			}
			if (data.type === 'update') {
				downloads[data.download.id] = data.download;
				if (data.download.status !== 'selecting_files' && selectionDismissedId === data.download.id)
					selectionDismissedId = null;
				if (
					data.download.status === 'selecting_files' &&
					!selectionDialogOpen &&
					selectionDismissedId !== data.download.id
				)
					void openSelection(data.download);
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
		selectionDismissedId = null;
		selectionDialogOpen = true;
		loadingSelection = true;
		try {
			const data = await request(`/api/download/${download.id}/files`);
			selectionDownload = { ...download, files: data.files ?? [] };
			selectedFileIds = (data.files ?? [])
				.filter((file: FileEntry) => file.selected)
				.map((file: FileEntry) => file.id)
				.filter((id: number | undefined): id is number => id != null);
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Could not load torrent files');
			selectionDialogOpen = false;
		} finally {
			loadingSelection = false;
		}
	}

	function dismissSelection() {
		selectionDismissedId = selectionDownload?.id ?? null;
		selectionDialogOpen = false;
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
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
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
			showSuccess(
				action === 'pause'
					? 'Download paused.'
					: action === 'resume'
						? 'Download resumed.'
						: 'Download cancelled.'
			);
		} catch (error) {
			showError(error instanceof Error ? error.message : 'Action failed');
		} finally {
			actionInFlight = null;
		}
	}

	function isMultipart(download: Download) {
		return download.total_files > 1;
	}

	function sizeLabel(download: Download) {
		const total = download.total_size_mb || download.size_mb;
		return (
			formatAdaptiveMb(total) ||
			formatAdaptiveMb(download.current_file_size_mb) ||
			(download.rd_total_size_bytes > 0 ? formatBytes(download.rd_total_size_bytes) : '')
		);
	}

	function fileCountLabel(download: Download) {
		if (!isMultipart(download)) return '';
		return download.status === 'completed'
			? `${download.total_files} files`
			: `${download.completed_files}/${download.total_files} files`;
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

	async function clearDownload(id: string, deleteLocal = false) {
		try {
			const data = await request(`/api/download/${id}${deleteLocal ? '?delete_local=true' : ''}`, {
				method: 'DELETE'
			});
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
		request('/api/auth/session')
			.then((data) => {
				authenticated = data.authenticated;
				authChecked = true;
				if (authenticated) {
					connectWebSocket();
				}
			})
			.catch(() => {
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
		<main class="min-h-dvh bg-background text-foreground">
			<SiteHeader onLogout={handleLogout} />

			<div class="page-shell">
				<div class="page-heading">
					<div>
						<h1 class="text-[22px] leading-7 font-semibold tracking-tight text-foreground">
							Downloads
						</h1>
						<p class="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
							{#if orderedDownloads.length}
								{activeDownloads} active / {completedDownloads} done{#if failedDownloads}
									/ {failedDownloads} failed{/if}
							{:else}
								Paste a magnet or direct link to start.
							{/if}
						</p>
					</div>
				</div>

				<!-- add download -->
				<div class="console-strip px-3 py-3 sm:px-5 sm:py-4">
					<div class="mb-3 flex items-center justify-between gap-3">
						<p class="text-sm font-semibold tracking-tight text-foreground">New download</p>
						<span class="shrink-0 font-mono text-[10px] tracking-wide text-muted-foreground"
							>MAGNET / HTTP</span
						>
					</div>
					<form
						class="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center"
						onsubmit={(e) => {
							e.preventDefault();
							addDownload();
						}}
					>
						<div class="relative min-w-0 flex-1">
							<Link
								class="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground"
							/>
							<Input
								id="link-input"
								class={`h-8 border-transparent bg-transparent pr-20 pl-10 font-mono text-[13px] placeholder:font-sans placeholder:text-[13px] ${linkType === 'invalid' ? '!border-destructive/60' : ''}`}
								bind:value={link}
								placeholder="Paste magnet or link…"
								aria-label="Magnet or direct link"
								aria-invalid={linkType === 'invalid' || !!formMessage}
								aria-describedby="link-help"
								autocomplete="off"
								spellcheck="false"
							/>
							<div class="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-0.5">
								<button
									type="button"
									onclick={pasteLink}
									aria-label="Paste from clipboard"
									title="Paste from clipboard"
									class="grid size-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
								>
									<Clipboard class="size-3.5" />
								</button>
								{#if link}
									<button
										type="button"
										onclick={clearLink}
										aria-label="Clear link"
										class="grid size-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
									>
										<X class="size-3.5" />
									</button>
								{/if}
							</div>
						</div>
						<Button
							type="submit"
							class="h-8 w-full shrink-0 px-4 text-[13px] sm:w-auto"
							disabled={!canAdd || adding}
						>
							{#if adding}<CircleNotch class="size-3.5 animate-spin" />{/if}Add download
						</Button>
					</form>
					<div class="mt-3 flex min-h-4 flex-wrap items-center gap-x-3 gap-y-1">
						{#if linkType === 'magnet'}
							<span class="font-mono text-[11px] tracking-tight text-muted-foreground"
								>magnet detected</span
							>
						{:else if linkType === 'direct'}
							<span class="font-mono text-[11px] tracking-tight text-muted-foreground"
								>direct link detected</span
							>
						{/if}
						{#if formMessage}
							<p id="link-help" class="text-[13px] text-destructive" role="alert">{formMessage}</p>
						{:else if linkType === 'invalid'}
							<p id="link-help" class="text-[13px] text-destructive" role="alert">
								Enter a valid magnet or http(s) link.
							</p>
						{:else}
							<p id="link-help" class="text-[13px] text-muted-foreground">
								Sent to Real-Debrid first, then pulled to this machine.
							</p>
						{/if}
					</div>
				</div>

				<!-- queue -->
				<section aria-labelledby="downloads-heading" aria-busy={initialLoading}>
					<div class="ledger">
						<div class="border-b border-border px-4 py-4 sm:px-5">
							<div class="section-heading flex-wrap">
								<h2
									id="downloads-heading"
									class="text-sm font-semibold tracking-tight text-foreground"
								>
									Queue <span class="font-mono text-xs font-normal text-muted-foreground"
										>({orderedDownloads.length})</span
									>
								</h2>
								{#if completedDownloads > 0}
									<Button
										variant="ghost"
										size="xs"
										class="h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-destructive"
										disabled={clearingCompleted}
										onclick={() => (clearCompletedDialogOpen = true)}
									>
										{#if clearingCompleted}<CircleNotch class="size-3 animate-spin" />{:else}<Trash
												class="size-3"
											/>{/if}
										<span>Clear done</span>
									</Button>
								{/if}
							</div>
							<div class="mt-4 grid items-center gap-3 lg:grid-cols-5">
								<div class="relative min-w-0 lg:col-span-3">
									<MagnifyingGlass
										class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"
									/>
									<Input
										bind:value={query}
										placeholder="Search downloads…"
										aria-label="Search downloads"
										class="h-8 border-transparent bg-muted/60 pr-8 pl-9 text-[13px] placeholder:text-[13px]"
									/>
									{#if query}
										<button
											type="button"
											onclick={() => (query = '')}
											aria-label="Clear search"
											class="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
										>
											<X class="size-3.5" />
										</button>
									{/if}
								</div>
								<Tabs.Root
									value={activeFilter}
									onValueChange={(v) => (activeFilter = v as typeof activeFilter)}
									class="w-full lg:col-span-2"
								>
									<Tabs.List class="grid h-7 w-full grid-cols-4 bg-transparent p-0">
										<Tabs.Trigger value="all" class="min-w-0 px-1 text-xs tabular-nums"
											>All <span class="font-mono text-[11px] opacity-70"
												>{orderedDownloads.length}</span
											></Tabs.Trigger
										>
										<Tabs.Trigger value="active" class="min-w-0 px-1 text-xs tabular-nums"
											>Active <span class="font-mono text-[11px] opacity-70">{activeDownloads}</span
											></Tabs.Trigger
										>
										<Tabs.Trigger value="completed" class="min-w-0 px-1 text-xs tabular-nums"
											>Done <span class="font-mono text-[11px] opacity-70"
												>{completedDownloads}</span
											></Tabs.Trigger
										>
										<Tabs.Trigger value="failed" class="min-w-0 px-1 text-xs tabular-nums"
											>Failed <span class="font-mono text-[11px] opacity-70">{failedDownloads}</span
											></Tabs.Trigger
										>
									</Tabs.List>
								</Tabs.Root>
							</div>
						</div>
						{#if initialLoading}
							<div class="grid gap-1 py-2" aria-label="Loading downloads">
								{#each [0, 1, 2] as i}
									<div class="py-2">
										<Skeleton class="h-3.5 w-2/3" />
										<Skeleton class="mt-2 h-[5px] w-full" />
									</div>
								{/each}
							</div>
						{:else if orderedDownloads.length === 0}
							<EmptyState
								icon={Tray}
								title="Queue is empty"
								hint="Paste a link above — it will show up here with live progress."
							/>
						{:else if filteredDownloads.length === 0}
							<EmptyState
								icon={MagnifyingGlass}
								title="No matches"
								hint="Try a different search or filter."
							/>
						{:else}
							<ul>
								{#each filteredDownloads as download (download.id)}
									<li class="ledger-row row-enter group">
										<div class="flex items-center gap-1.5">
											{#if isMultipart(download)}
												<button
													type="button"
													class="grid size-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
													aria-label={`${expandedDownloads[download.id] ? 'Collapse' : 'Expand'} file list`}
													aria-expanded={expandedDownloads[download.id] ?? false}
													onclick={() => toggleExpanded(download.id)}
												>
													<CaretRight
														class={`size-3.5 transition-transform duration-200 ${expandedDownloads[download.id] ? 'rotate-90' : ''}`}
													/>
												</button>
											{:else}
												<span class="size-6 shrink-0" aria-hidden="true"></span>
											{/if}
											<div class="flex min-w-0 flex-1 items-center gap-1">
												<p
													class="min-w-0 shrink line-clamp-2 text-sm leading-5 font-medium tracking-tight"
													title={download.name}
												>
													{download.name}
												</p>
												{#if download.original_link}
													<Tooltip.Root>
														<Tooltip.Trigger>
															{#snippet child({ props })}
																<Button
																	{...props}
																	variant="ghost"
																	size="icon-sm"
																	class="size-6 shrink-0 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100"
																	aria-label={download.type === 'magnet'
																		? 'Copy magnet link'
																		: 'Copy download link'}
																	onclick={() => copyOriginalLink(download)}
																>
																	{#if copiedLinkId === download.id}<Check
																			class="size-3.5"
																		/>{:else}<Link class="size-3.5" />{/if}
																</Button>
															{/snippet}
														</Tooltip.Trigger>
														<Tooltip.Content
															>{download.type === 'magnet'
																? 'Copy magnet link'
																: 'Copy download link'}</Tooltip.Content
														>
													</Tooltip.Root>
												{/if}
											</div>
											<StatusBadge status={download.status} class="shrink-0" />
											<div class="flex shrink-0 items-center gap-0.5">
												{#if !isActive(download.status)}
													{#if download.status === 'failed' || download.status === 'rd_error'}
														<Tooltip.Root>
															<Tooltip.Trigger>
																{#snippet child({ props })}
																	<Button
																		{...props}
																		variant="ghost"
																		size="icon-sm"
																		class="size-6"
																		aria-label="Retry download"
																		onclick={() => downloadAction(download.id, 'resume')}
																		><ArrowCounterClockwise class="size-3.5" /></Button
																	>
																{/snippet}
															</Tooltip.Trigger>
															<Tooltip.Content>Retry</Tooltip.Content>
														</Tooltip.Root>
													{/if}
													{#if download.status === 'completed' && download.output_path}
														<Tooltip.Root>
															<Tooltip.Trigger>
																{#snippet child({ props })}
																	<Button
																		{...props}
																		variant="ghost"
																		size="icon-sm"
																		class="size-6"
																		aria-label="Copy save path"
																		onclick={() => copySavePath(download)}
																		>{#if copiedPathId === download.id}<Check
																				class="size-3.5"
																			/>{:else}<FolderOpen class="size-3.5" />{/if}</Button
																	>
																{/snippet}
															</Tooltip.Trigger>
															<Tooltip.Content>Copy save path</Tooltip.Content>
														</Tooltip.Root>
													{/if}
													<Tooltip.Root>
														<Tooltip.Trigger>
															{#snippet child({ props })}
																<Button
																	{...props}
																	variant="ghost"
																	size="icon-sm"
																	class="size-6"
																	aria-label="Remove download"
																	onclick={() => requestDelete(download.id)}
																	><Trash class="size-3.5" /></Button
																>
															{/snippet}
														</Tooltip.Trigger>
														<Tooltip.Content>Remove</Tooltip.Content>
													</Tooltip.Root>
												{:else}
													{#if download.status === 'selecting_files'}
														<Tooltip.Root>
															<Tooltip.Trigger>
																{#snippet child({ props })}
																	<Button
																		{...props}
																		variant="ghost"
																		size="icon-sm"
																		class="size-8"
																		aria-label="Choose files"
																		onclick={() => void openSelection(download)}
																		><FolderOpen class="size-3.5" /></Button
																	>
																{/snippet}
															</Tooltip.Trigger>
															<Tooltip.Content>Choose files</Tooltip.Content>
														</Tooltip.Root>
													{/if}
													{#if download.status === 'downloading'}
														<Tooltip.Root>
															<Tooltip.Trigger>
																{#snippet child({ props })}
																	<Button
																		{...props}
																		variant="ghost"
																		size="icon-sm"
																		class="size-6"
																		disabled={actionInFlight?.startsWith(`${download.id}:`)}
																		aria-label="Pause download"
																		onclick={() => downloadAction(download.id, 'pause')}
																		><Pause class="size-3.5" /></Button
																	>
																{/snippet}
															</Tooltip.Trigger>
															<Tooltip.Content>Pause</Tooltip.Content>
														</Tooltip.Root>
													{:else if download.status === 'paused'}
														<Tooltip.Root>
															<Tooltip.Trigger>
																{#snippet child({ props })}
																	<Button
																		{...props}
																		variant="ghost"
																		size="icon-sm"
																		class="size-6"
																		disabled={actionInFlight?.startsWith(`${download.id}:`)}
																		aria-label="Resume download"
																		onclick={() => downloadAction(download.id, 'resume')}
																		><Play class="size-3.5" /></Button
																	>
																{/snippet}
															</Tooltip.Trigger>
															<Tooltip.Content>Resume</Tooltip.Content>
														</Tooltip.Root>
													{/if}
													<Tooltip.Root>
														<Tooltip.Trigger>
															{#snippet child({ props })}
																<Button
																	{...props}
																	variant="ghost"
																	size="icon-sm"
																	class="size-6"
																	disabled={actionInFlight?.startsWith(`${download.id}:`)}
																	aria-label="Cancel download"
																	onclick={() => requestCancel(download.id)}
																	><X class="size-3.5" /></Button
																>
															{/snippet}
														</Tooltip.Trigger>
														<Tooltip.Content>Cancel</Tooltip.Content>
													</Tooltip.Root>
												{/if}
											</div>
										</div>
										<div class="pl-[30px]">
											<div
												class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs tabular-nums text-muted-foreground"
											>
												{#if fileCountLabel(download)}<span>{fileCountLabel(download)}</span>{/if}
												{#if sizeLabel(download)}<span>{sizeLabel(download)}</span>{/if}
												{#if formatSpeed(download)}<span class="text-foreground"
														>{formatSpeed(download)}</span
													>{/if}
												{#if download.seeders != null && (download.status === 'rd_downloading' || download.status === 'processing_torrent')}
													<span>{download.seeders} seeders</span>
												{/if}
												<span
													class="ml-auto font-mono text-xs font-medium text-foreground tabular-nums"
													>{download.progress.toFixed(0)}%</span
												>
											</div>
											{#if isActive(download.status)}
												<div class={railClass(download.status)} aria-hidden="true">
													<span style={`width: ${Math.min(Math.max(download.progress, 0), 100)}%`}
													></span>
												</div>
											{/if}
											{#if isMultipart(download) && expandedDownloads[download.id]}
												{#if download.status === 'completed'}
													<ul
														aria-label="Downloaded files"
														class="mt-3 grid gap-0.5 rounded-lg border border-border px-3 py-2"
													>
														{#each download.files ?? [] as file}
															<li class="flex items-center gap-2 py-1 text-[11px]">
																<Check class="size-3.5 shrink-0 text-muted-foreground" />
																<span
																	class="min-w-0 flex-1 truncate font-mono text-muted-foreground"
																	title={file.name}>{fileName(file)}</span
																>
																<span class="shrink-0 font-mono text-muted-foreground tabular-nums"
																	>{fileSize(file)}</span
																>
															</li>
														{/each}
													</ul>
												{:else}
													<ul
														aria-label="Download file progress"
														class="mt-3 grid gap-2.5 rounded-lg border border-border px-3 py-2.5"
													>
														{#each download.files ?? [] as file}
															<li>
																<div class="flex items-baseline gap-2 text-[11px]">
																	<span
																		class="min-w-0 flex-1 line-clamp-2 font-mono text-muted-foreground"
																		title={file.name}>{fileName(file)}</span
																	>
																	<span
																		class="shrink-0 font-mono text-muted-foreground tabular-nums"
																		>{fileSize(file)}{#if download.status !== 'rd_downloading'}
																			· {(file.progress ?? 0).toFixed(0)}%{/if}</span
																	>
																</div>
																{#if download.status !== 'rd_downloading'}
																	<Progress
																		value={file.progress ?? 0}
																		max={100}
																		class={`mt-1.5 h-[3px] ${barClass(file.status ?? download.status)}`}
																		aria-label={`${fileName(file)} progress: ${(file.progress ?? 0).toFixed(0)} percent`}
																	/>
																{/if}
															</li>
														{/each}
													</ul>
												{/if}
											{/if}
											{#if download.output_path}
												<p
													class="mt-1.5 truncate font-mono text-[11px] text-muted-foreground/70"
													title={pathLabel(download.output_path)}
												>
													{truncateMiddle(pathLabel(download.output_path), 56)}
												</p>
											{/if}

											{#if download.error_message && download.status !== 'cancelled'}
												<Alert.Root variant="destructive" class="mt-2.5 border-destructive/30">
													<Alert.Description
														class="flex items-start gap-1.5 text-xs leading-relaxed"
														>{errorLabel(download)}</Alert.Description
													>
												</Alert.Root>
											{/if}
										</div>
									</li>
								{/each}
							</ul>
						{/if}
					</div>
				</section>
			</div>
		</main>
		<Dialog.Root bind:open={clearCompletedDialogOpen}>
			<Dialog.Content class="sm:max-w-[380px]">
				<div class="px-5 pt-5 pr-12 pb-4">
					<Dialog.Header>
						<div class="flex items-start gap-3">
							<span
								class="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground"
							>
								<Trash class="size-3.5" />
							</span>
							<div class="grid gap-1 pt-0.5">
								<Dialog.Title>Clear completed?</Dialog.Title>
								<Dialog.Description
									>{completedDownloads} completed {completedDownloads === 1
										? 'download'
										: 'downloads'} will be removed from the queue. Local files are kept.</Dialog.Description
								>
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
							<span
								class="grid size-8 shrink-0 place-items-center rounded-full bg-destructive/10 text-destructive"
							>
								<WarningCircle class="size-3.5" />
							</span>
							<div class="grid gap-1 pt-0.5">
								<Dialog.Title>Cancel download?</Dialog.Title>
								<Dialog.Description
									>This stops the download but keeps it in the list.</Dialog.Description
								>
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
					<Button variant="destructive" size="sm" class="h-8" onclick={confirmCancel}
						>Cancel download</Button
					>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>

		<Dialog.Root bind:open={selectionDialogOpen}>
			<Dialog.Content showCloseButton={true} class="gap-3 p-4 sm:max-w-[520px]">
				<Dialog.Header>
					<Dialog.Title>Select files for {selectionDownload?.name ?? 'torrent'}</Dialog.Title>
					<Dialog.Description
						>You must choose at least one file before this torrent can start.</Dialog.Description
					>
				</Dialog.Header>
				<div class="max-h-[55vh] overflow-y-auto">
					{#if loadingSelection}
						<div
							class="flex items-center justify-center gap-2 py-8 text-[13px] text-muted-foreground"
						>
							<CircleNotch class="size-3.5 animate-spin" /> Loading files…
						</div>
					{:else}
						<div class="grid gap-1">
							{#each selectionDownload?.files ?? [] as file}
								{@const checked = file.id != null && selectedFileIds.includes(file.id)}
								<button
									type="button"
									role="checkbox"
									aria-checked={checked}
									onclick={() => toggleFile(file.id)}
									class="flex cursor-pointer items-center gap-3 rounded px-2 py-2 text-left text-[13px] hover:bg-muted"
								>
									<Checkbox
										{checked}
										tabindex={-1}
										class="pointer-events-none"
										aria-hidden="true"
									/>
									<span class="min-w-0 flex-1 truncate" title={file.name}>{fileName(file)}</span>
									<span class="shrink-0 font-mono text-xs text-muted-foreground"
										>{fileSize(file)}</span
									>
								</button>
							{/each}
						</div>
					{/if}
				</div>
				<Dialog.Footer class="flex-row justify-between">
					<Button variant="outline" size="sm" onclick={dismissSelection}>Choose later</Button>
					<Button
						size="sm"
						disabled={loadingSelection || submittingSelection || !selectedFileIds.length}
						onclick={submitSelection}
						>{submittingSelection
							? 'Starting…'
							: `Start with ${selectedFileIds.length} selected`}</Button
					>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>

		<Dialog.Root bind:open={deleteDialogOpen}>
			<Dialog.Content class="gap-0 p-0 sm:max-w-[420px]">
				<div class="px-5 pt-5 pr-12 pb-4">
					<Dialog.Header>
						<Dialog.Title>Remove download?</Dialog.Title>
						<Dialog.Description
							>The queue entry will be removed. Local files are kept unless you choose to delete
							them.</Dialog.Description
						>
					</Dialog.Header>
				</div>
				<div class="px-5 pb-4">
					<button
						type="button"
						role="checkbox"
						aria-checked={deleteLocalFiles}
						onclick={() => (deleteLocalFiles = !deleteLocalFiles)}
						class="flex cursor-pointer items-center gap-2 text-left text-[13px]"
					>
						<Checkbox
							checked={deleteLocalFiles}
							tabindex={-1}
							class="pointer-events-none"
							aria-hidden="true"
						/> Delete local files and partial data
					</button>
				</div>
				<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
					<Dialog.Close>
						{#snippet child({ props })}<Button variant="outline" size="sm" {...props}>Keep</Button
							>{/snippet}
					</Dialog.Close>
					<Button variant="destructive" size="sm" onclick={confirmDelete}>Remove</Button>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>
	</Tooltip.Provider>
{:else if authChecked}
	<main class="grid min-h-dvh place-items-center bg-background px-4 py-12 text-foreground sm:py-16">
		<div class="w-full max-w-sm">
			<div class="mb-8 px-1">
				<span class="text-xs font-medium tracking-normal text-muted-foreground">RMT-Debrid</span>
			</div>
			<div class="ledger p-5 sm:p-6">
				<h1 class="text-lg font-semibold tracking-tight">Sign in</h1>
				<p class="mt-1 text-[13px] text-muted-foreground">
					Enter the household password to continue.
				</p>
				<form
					class="mt-5 grid gap-3"
					onsubmit={(event) => {
						event.preventDefault();
						login();
					}}
				>
					<div class="grid gap-1.5">
						<label for="login-password" class="text-[13px] font-medium">Password</label>
						<div class="relative">
							<Input
								id="login-password"
								type={showPassword ? 'text' : 'password'}
								bind:value={password}
								autocomplete="current-password"
								autofocus
								enterkeyhint="go"
								aria-invalid={loginError ? 'true' : undefined}
								aria-describedby={loginError ? 'login-error' : undefined}
								class={`h-10 border-transparent bg-muted/60 ${capsLockOn ? 'pr-16' : 'pr-10'} ${loginError ? '!border-destructive/60 !bg-destructive/[0.04]' : ''}`}
								onkeydown={handlePasswordKey}
								onkeyup={handlePasswordKey}
								onclick={handlePasswordPointer}
								onfocus={handlePasswordFocus}
								onblur={() => (capsLockOn = false)}
								oninput={() => {
									if (loginError) loginError = '';
								}}
							/>
							<div class="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-0.5">
								{#if capsLockOn}
									<span
										role="status"
										title="Caps lock is on"
										aria-label="Caps lock is on"
										class="grid size-7 place-items-center text-muted-foreground"
									>
										<ArrowFatLineUp class="size-4" aria-hidden="true" />
									</span>
								{/if}
								<button
									type="button"
									onclick={() => (showPassword = !showPassword)}
									aria-label={showPassword ? 'Hide password' : 'Show password'}
									aria-pressed={showPassword}
									class="grid size-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
								>
									{#if showPassword}<EyeSlash class="size-4" />{:else}<Eye class="size-4" />{/if}
								</button>
							</div>
						</div>
					</div>
					{#if loginError}
						<div
							id="login-error"
							role="alert"
							class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/[0.06] px-3 py-2.5 text-[13px] leading-5 text-destructive"
						>
							<WarningCircle class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
							<p>{loginError}</p>
						</div>
					{/if}
					<Button type="submit" class="h-10 w-full" disabled={loggingIn || !password}
						>{#if loggingIn}<CircleNotch class="size-4 animate-spin" /> Signing in…{:else}Sign in{/if}</Button
					>
				</form>
			</div>
		</div>
	</main>
{:else}
	<main class="grid min-h-dvh place-items-center bg-background px-4 text-foreground">
		<CircleNotch class="size-5 animate-spin text-muted-foreground" aria-label="Loading" />
	</main>
{/if}
