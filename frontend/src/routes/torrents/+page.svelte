<script lang="ts">
	import { onMount } from 'svelte';
	import {
		ArrowDown,
		Check,
		CaretLeft,
		CaretRight,
		CaretDoubleLeft,
		WarningCircle,
		Download,
		Tray,
		Info,
		CircleNotch,
		Play,
		ArrowClockwise,
		MagnifyingGlass,
		Trash,
		X
	} from 'phosphor-svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Switch } from '$lib/components/ui/switch';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { Label } from '$lib/components/ui/label';
	import StatusBadge from '$lib/components/status-badge.svelte';
	import EmptyState from '$lib/components/empty-state.svelte';
	import { statusKind } from '$lib/status';
	import { formatBytes, formatDateTimeCompact } from '$lib/format';
	import { toast } from 'svelte-sonner';
	import SiteHeader from '$lib/components/site-header.svelte';

	type RdTorrent = {
		id: string;
		filename: string;
		hash?: string;
		bytes: number;
		host?: string;
		progress: number;
		status: string;
		added?: string;
		links?: string[];
		ended?: string;
		speed?: number;
		seeders?: number;
	};
	type RdFile = {
		id?: number;
		path?: string;
		bytes?: number;
		selected?: number;
		status?: string;
		individually_downloadable?: boolean;
	};

	let torrents = $state<RdTorrent[]>([]);
	let loading = $state(true);
	let refreshing = $state(false);
	let error = $state('');
	let query = $state('');
	let activeOnly = $state(false);
	let page = $state(1);
	let hasMore = $state(false);
	let totalCount = $state<number | null>(null);
	let pageCount = $state<number | null>(null);
	const PAGE_SIZE = 50;
	let authChecked = $state(false);
	let authenticated = $state(false);
	let importingId = $state<string | null>(null);
	let importedIds = $state<string[]>([]);
	let deleteRdDialogOpen = $state(false);
	let pendingDeleteRd = $state<RdTorrent | null>(null);
	let deletingRd = $state(false);
	let expandedTorrentId = $state<string | null>(null);
	let torrentFiles = $state<Record<string, RdFile[]>>({});
	let filesLoading = $state<string | null>(null);
	let filesError = $state<Record<string, string>>({});
	let downloadingFileId = $state<string | null>(null);
	type StreamState = { status: 'loading' | 'ready' };
	let streamingLinks = $state<Record<string, StreamState>>({});
	type StreamOptions = {
		streamable: boolean;
		streaming_url: string;
		media_infos?: Record<string, unknown>;
	};
	let streamingData = $state<Record<string, StreamOptions>>({});
	let streamDialogOpen = $state(false);
	let activeStreamTorrent = $state<RdTorrent | null>(null);
	let activeStreamFile = $state<RdFile | null>(null);
	let activeStreamKey = $state<string | null>(null);
	let streamDialogLoading = $state(false);
	const inactiveStatuses = ['downloaded', 'error', 'magnet_error', 'virus', 'dead'];

	const filteredTorrents = $derived(
		torrents.filter((torrent) => {
			if (activeOnly && inactiveStatuses.includes(torrent.status)) return false;
			const q = query.trim().toLowerCase();
			if (!q) return true;
			return torrent.filename.toLowerCase().includes(q) || torrent.status.toLowerCase().includes(q);
		})
	);
	const torrentCountLabel = $derived(
		filteredTorrents.length === 0
			? '0 matching torrents'
			: totalCount != null && !query.trim()
				? `${filteredTorrents.length} of ${totalCount} torrents`
				: `${filteredTorrents.length} matching torrents`
	);

	function formatSpeed(bps?: number) {
		if (!bps || bps <= 0) return '';
		const mbps = bps / 1024 / 1024;
		if (mbps < 1) return `${(mbps * 1024).toFixed(0)} KB/s`;
		return `${mbps.toFixed(1)} MB/s`;
	}

	function statusClass(status: string) {
		const kind = statusKind(status);
		if (kind === 'destructive') return 'text-destructive';
		if (kind === 'success') return 'text-foreground';
		return 'text-muted-foreground';
	}

	function railClass(status: string) {
		const kind = statusKind(status);
		if (kind === 'success') return 'ledger-rail is-done';
		if (kind === 'destructive') return 'ledger-rail is-failed';
		return 'ledger-rail';
	}

	function metaParts(torrent: RdTorrent) {
		const parts: string[] = [];
		if (torrent.bytes > 0) parts.push(formatBytes(torrent.bytes));
		const speed = formatSpeed(torrent.speed);
		if (speed) parts.push(speed);
		if (torrent.seeders != null && torrent.status === 'downloading') {
			parts.push(`${torrent.seeders} seeders`);
		}
		const added = formatDateTimeCompact(torrent.added);
		if (added) parts.push(added);
		return parts;
	}

	function mediaSummary(mediaInfos: unknown): {
		type?: string;
		duration?: number;
		audio: Array<{ id: string; label: string }>;
		subs: Array<{ id: string; label: string }>;
	} {
		const summary: {
			type?: string;
			duration?: number;
			audio: Array<{ id: string; label: string }>;
			subs: Array<{ id: string; label: string }>;
		} = { audio: [], subs: [] };
		if (!mediaInfos || typeof mediaInfos !== 'object') return summary;
		const info = mediaInfos as Record<string, unknown>;
		if (typeof info.type === 'string' && info.type) summary.type = info.type;
		if (typeof info.duration === 'number') summary.duration = info.duration;
		const details = info.details;
		if (details && typeof details === 'object') {
			const record = details as Record<string, unknown>;
			summary.audio = trackEntries(record.audio);
			summary.subs = trackEntries(record.subtitles);
		}
		return summary;
	}

	function trackEntries(tracks: unknown): Array<{ id: string; label: string }> {
		if (!tracks || typeof tracks !== 'object') return [];
		const rows: Array<{ id: string; label: string }> = [];
		for (const [id, track] of Object.entries(tracks as Record<string, unknown>)) {
			if (!track || typeof track !== 'object') continue;
			const record = track as Record<string, unknown>;
			const lang =
				typeof record.lang === 'string' && record.lang
					? record.lang
					: typeof record.lang_iso === 'string'
						? record.lang_iso
						: id;
			const extras: string[] = [];
			if (typeof record.codec === 'string' && record.codec) extras.push(record.codec);
			if (typeof record.channels === 'number' && record.channels)
				extras.push(`${record.channels}ch`);
			if (typeof record.sampling === 'number' && record.sampling)
				extras.push(`${record.sampling}Hz`);
			if (typeof record.type === 'string' && record.type) extras.push(record.type);
			if (typeof record.width === 'number' && typeof record.height === 'number')
				extras.push(`${record.width}x${record.height}`);
			rows.push({ id, label: extras.length > 0 ? `${lang} (${extras.join(' · ')})` : `${lang}` });
		}
		return rows;
	}

	async function openStreamingDialog(torrent: RdTorrent, file: RdFile) {
		if (file.id == null || !file.individually_downloadable) return;
		const key = `${torrent.id}:${file.id}`;
		if (streamDialogLoading) return;
		delete streamingData[key];
		streamingLinks = { ...streamingLinks, [key]: { status: 'loading' } };
		streamDialogLoading = true;
		activeStreamTorrent = torrent;
		activeStreamFile = file;
		activeStreamKey = key;
		streamDialogOpen = true;
		try {
			const response = await fetch(
				`/api/rd/torrents/${encodeURIComponent(torrent.id)}/files/${file.id}/streaming`
			);
			const data = (await response.json().catch(() => null)) as {
				streamable?: unknown;
				streaming_url?: unknown;
				media_infos?: unknown;
				detail?: string;
			} | null;
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error(data?.detail ?? 'Could not load streaming links.');
			}
			if (data?.streamable !== true) {
				streamingLinks = { ...streamingLinks, [key]: { status: 'ready' } };
				toast.info('Streaming is not available for this file.');
				return;
			}
			const options: StreamOptions = {
				streamable: true,
				streaming_url: typeof data.streaming_url === 'string' ? data.streaming_url : '',
				media_infos:
					data.media_infos && typeof data.media_infos === 'object'
						? (data.media_infos as Record<string, unknown>)
						: undefined
			};
			if (!options.streaming_url) {
				streamingLinks = { ...streamingLinks, [key]: { status: 'ready' } };
				toast.info('Streaming is not available for this file.');
				return;
			}
			streamingData = { ...streamingData, [key]: options };
			streamingLinks = { ...streamingLinks, [key]: { status: 'ready' } };
		} catch (err) {
			streamingLinks = { ...streamingLinks, [key]: { status: 'ready' } };
			toast.error(err instanceof Error ? err.message : 'Could not load streaming links.');
		} finally {
			streamDialogLoading = false;
		}
	}

	async function openStreamingPage(torrent: RdTorrent, file: RdFile) {
		if (file.id == null || !file.individually_downloadable) return;
		const popup = window.open('about:blank', '_blank');
		if (!popup) {
			toast.error('Allow pop-ups to open the Real-Debrid player.');
			return;
		}
		try {
			const response = await fetch(
				`/api/rd/torrents/${encodeURIComponent(torrent.id)}/files/${file.id}/streaming`
			);
			const data = (await response.json().catch(() => null)) as {
				streamable?: unknown;
				streaming_url?: unknown;
				detail?: string;
			} | null;
			if (!response.ok) throw new Error(data?.detail ?? 'Could not open the Real-Debrid player.');
			if (
				data?.streamable !== true ||
				typeof data.streaming_url !== 'string' ||
				!data.streaming_url
			) {
				throw new Error('Streaming is not available for this file.');
			}
			popup.location.href = data.streaming_url;
		} catch (err) {
			popup.close();
			toast.error(err instanceof Error ? err.message : 'Could not open the Real-Debrid player.');
		}
	}

	async function toggleTorrentFiles(torrent: RdTorrent) {
		if (expandedTorrentId === torrent.id) {
			expandedTorrentId = null;
			return;
		}
		expandedTorrentId = torrent.id;
		if (torrent.id in torrentFiles) return;
		filesError = { ...filesError, [torrent.id]: '' };
		filesLoading = torrent.id;
		try {
			const response = await fetch(`/api/rd/torrents/${encodeURIComponent(torrent.id)}`);
			const data = (await response.json().catch(() => null)) as {
				files?: unknown;
				detail?: string;
			} | null;
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error(data?.detail ?? 'Could not load torrent files.');
			}
			torrentFiles = {
				...torrentFiles,
				[torrent.id]: Array.isArray(data?.files) ? (data.files as RdFile[]) : []
			};
		} catch (err) {
			filesError = {
				...filesError,
				[torrent.id]: err instanceof Error ? err.message : 'Could not load torrent files.'
			};
		} finally {
			if (filesLoading === torrent.id) filesLoading = null;
		}
	}

	function retryTorrentFiles(torrent: RdTorrent) {
		torrentFiles = Object.fromEntries(
			Object.entries(torrentFiles).filter(([id]) => id !== torrent.id)
		);
		filesError = { ...filesError, [torrent.id]: '' };
		expandedTorrentId = null;
		void toggleTorrentFiles(torrent);
	}

	async function downloadTorrentFile(torrent: RdTorrent, file: RdFile) {
		if (file.id == null || downloadingFileId) return;
		const key = `${torrent.id}:${file.id}`;
		downloadingFileId = key;
		try {
			const response = await fetch(
				`/api/rd/torrents/${encodeURIComponent(torrent.id)}/files/${file.id}/download`,
				{ method: 'POST' }
			);
			const data = (await response.json().catch(() => null)) as { detail?: string } | null;
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error(data?.detail ?? 'Could not add file to downloads.');
			}
			toast.success('File added to downloads.');
		} catch (err) {
			toast.error(err instanceof Error ? err.message : 'Could not add file to downloads.');
		} finally {
			downloadingFileId = null;
		}
	}

	async function fetchTorrents() {
		if (!authenticated) return;
		if (!torrents.length) loading = true;
		else refreshing = true;
		error = '';
		try {
			const params = new URLSearchParams({ limit: String(PAGE_SIZE), page: String(page) });
			if (activeOnly) params.set('filter', 'active');
			const response = await fetch(`/api/rd/torrents?${params}`);
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error((data as { detail?: string } | null)?.detail ?? 'Could not load torrents.');
			}
			const payload = data as
				| {
						torrents?: unknown;
						has_more?: unknown;
						has_next?: unknown;
						total?: unknown;
						page_count?: unknown;
				  }
				| RdTorrent[]
				| null;
			if (Array.isArray(payload)) {
				// Legacy backend shape: bare list with no pagination metadata.
				torrents = payload;
				hasMore = payload.length >= PAGE_SIZE;
				totalCount = null;
				pageCount = null;
			} else {
				const list = payload?.torrents;
				torrents = Array.isArray(list) ? list : [];
				hasMore = payload?.has_next === true || payload?.has_more === true;
				totalCount = typeof payload?.total === 'number' ? payload.total : null;
				pageCount = typeof payload?.page_count === 'number' ? payload.page_count : null;
			}
		} catch (err) {
			error = err instanceof Error ? err.message : 'Could not load torrents.';
		} finally {
			loading = false;
			refreshing = false;
		}
	}

	function toggleActiveOnly() {
		activeOnly = !activeOnly;
		page = 1;
		void fetchTorrents();
	}

	function handleLogout() {
		authenticated = false;
		torrents = [];
		hasMore = false;
		totalCount = null;
		pageCount = null;
	}

	function goToPage(next: number) {
		if (next < 1 || next === page || loading || refreshing) return;
		page = next;
		window.scrollTo({ top: 0, behavior: 'smooth' });
		void fetchTorrents();
	}

	async function importTorrent(torrent: RdTorrent) {
		if (importingId) return;
		importingId = torrent.id;
		try {
			const response = await fetch(`/api/rd/torrents/${encodeURIComponent(torrent.id)}/import`, {
				method: 'POST'
			});
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error(
					(data as { detail?: string } | null)?.detail ?? 'Could not add torrent to downloads.'
				);
			}
			const added = (data as { added?: unknown } | null)?.added;
			importedIds = [...importedIds, torrent.id];
			toast.success(
				typeof added === 'number' && added !== 1
					? `Added ${added} selected files to downloads.`
					: 'Selected files added to downloads.'
			);
		} catch (err) {
			toast.error(err instanceof Error ? err.message : 'Could not add torrent to downloads.');
		} finally {
			importingId = null;
		}
	}

	function requestDeleteRd(torrent: RdTorrent) {
		pendingDeleteRd = torrent;
		deleteRdDialogOpen = true;
	}

	async function confirmDeleteRd() {
		if (!pendingDeleteRd || deletingRd) return;
		deletingRd = true;
		try {
			const response = await fetch(`/api/rd/torrents/${pendingDeleteRd.id}`, { method: 'DELETE' });
			const data = await response.json().catch(() => null);
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error(
					(data as { detail?: string } | null)?.detail ?? 'Could not delete torrent.'
				);
			}
			toast.success('Torrent deleted from Real-Debrid.');
			deleteRdDialogOpen = false;
			pendingDeleteRd = null;
			if (torrents.length <= 1 && page > 1) {
				goToPage(page - 1);
			} else {
				void fetchTorrents();
			}
		} catch (err) {
			toast.error(err instanceof Error ? err.message : 'Could not delete torrent.');
		} finally {
			deletingRd = false;
		}
	}

	onMount(() => {
		fetch('/api/auth/session')
			.then(async (response) => {
				const data = await response.json().catch(() => ({}));
				authenticated = data.authenticated === true;
				authChecked = true;
				if (authenticated) void fetchTorrents();
				else loading = false;
			})
			.catch(() => {
				authChecked = true;
				loading = false;
				error = 'Unable to contact the server.';
			});
	});
