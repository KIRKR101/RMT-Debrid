<script lang="ts">
	import { onMount } from 'svelte';
	import { Check, ChevronLeft, ChevronRight, ChevronsLeft, Download, Inbox, Loader2, RefreshCw, Search, Trash2 } from '@lucide/svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Progress } from '$lib/components/ui/progress';
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
	const inactiveStatuses = ['downloaded', 'error', 'magnet_error', 'virus', 'dead'];

	const filteredTorrents = $derived(
		torrents.filter((torrent) => {
			if (activeOnly && inactiveStatuses.includes(torrent.status)) return false;
			const q = query.trim().toLowerCase();
			if (!q) return true;
			return (
				torrent.filename.toLowerCase().includes(q) ||
				torrent.status.toLowerCase().includes(q)
			);
		})
	);

	function formatBytes(bytes: number) {
		if (!bytes || bytes <= 0) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB', 'TB'];
		const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
		return `${parseFloat((bytes / 1024 ** unit).toFixed(1))} ${units[unit]}`;
	}

	function formatSpeed(bps?: number) {
		if (!bps || bps <= 0) return '';
		const mbps = bps / 1024 / 1024;
		if (mbps < 1) return `${(mbps * 1024).toFixed(0)} KB/s`;
		return `${mbps.toFixed(1)} MB/s`;
	}

	function formatDate(value?: string) {
		if (!value) return '';
		const parsed = new Date(value);
		return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString();
	}

	function statusClass(status: string) {
		if (status === 'downloaded') return 'text-emerald-400';
		if (['error', 'magnet_error', 'virus', 'dead'].includes(status)) return 'text-red-400';
		if (status === 'downloading') return 'text-violet-300';
		return 'text-sky-300';
	}

	function dotClass(status: string) {
		if (status === 'downloaded') return 'bg-emerald-400';
		if (['error', 'magnet_error', 'virus', 'dead'].includes(status)) return 'bg-red-400';
		if (status === 'downloading') return 'bg-violet-400';
		return 'bg-sky-400';
	}

	function metaLine(torrent: RdTorrent) {
		const parts: string[] = [];
		if (torrent.bytes > 0) parts.push(formatBytes(torrent.bytes));
		const speed = formatSpeed(torrent.speed);
		if (speed) parts.push(speed);
		if (torrent.seeders != null && torrent.status === 'downloading') {
			parts.push(`${torrent.seeders} seeders`);
		}
		const added = formatDate(torrent.added);
		if (added) parts.push(added);
		return parts.join(' · ');
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
			const data = await response.json().catch(() => null) as { files?: unknown; detail?: string } | null;
			if (!response.ok) {
				if (response.status === 401) authenticated = false;
				throw new Error(data?.detail ?? 'Could not load torrent files.');
			}
			torrentFiles = {
				...torrentFiles,
				[torrent.id]: Array.isArray(data?.files) ? data.files as RdFile[] : []
			};
		} catch (err) {
			filesError = { ...filesError, [torrent.id]: err instanceof Error ? err.message : 'Could not load torrent files.' };
		} finally {
			if (filesLoading === torrent.id) filesLoading = null;
		}
	}

	async function downloadTorrentFile(torrent: RdTorrent, file: RdFile) {
		if (file.id == null || downloadingFileId) return;
		const key = `${torrent.id}:${file.id}`;
		downloadingFileId = key;
		try {
			const response = await fetch(`/api/rd/torrents/${encodeURIComponent(torrent.id)}/files/${file.id}/download`, { method: 'POST' });
			const data = await response.json().catch(() => null) as { detail?: string } | null;
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
				throw new Error(
					(data as { detail?: string } | null)?.detail ?? 'Could not load torrents.'
				);
			}
			const payload = data as { torrents?: unknown; has_more?: unknown } | RdTorrent[] | null;
			if (Array.isArray(payload)) {
				// Legacy backend shape: bare list with no pagination metadata.
				torrents = payload;
				hasMore = payload.length >= PAGE_SIZE;
			} else {
				const list = payload?.torrents;
				torrents = Array.isArray(list) ? list : [];
				hasMore = payload?.has_more === true;
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
	}

	function goToPage(next: number) {
		if (next < 1 || next === page || loading || refreshing) return;
		page = next;
		window.scrollTo({ top: 0 });
		void fetchTorrents();
	}

	async function importTorrent(torrent: RdTorrent) {
		if (importingId) return;
		importingId = torrent.id;
		try {
			const response = await fetch(`/api/rd/torrents/${encodeURIComponent(torrent.id)}/import`, { method: 'POST' });
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
	<main class="grid min-h-screen place-items-center bg-background px-4 text-foreground">
		<Loader2 class="size-5 animate-spin text-muted-foreground" aria-label="Loading" />
	</main>
{:else if !authenticated}
	<main class="grid min-h-screen place-items-center bg-background px-4 text-foreground">
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
	<main class="min-h-screen bg-background text-foreground">
		<SiteHeader onLogout={handleLogout} />

		<div class="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8">
			<section aria-labelledby="torrents-heading">
				<Card class="gap-0 rounded-md py-0">
					<CardHeader class="border-b border-border/60 px-4 py-3">
						<div class="flex flex-wrap items-center justify-between gap-2">
							<CardTitle id="torrents-heading" class="text-sm font-semibold text-foreground">
								Real-Debrid Torrents
								{#if !loading}<span class="font-mono text-xs font-normal text-muted-foreground">({filteredTorrents.length})</span>{/if}
							</CardTitle>
							<div class="flex items-center gap-2">
								<Button
									variant="ghost"
									size="icon-xs"
									aria-label="Refresh torrents"
									onclick={() => void fetchTorrents()}
									disabled={loading || refreshing}
								>
									<RefreshCw class={`size-3.5 ${refreshing ? 'animate-spin' : ''}`} />
								</Button>
							</div>
						</div>
						<div class="mt-2.5 flex min-w-0 items-center gap-2">
							<div class="relative min-w-0 flex-1">
								<Search class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
								<Input bind:value={query} placeholder="Filter this page…" aria-label="Filter torrents on this page" class="h-8 pl-8 text-[13px]" />
							</div>
													<button
								type="button"
								aria-pressed={activeOnly}
								onclick={toggleActiveOnly}
								class={`flex h-8 shrink-0 cursor-pointer items-center justify-center gap-1 rounded-md border border-border/50 px-2.5 text-[11px] font-medium transition-colors duration-75 ${activeOnly ? 'bg-foreground/10 text-foreground' : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground'}`}
							>
								Active only
													</button>
						</div>
					</CardHeader>

					<CardContent class="px-4 pb-2">
						{#if loading}
							<div class="grid gap-1 py-2" aria-label="Loading torrents">
								{#each [0, 1, 2] as i (i)}
									<div class="py-2">
										<div class="h-3.5 w-2/3 animate-pulse rounded bg-muted"></div>
										<div class="mt-2 h-[5px] w-full animate-pulse rounded bg-muted"></div>
									</div>
								{/each}
							</div>
						{:else if error}
							<div class="py-4">
								<Alert.Root variant="destructive">
									<Alert.Description>{error}</Alert.Description>
								</Alert.Root>
							</div>
						{:else if torrents.length === 0}
							<div class="flex flex-col items-center px-6 py-10 text-center">
								<Inbox class="size-6 text-muted-foreground" />
								<p class="mt-3 text-sm text-muted-foreground">
									{activeOnly ? 'No active torrents on Real-Debrid' : 'No torrents on Real-Debrid'}
								</p>
							</div>
						{:else if filteredTorrents.length === 0}
							<div class="px-6 py-10 text-center text-sm text-muted-foreground">No matches</div>
						{:else}
							<ul class="divide-y divide-border/30">
								{#each filteredTorrents as torrent (torrent.id)}
									<li class="group py-3.5">
										<div class="flex items-center justify-between gap-3">
											<div class="flex min-w-0 items-center gap-1.5">
												<button
													type="button"
													class="grid size-6 shrink-0 cursor-pointer place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
													aria-expanded={expandedTorrentId === torrent.id}
													aria-label={`${expandedTorrentId === torrent.id ? 'Hide' : 'Show'} files for ${torrent.filename}`}
													onclick={() => void toggleTorrentFiles(torrent)}
												>
													<ChevronRight class={`size-3.5 transition-transform ${expandedTorrentId === torrent.id ? 'rotate-90' : ''}`} />
												</button>
												<p class="min-w-0 truncate text-sm font-semibold" title={torrent.filename}>
													{torrent.filename}
												</p>
											</div>
							<div class="flex shrink-0 items-center gap-1.5">
								<span class={`inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium whitespace-nowrap capitalize ${statusClass(torrent.status)}`}>
													<span class={`size-1.5 rounded-full ${dotClass(torrent.status)}`}></span>
													{torrent.status.replaceAll('_', ' ')}
												</span>
												{#if torrent.status === 'downloaded'}
													{#if importedIds.includes(torrent.id)}
														<span class="grid size-6 place-items-center text-emerald-400" title="Added to downloads" aria-label="Added to downloads">
															<Check class="size-3.5" />
														</span>
													{:else}
														<button
															type="button"
																class="ml-1 grid size-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-default disabled:opacity-50"
															title="Add to downloads"
															aria-label={`Add ${torrent.filename} to downloads`}
															disabled={importingId === torrent.id}
															onclick={() => void importTorrent(torrent)}
														>
															{#if importingId === torrent.id}
																<Loader2 class="size-3.5 animate-spin" />
															{:else}
																<Download class="size-3.5" />
															{/if}
														</button>
													{/if}
												{/if}
												<button
													type="button"
														class="grid size-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
													title="Delete from Real-Debrid"
													aria-label={`Delete ${torrent.filename} from Real-Debrid`}
													onclick={() => requestDeleteRd(torrent)}
												>
													<Trash2 class="size-3.5" />
												</button>
											</div>
										</div>
										<div class="mt-1 flex items-baseline justify-between gap-3 pl-7">
											<p class="min-w-0 truncate font-mono text-xs text-muted-foreground">
												{metaLine(torrent)}
											</p>
											{#if torrent.status !== 'downloaded'}
												<span class="w-11 shrink-0 text-right font-mono text-xs text-foreground">
													{torrent.progress}%
												</span>
											{/if}
										</div>
										{#if torrent.status !== 'downloaded'}
											<div class="mt-1.5">
												<Progress
													value={torrent.progress}
													max={100}
													class="h-[5px] flex-1"
													aria-label={`${torrent.filename} progress`}
												/>
											</div>
										{/if}
										{#if expandedTorrentId === torrent.id}
											<div class="mt-3 rounded-md border border-border/50 bg-muted/20 px-3 py-2">
												{#if filesLoading === torrent.id}
													<p class="text-xs text-muted-foreground">Loading files…</p>
												{:else if filesError[torrent.id]}
													<p class="text-xs text-destructive">{filesError[torrent.id]}</p>
												{:else if torrentFiles[torrent.id]?.length === 0}
													<p class="text-xs text-muted-foreground">No constituent files reported.</p>
												{:else}
													<ul class="space-y-1.5">
														{#each torrentFiles[torrent.id] ?? [] as file (file.id ?? file.path)}
															<li class="flex items-center justify-between gap-3 text-xs">
																<span class="min-w-0 truncate font-mono text-muted-foreground" title={file.path ?? 'Unnamed file'}>{file.path ?? 'Unnamed file'}</span>
																<div class="flex shrink-0 items-center gap-2">
																															<span class="font-mono text-muted-foreground">{formatBytes(file.bytes ?? 0)}</span>
																															{#if file.individually_downloadable}
																															<button
																		type="button"
																		class="grid size-6 cursor-pointer place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-default disabled:opacity-50"
															disabled={file.id == null || downloadingFileId !== null}
															title="Add file to downloads"
																			aria-label={`Add ${file.path ?? 'file'} to downloads`}
																		onclick={() => void downloadTorrentFile(torrent, file)}
																	>
																		{#if downloadingFileId === `${torrent.id}:${file.id}`}
																			<Loader2 class="size-3 animate-spin" />
																		{:else}
																			<Download class="size-3" />
																		{/if}
																															</button>
																											{/if}
																</div>
															</li>
														{/each}
													</ul>
												{/if}
											</div>
										{/if}
									</li>
								{/each}
							</ul>
						{/if}
					</CardContent>
					{#if !loading && !error && (torrents.length > 0 || page > 1)}
						<CardFooter class="flex items-center justify-between gap-2 border-t border-border/60 px-4 py-3">
							<p class="min-w-0 truncate font-mono text-xs text-muted-foreground">
								{torrents.length} shown · Page {page}
							</p>
							<div class="flex shrink-0 items-center gap-1.5" role="navigation" aria-label="Torrent pages">
								<Button
									variant="outline"
									size="icon-xs"
									disabled={page <= 1 || refreshing}
									onclick={() => goToPage(1)}
									aria-label="Go to first page"
								>
									<ChevronsLeft class="size-3.5" />
								</Button>
								<Button
									variant="outline"
									size="xs"
									disabled={page <= 1 || refreshing}
									onclick={() => goToPage(page - 1)}
									aria-label="Go to previous page"
								>
									<ChevronLeft class="size-3.5" /> Previous
								</Button>
								<Button
									variant="outline"
									size="xs"
									disabled={!hasMore || refreshing}
									onclick={() => goToPage(page + 1)}
									aria-label="Go to next page"
								>
									Next <ChevronRight class="size-3.5" />
								</Button>
							</div>
						</CardFooter>
					{/if}
				</Card>
			</section>
		</div>
	</main>

	<Dialog.Root bind:open={deleteRdDialogOpen}>
			<Dialog.Content class="gap-0 p-0 sm:max-w-[420px]">
				<div class="px-5 pt-5 pr-12 pb-4">
					<Dialog.Header>
						<Dialog.Title>Delete from Real-Debrid?</Dialog.Title>
						<Dialog.Description>
							{pendingDeleteRd?.filename ?? 'This torrent'} will be permanently removed from your
							Real-Debrid account.
						</Dialog.Description>
					</Dialog.Header>
				</div>
				<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
				<Dialog.Close>
					{#snippet child({ props })}
						<Button variant="outline" size="sm" {...props}>Keep</Button>
					{/snippet}
				</Dialog.Close>
				<Button variant="destructive" size="sm" disabled={deletingRd} onclick={() => void confirmDeleteRd()}>
					{#if deletingRd}<Loader2 class="size-3.5 animate-spin" /> Deleting…{:else}Delete{/if}
				</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
{/if}