</script>

<svelte:head>
	<title>Torrents — RMT-Debrid</title>
	<meta name="description" content="Torrents currently on Real-Debrid." />
</svelte:head>

{#if !authChecked}
	<main class="grid min-h-dvh place-items-center bg-background px-4 text-foreground">
		<CircleNotch class="size-5 animate-spin text-muted-foreground" aria-label="Loading" />
	</main>
{:else if !authenticated}
	<main class="grid min-h-dvh place-items-center bg-background px-4 text-foreground">
		<Card class="w-full max-w-sm">
			<CardHeader>
				<CardTitle>Torrents</CardTitle>
				<p class="text-sm text-muted-foreground">Sign in to view your Real-Debrid torrents.</p>
			</CardHeader>
			<CardContent>
				<Button href="/" class="w-full">Go to sign in</Button>
			</CardContent>
		</Card>
	</main>
{:else}
	<Tooltip.Provider>
		<main class="min-h-dvh bg-background text-foreground">
			<SiteHeader onLogout={handleLogout} />

			<div class="page-shell">
				<div class="page-heading">
					<div>
						<h1 class="text-[22px] leading-7 font-semibold tracking-tight text-foreground">
							Torrents
						</h1>
						<p class="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
							Everything stored in your Real-Debrid account.
						</p>
					</div>
				</div>
				<section aria-labelledby="torrents-heading" aria-busy={loading || refreshing}>
					<div class="ledger">
						<div class="border-b border-border px-4 pt-3 pb-4 sm:px-5 sm:py-4">
							<div class="section-heading flex-wrap" style="min-height: 0;">
								<div class="flex items-center gap-2">
									<h2
										id="torrents-heading"
										class="text-sm font-semibold tracking-tight text-foreground"
									>
										Real-Debrid torrents
									</h2>
									<Button
										variant="ghost"
										size="icon-xs"
										class="size-5 shrink-0"
										aria-label="Refresh torrents"
										onclick={() => void fetchTorrents()}
										disabled={loading || refreshing}
									>
										<ArrowClockwise class={`size-3 ${refreshing ? 'animate-spin' : ''}`} />
									</Button>
								</div>
							</div>
							<div class="mt-4 flex min-w-0 items-center gap-3">
								<div class="relative min-w-0 flex-1">
									<MagnifyingGlass
										class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"
									/>
									<Input
										bind:value={query}
										placeholder="Filter this page…"
										aria-label="Filter torrents on this page"
										class="h-8 border-transparent bg-muted/60 pr-8 pl-9 text-[13px] placeholder:text-[13px]"
									/>
									{#if query}
										<button
											type="button"
											onclick={() => (query = '')}
											aria-label="Clear filter"
											class="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
										>
											<X class="size-3.5" />
										</button>
									{/if}
								</div>
								<div class="flex shrink-0 items-center gap-2">
									<Switch
										id="active-only"
										checked={activeOnly}
										onCheckedChange={() => toggleActiveOnly()}
										aria-label="Show active only"
									/>
									<Label
										for="active-only"
										class="text-xs font-medium whitespace-nowrap text-muted-foreground"
										>Active only</Label
									>
								</div>
							</div>
						</div>

						<div class="px-2 py-2 sm:px-3">
							{#if loading}
								<div class="grid gap-1 py-2" aria-label="Loading torrents">
									{#each [0, 1, 2] as i (i)}
										<div class="py-2">
											<Skeleton class="h-3.5 w-2/3" />
											<Skeleton class="mt-2 h-[5px] w-full" />
										</div>
									{/each}
								</div>
							{:else if error}
								<div class="py-4">
									<Alert.Root variant="destructive" class="flex items-center justify-between gap-3">
										<Alert.Description class="min-w-0 flex-1">{error}</Alert.Description>
										<Button
											variant="outline"
											size="xs"
											class="h-7 shrink-0"
											onclick={() => void fetchTorrents()}
											disabled={refreshing}>Retry</Button
										>
									</Alert.Root>
								</div>
							{:else if torrents.length === 0 && !activeOnly && !query.trim()}
								<EmptyState
									icon={Tray}
									title={activeOnly
										? 'No active torrents on Real-Debrid'
										: 'No torrents on Real-Debrid'}
								/>
							{:else if filteredTorrents.length === 0}
								<EmptyState
									icon={MagnifyingGlass}
									title={activeOnly ? 'No active torrents' : 'No torrents match this search'}
									hint={activeOnly
										? 'There are no in-progress torrents on the current page.'
										: 'Try a different search term or clear the filter.'}
									actionLabel={activeOnly ? 'Show all torrents' : 'Clear search'}
									onAction={() => {
										if (activeOnly) {
											activeOnly = false;
											page = 1;
											void fetchTorrents();
										} else {
											query = '';
										}
									}}
								/>
							{:else}
								<ul>
									{#each filteredTorrents as torrent (torrent.id)}
										<li class="ledger-row row-enter group">
											<div class="flex items-start gap-1.5">
												<div class="flex h-7 w-6 shrink-0 items-center justify-center">
													<button
														type="button"
														class="grid size-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-ring"
														aria-expanded={expandedTorrentId === torrent.id}
														aria-label={`${expandedTorrentId === torrent.id ? 'Hide' : 'Show'} files for ${torrent.filename}`}
														onclick={() => void toggleTorrentFiles(torrent)}
													>
														<CaretRight
															class={`size-3.5 transition-transform duration-200 ${expandedTorrentId === torrent.id ? 'rotate-90' : ''}`}
														/>
													</button>
												</div>
												<div class="min-w-0 flex-1">
													<div class="flex h-7 items-center justify-between gap-2 sm:gap-3">
														<div class="flex min-w-0 flex-1 items-center gap-2">
															<p
																class="min-w-0 flex-1 truncate text-sm leading-5 font-medium tracking-tight"
																title={torrent.filename}
															>
																{torrent.filename}
															</p>
															<span class="hidden shrink-0 sm:inline-flex"
																><StatusBadge status={torrent.status} /></span
															>
															<span
																class={`inline-flex shrink-0 items-center sm:hidden ${statusClass(torrent.status)}`}
																aria-label={torrent.status.replaceAll('_', ' ')}
																title={torrent.status.replaceAll('_', ' ')}
															>
																{#if torrent.status === 'downloaded'}
																	<Check class="size-4" aria-hidden="true" />
																{:else if ['error', 'magnet_error', 'virus', 'dead'].includes(torrent.status)}
																	<WarningCircle class="size-4" aria-hidden="true" />
																{:else if torrent.status === 'downloading'}
																	<ArrowDown class="size-4" aria-hidden="true" />
																{:else}
																	<CircleNotch class="size-4" aria-hidden="true" />
																{/if}
															</span>
														</div>
														<div class="flex shrink-0 items-center gap-0.5">
															{#if torrent.status === 'downloaded'}
																{#if importedIds.includes(torrent.id)}
																	<span
																		class="grid size-7 place-items-center text-foreground"
																		title="Added to downloads"
																		aria-label="Added to downloads"
																	>
																		<Check class="size-3.5" />
																	</span>
																{:else}
																	<Tooltip.Root>
																		<Tooltip.Trigger>
																			{#snippet child({ props })}
																				<Button
																					{...props}
																					variant="ghost"
																					size="icon-sm"
																					class="size-7"
																					aria-label={`Add ${torrent.filename} to downloads`}
																					disabled={importingId === torrent.id}
																					onclick={() => void importTorrent(torrent)}
																				>
																					{#if importingId === torrent.id}
																						<CircleNotch class="size-3.5 animate-spin" />
																					{:else}
																						<Download class="size-3.5" />
																					{/if}
																				</Button>
																			{/snippet}
																		</Tooltip.Trigger>
																		<Tooltip.Content>Add to downloads</Tooltip.Content>
																	</Tooltip.Root>
																{/if}
															{/if}
															<Tooltip.Root>
																<Tooltip.Trigger>
																	{#snippet child({ props })}
																		<Button
																			{...props}
																			variant="ghost"
																			size="icon-sm"
																			class="size-7"
																			aria-label={`Delete ${torrent.filename} from Real-Debrid`}
																			onclick={() => requestDeleteRd(torrent)}
																		>
																			<Trash class="size-3.5" />
																		</Button>
																	{/snippet}
																</Tooltip.Trigger>
																<Tooltip.Content>Delete from Real-Debrid</Tooltip.Content>
															</Tooltip.Root>
														</div>
													</div>
													<div
														class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs tabular-nums text-muted-foreground"
													>
														{#each metaParts(torrent) as part}
															<span>{part}</span>
														{/each}
														{#if torrent.status !== 'downloaded'}
															<span class="ml-auto shrink-0 text-xs font-medium text-foreground">
																{Math.round(torrent.progress)}%
															</span>
														{/if}
													</div>
													{#if torrent.status !== 'downloaded'}
														<div class={railClass(torrent.status)} aria-hidden="true">
															<span
																style={`width: ${Math.min(Math.max(torrent.progress, 0), 100)}%`}
															></span>
														</div>
													{/if}
													{#if expandedTorrentId === torrent.id}
														<div class="mt-3 rounded-lg border border-border px-3 py-2">
															{#if filesLoading === torrent.id}
																<p
																	class="flex items-center gap-2 px-1 py-2 text-xs text-muted-foreground"
																>
																	<CircleNotch class="size-3.5 animate-spin" /> Loading files…
																</p>
															{:else if filesError[torrent.id]}
																<div class="flex items-center justify-between gap-3 px-1 py-1">
																	<p
																		class="min-w-0 flex-1 text-xs leading-relaxed text-destructive"
																	>
																		{filesError[torrent.id]}
																	</p>
																	<Button
																		variant="ghost"
																		size="xs"
																		class="h-7 shrink-0"
																		onclick={() => retryTorrentFiles(torrent)}>Retry</Button
																	>
																</div>
															{:else if torrentFiles[torrent.id]?.length === 0}
																<p class="px-1 py-2 text-xs text-muted-foreground">
																	No constituent files reported.
																</p>
															{:else}
																<ul class="divide-y divide-border/50">
																	{#each torrentFiles[torrent.id] ?? [] as file (file.id ?? file.path)}
																		<li class="flex items-center gap-2 py-1.5 text-xs">
																			<span
																				class="min-w-0 flex-1 truncate font-mono text-muted-foreground"
																				title={file.path ?? 'Unnamed file'}
																				>{file.path ?? 'Unnamed file'}</span
																			>
																			<span
																				class="shrink-0 font-mono text-muted-foreground tabular-nums"
																				>{formatBytes(file.bytes ?? 0)}</span
																			>
																			<div class="flex shrink-0 items-center gap-0.5">
																				{#if file.individually_downloadable && file.id != null}
																					{@const stream =
																						streamingLinks[`${torrent.id}:${file.id}`]}
																					{#if stream?.status === 'loading'}
																						<span
																							class="grid size-7 place-items-center text-muted-foreground"
																							aria-label="Checking streaming availability"
																						>
																							<CircleNotch class="size-3 animate-spin" />
																						</span>
																					{:else}
																						<Tooltip.Root>
																							<Tooltip.Trigger>
																								{#snippet child({ props })}
																									<Button
																										{...props}
																										variant="ghost"
																										size="icon-sm"
																										class="size-7"
																										aria-label={`Play ${file.path ?? 'file'} in Real-Debrid`}
																										onclick={() =>
																											void openStreamingPage(torrent, file)}
																									>
																										<Play class="size-3.5" />
																									</Button>
																								{/snippet}
																							</Tooltip.Trigger>
																							<Tooltip.Content>Play in Real-Debrid</Tooltip.Content>
																						</Tooltip.Root>
																						<Tooltip.Root>
																							<Tooltip.Trigger>
																								{#snippet child({ props })}
																									<Button
																										{...props}
																										variant="ghost"
																										size="icon-sm"
																										class="size-7"
																										aria-label={`Show media info for ${file.path ?? 'file'}`}
																										onclick={() =>
																											void openStreamingDialog(torrent, file)}
																									>
																										<Info class="size-3.5" />
																									</Button>
																								{/snippet}
																							</Tooltip.Trigger>
																							<Tooltip.Content>Media info</Tooltip.Content>
																						</Tooltip.Root>
																					{/if}
																					<Tooltip.Root>
																						<Tooltip.Trigger>
																							{#snippet child({ props })}
																								<Button
																									{...props}
																									variant="ghost"
																									size="icon-sm"
																									class="size-7"
																									disabled={file.id == null ||
																										downloadingFileId !== null}
																									aria-label={`Add ${file.path ?? 'file'} to downloads`}
																									onclick={() =>
																										void downloadTorrentFile(torrent, file)}
																								>
																									{#if downloadingFileId === `${torrent.id}:${file.id}`}
																										<CircleNotch class="size-3.5 animate-spin" />
																									{:else}
																										<Download class="size-3.5" />
																									{/if}
																								</Button>
																							{/snippet}
																						</Tooltip.Trigger>
																						<Tooltip.Content>Add file to downloads</Tooltip.Content>
																					</Tooltip.Root>
																				{/if}
																			</div>
																		</li>
																	{/each}
																</ul>
															{/if}
														</div>
													{/if}
												</div>
											</div>
										</li>
									{/each}
								</ul>
							{/if}
						</div>
						{#if !loading && !error && (filteredTorrents.length > 0 || page > 1)}
							<div class="flex items-center justify-between gap-3 border-t border-border px-5 py-4">
								<p class="min-w-0 truncate font-mono text-xs text-muted-foreground">
									{torrentCountLabel} · Page {page}{#if pageCount != null}
										of {pageCount}{/if}
								</p>
								<div
									class="flex shrink-0 items-center gap-1.5"
									role="navigation"
									aria-label="Torrent pages"
								>
									<Button
										variant="outline"
										size="icon-xs"
										disabled={page <= 1 || refreshing}
										onclick={() => goToPage(1)}
										aria-label="Go to first page"
									>
										<CaretDoubleLeft class="size-3.5" />
									</Button>
									<Button
										variant="outline"
										size="xs"
										disabled={page <= 1 || refreshing}
										onclick={() => goToPage(page - 1)}
										aria-label="Go to previous page"
									>
										<CaretLeft class="size-3.5" /> Previous
									</Button>
									<Button
										variant="outline"
										size="xs"
										disabled={!hasMore || refreshing}
										onclick={() => goToPage(page + 1)}
										aria-label="Go to next page"
									>
										Next <CaretRight class="size-3.5" />
									</Button>
								</div>
							</div>
						{/if}
					</div>
				</section>
			</div>
		</main>
	</Tooltip.Provider>

	<Dialog.Root bind:open={streamDialogOpen}>
		<Dialog.Content class="gap-0 p-0 sm:max-w-[480px]">
			<div class="px-5 pt-5 pr-12 pb-4">
				<Dialog.Header>
					<Dialog.Title>Stream file</Dialog.Title>
					<Dialog.Description>
						{activeStreamFile?.path ?? activeStreamTorrent?.filename ?? 'Choose a version to play'}
					</Dialog.Description>
				</Dialog.Header>
			</div>
			<div class="max-h-[60vh] space-y-4 overflow-y-auto px-5 pb-5">
				{#if streamDialogLoading || (activeStreamKey && streamingLinks[activeStreamKey]?.status === 'loading')}
					<p class="flex items-center gap-2 text-xs text-muted-foreground">
						<CircleNotch class="size-3.5 animate-spin" /> Loading streaming versions…
					</p>
				{:else if activeStreamKey && streamingData[activeStreamKey]}
					{@const options = streamingData[activeStreamKey]}
					{@const summary = mediaSummary(options.media_infos)}
					{#if summary.type || summary.duration !== undefined || summary.audio.length > 0 || summary.subs.length > 0}
						<div
							class="space-y-2 rounded-xl border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
						>
							{#if summary.type || summary.duration !== undefined}
								<p>
									{#if summary.type}Type: {summary.type} ·
									{/if}
									{#if summary.duration !== undefined}Duration: {Math.round(summary.duration)}s{/if}
								</p>
							{/if}
							{#if summary.audio.length > 0}
								<div>
									<p class="mb-1 font-medium text-foreground">Audio · {summary.audio.length}</p>
									<ul class="list-disc space-y-0.5 pl-4">
										{#each summary.audio as track (track.id)}
											<li>{track.label}</li>
										{/each}
									</ul>
								</div>
							{/if}
							{#if summary.subs.length > 0}
								<div>
									<p class="mb-1 font-medium text-foreground">Subtitles · {summary.subs.length}</p>
									<ul class="list-disc space-y-0.5 pl-4">
										{#each summary.subs as track (track.id)}
											<li>{track.label}</li>
										{/each}
									</ul>
								</div>
							{/if}
							{#if summary.audio.length > 0 || summary.subs.length > 0}
								<p class="text-[11px]">
									The Real-Debrid player lets you choose the available tracks.
								</p>
							{/if}
						</div>
					{/if}
					<a
						href={options.streaming_url}
						target="_blank"
						rel="noopener noreferrer"
						class="flex items-center justify-center gap-2 rounded-md border border-border/50 px-3 py-2 text-xs hover:bg-muted"
					>
						<Play class="size-3.5" /> Open Real-Debrid player
					</a>
				{:else}
					<p class="text-xs text-muted-foreground">No streaming versions available.</p>
				{/if}
			</div>
		</Dialog.Content>
	</Dialog.Root>

	<Dialog.Root bind:open={deleteRdDialogOpen}>
		<Dialog.Content class="gap-0 p-0 sm:max-w-[420px]">
			<div class="px-5 pt-5 pr-12 pb-4">
				<Dialog.Header>
					<Dialog.Title>Delete from Real-Debrid?</Dialog.Title>
					<Dialog.Description>
						{pendingDeleteRd?.filename ?? 'This torrent'} will be permanently removed from your Real-Debrid
						account.
					</Dialog.Description>
				</Dialog.Header>
			</div>
			<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
				<Dialog.Close>
					{#snippet child({ props })}
						<Button variant="outline" size="sm" {...props}>Keep</Button>
					{/snippet}
				</Dialog.Close>
				<Button
					variant="destructive"
					size="sm"
					disabled={deletingRd}
					onclick={() => void confirmDeleteRd()}
				>
					{#if deletingRd}<CircleNotch class="size-3.5 animate-spin" /> Deleting…{:else}Delete{/if}
				</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
{/if}
