<script lang="ts">
	import { Check, ChevronDown, Download, Film, Loader2, Search, Tv, Upload } from '@lucide/svelte';
	import { Select } from 'bits-ui';
	import { Button } from '$lib/components/ui/button';
	import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { toast } from 'svelte-sonner';
	import SiteHeader from '$lib/components/site-header.svelte';

	type Title = { imdb_id: string; title: string; year: string; media_type: 'movie' | 'series' };
	type Release = { info_hash: string; title: string; name: string; source: string };

	let query = $state('');
	let mediaType = $state<'movie' | 'series'>('movie');
	let titles = $state<Title[]>([]);
	let selected = $state<Title | null>(null);
	let season = $state<number | undefined>(undefined);
	let episode = $state<number | undefined>(undefined);
	let releases = $state<Release[]>([]);
	let searching = $state(false);
	let loadingReleases = $state(false);
	let action = $state<string | null>(null);
	let added = $state(new Set<string>());
	let selectionOpen = $state(false);
	let selectionLoading = $state(false);
	let selectionSubmitting = $state(false);
	let selectionTaskId = $state<string | null>(null);
	let selectionTaskName = $state('torrent');
	let selectionFiles = $state<Array<{ id?: number; name?: string; size?: number; selected?: number }>>([]);
	let selectedFileIds = $state<number[]>([]);
	let releaseQuery = $state('');
	let quality = $state('All quality');
	let releaseType = $state('All types');
	let sort = $state('Best match');

	const qualityFilters = ['All quality', '4K / UHD', '1080p', '720p'] as const;
	const typeFilters = ['All types', 'WEB-DL', 'BluRay', 'Remux', 'Encode'] as const;

	const filteredReleases = $derived(
		[...releases]
			.filter((release) => {
				const text = `${release.title} ${release.name}`.toLowerCase();
				const q = releaseQuery.trim().toLowerCase();
				const matchesQuery = !q || text.includes(q);
				const matchesQuality = quality === 'All quality' || (quality === '4K / UHD' ? /\b(2160p|4k|uhd)\b/i.test(text) : text.includes(quality));
				const matchesType = releaseType === 'All types' || text.includes(releaseType.toLowerCase());
				return matchesQuery && matchesQuality && matchesType;
			})
			.sort((a, b) => sort === 'Name A–Z' ? a.title.localeCompare(b.title) : 0)
	);

	async function searchTitles() {
		if (query.trim().length < 2 || searching) return;
		searching = true;
		titles = [];
		selected = null;
		releases = [];
		try {
			const response = await fetch(`/api/discover/search?q=${encodeURIComponent(query.trim())}&type=${mediaType}`);
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || 'Search failed');
			titles = data.titles;
			if (!titles.length) toast.info('No matching titles found.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Search failed');
		} finally {
			searching = false;
		}
	}

	async function chooseTitle(title: Title) {
		selected = title;
		mediaType = title.media_type;
		season = undefined;
		episode = undefined;
		releases = [];
		releaseQuery = '';
		if (title.media_type === 'movie') await loadReleases();
	}

	async function loadReleases() {
		if (!selected || loadingReleases) return;
		loadingReleases = true;
		try {
			const params = new URLSearchParams();
			if (selected.media_type === 'series' && typeof season === 'number' && Number.isInteger(season) && season > 0) params.set('season', String(season));
			if (selected.media_type === 'series' && typeof episode === 'number' && Number.isInteger(episode) && episode > 0) params.set('episode', String(episode));
			const suffix = params.toString() ? `?${params}` : '';
			const response = await fetch(`/api/discover/${selected.media_type}/${selected.imdb_id}${suffix}`);
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || 'Release search failed');
			releases = data.releases;
			if (!releases.length) toast.info('No releases found for that selection.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Release search failed');
		} finally {
			loadingReleases = false;
		}
	}

	function clearFilters() {
		releaseQuery = '';
		quality = 'All quality';
		releaseType = 'All types';
		sort = 'Best match';
	}

	async function addToRd(release: Release) {
		action = `${release.info_hash}:rd`;
		try {
			const response = await fetch('/api/discover/add-to-rd', {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ info_hash: release.info_hash })
			});
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || 'Real-Debrid rejected the magnet');
			added = new Set(added).add(release.info_hash);
			toast.success('Added to Real-Debrid.');
			await promptSelection(data.id, release.title);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Could not add to Real-Debrid');
		} finally {
			action = null;
		}
	}

	async function download(release: Release) {
		action = `${release.info_hash}:download`;
		try {
			const response = await fetch('/api/discover/download', {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ info_hash: release.info_hash })
			});
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || 'Download failed');
			toast.success('Added to server downloads.');
			await promptSelection(data.id, release.title);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Download failed');
		} finally {
			action = null;
		}
	}

	async function promptSelection(taskId: string, name: string) {
		selectionLoading = true;
		try {
			const response = await fetch(`/api/download/${taskId}/files`);
			const data = await response.json();
			if (!response.ok || data.status !== 'selecting_files') return;
			selectionTaskId = taskId;
			selectionTaskName = name;
			selectionFiles = data.files ?? [];
			selectedFileIds = selectionFiles.filter((file) => file.selected).map((file) => file.id).filter((id): id is number => id != null);
			selectionOpen = true;
		} finally {
			selectionLoading = false;
		}
	}

	async function submitSelection() {
		if (!selectionTaskId || !selectedFileIds.length || selectionSubmitting) return;
		selectionSubmitting = true;
		try {
			const response = await fetch(`/api/download/${selectionTaskId}/files`, {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selectedFileIds })
			});
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || 'Could not select files');
			selectionOpen = false;
			toast.success('File selection saved.');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Could not select files');
		} finally {
			selectionSubmitting = false;
		}
	}

	function fileSize(bytes?: number) {
		if (!bytes) return '';
		if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
		return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
	}
</script>

<svelte:head>
	<title>Discover — RMT-Debrid</title>
	<meta name="description" content="Search for movies and shows, then add releases to Real-Debrid." />
</svelte:head>

<main class="min-h-screen bg-background text-foreground">
	<SiteHeader onLogout={() => (window.location.href = '/')} />

	<div class="mx-auto grid w-full max-w-6xl gap-4 px-3 py-4 sm:px-8 sm:py-6">
		<Card class="gap-0 rounded-md py-0">
			<CardContent class="px-3 py-3 sm:px-4">
				<form class="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center" onsubmit={(event) => { event.preventDefault(); searchTitles(); }}>
				<span class="sr-only" id="media-type-label">Media type</span>
				<div class="w-full sm:w-40">
					<Select.Root type="single" bind:value={mediaType} name="media-type" items={[{ value: 'movie', label: 'Movie' }, { value: 'series', label: 'TV show' }]}>
						<Select.Trigger aria-labelledby="media-type-label" class="flex h-10 w-full cursor-pointer items-center justify-between rounded-md border border-input bg-input/30 px-2.5 text-[13px] font-medium text-foreground [&_[data-select-value]]:min-w-0 [&_[data-select-value]]:truncate shadow-xs outline-none transition-colors duration-75 hover:bg-muted focus:border-ring focus:ring-2 focus:ring-ring/30"><Select.Value /><ChevronDown class="size-3.5 shrink-0 text-muted-foreground" /></Select.Trigger>
						<Select.Portal><Select.Content class="z-50 min-w-[var(--bits-select-anchor-width)] overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl" sideOffset={6}><Select.Viewport><Select.Item value="movie" label="Movie" class="cursor-pointer rounded px-2 py-1.5 text-[13px] outline-none hover:bg-foreground/10 data-[highlighted]:bg-foreground/10">Movie</Select.Item><Select.Item value="series" label="TV show" class="cursor-pointer rounded px-2 py-1.5 text-[13px] outline-none hover:bg-foreground/10 data-[highlighted]:bg-foreground/10">TV show</Select.Item></Select.Viewport></Select.Content></Select.Portal>
					</Select.Root>
				</div>
				<label class="sr-only" for="title-search">Title</label>
				<div class="relative flex-1"><Input id="title-search" bind:value={query} placeholder="Search for a movie or show…" autocomplete="off" class="h-10 text-[13px]" /></div>
				<Button type="submit" class="h-10 w-full shrink-0 sm:w-auto" disabled={searching || query.trim().length < 2}>{#if searching}<Loader2 class="size-4 animate-spin" />{:else}<Search class="size-4" />{/if} Search</Button>
			</form>
			<p class="mt-2 text-xs text-muted-foreground">Tip: search by exact title for the cleanest release list.</p>
		</CardContent>
	</Card>

	{#if titles.length}
		<section class="grid gap-2" aria-label="Title results">
			<div class="flex items-center justify-between"><h2 class="text-sm font-semibold">Choose a title</h2><span class="font-mono text-xs font-normal text-muted-foreground">{titles.length} matches</span></div>
			<div class="grid gap-2 sm:grid-cols-2">
				{#each titles as title (title.imdb_id)}
					<button type="button" class={`group flex min-w-0 cursor-pointer items-center gap-2.5 rounded-md border border-border bg-card px-3 py-2.5 text-left transition-colors duration-75 hover:border-foreground/30 hover:bg-muted/40 ${selected?.imdb_id === title.imdb_id ? 'bg-muted/50' : ''}`} onclick={() => chooseTitle(title)}>
						<span class="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">{#if title.media_type === 'movie'}<Film class="size-3.5" />{:else}<Tv class="size-3.5" />{/if}</span>
						<span class="min-w-0 flex-1 overflow-hidden"><span class="block max-w-full truncate text-sm font-semibold" title={title.title}>{title.title}</span><span class="font-mono text-xs text-muted-foreground">{title.year || 'Year unknown'} · {title.imdb_id}</span></span>
					</button>
				{/each}
			</div>
		</section>
	{/if}

	{#if selected?.media_type === 'series'}
		<Card class="gap-0 rounded-md py-0">
			<CardHeader class="border-b border-border/60 px-3 py-3 sm:px-4"><CardTitle class="text-sm font-semibold">Which episode?</CardTitle><CardDescription class="text-xs">Leave both blank to search the whole show.</CardDescription></CardHeader>
			<CardContent class="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-end sm:px-4">
				<label class="grid gap-1.5 text-xs font-medium">Season<Input type="number" min="1" bind:value={season} placeholder="Any" class="h-8 w-full text-[13px] sm:w-28" /></label>
				<label class="grid gap-1.5 text-xs font-medium">Episode<Input type="number" min="1" bind:value={episode} placeholder="Any" class="h-8 w-full text-[13px] sm:w-28" /></label>
				<Button type="button" size="sm" class="h-8" onclick={() => loadReleases()} disabled={loadingReleases}>{#if loadingReleases}<Loader2 class="size-3.5 animate-spin" />{:else}<Search class="size-3.5" />{/if} Find releases</Button>
			</CardContent>
		</Card>
	{/if}

	{#if releases.length}
		<section class="grid gap-2" aria-label="Torrent releases">
			<div class="flex flex-wrap items-center justify-between gap-2"><div class="flex min-w-0 items-center gap-2"><h2 class="text-sm font-semibold">Available releases</h2><span class="font-mono text-xs font-normal text-muted-foreground">({filteredReleases.length})</span></div><div class="flex items-center gap-2"><span class="sr-only">Sort releases</span><Select.Root type="single" bind:value={sort} items={[{ value: 'Best match', label: 'Best match' }, { value: 'Name A–Z', label: 'Name A–Z' }]}><Select.Trigger class="flex h-8 w-28 cursor-pointer items-center justify-between gap-1 rounded-md border border-border/50 px-2.5 text-[11px] font-medium text-foreground [&_[data-select-value]]:min-w-0 [&_[data-select-value]]:truncate outline-none transition-colors duration-75 hover:bg-foreground/5 focus:border-ring focus:ring-2 focus:ring-ring/30"><Select.Value /><ChevronDown class="size-3.5 shrink-0 text-muted-foreground" /></Select.Trigger><Select.Portal><Select.Content class="z-50 min-w-[var(--bits-select-anchor-width)] overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl" sideOffset={4}><Select.Viewport><Select.Item value="Best match" label="Best match" class="cursor-pointer rounded px-2 py-1.5 text-xs outline-none hover:bg-foreground/10 data-[highlighted]:bg-foreground/10">Best match</Select.Item><Select.Item value="Name A–Z" label="Name A–Z" class="cursor-pointer rounded px-2 py-1.5 text-xs outline-none hover:bg-foreground/10 data-[highlighted]:bg-foreground/10">Name A–Z</Select.Item></Select.Viewport></Select.Content></Select.Portal></Select.Root></div></div>
			<div class="flex flex-col gap-2 rounded-md border border-border/50 bg-muted/20 p-2 sm:flex-row sm:items-center"><div class="relative min-w-0 flex-1"><Search class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" /><Input bind:value={releaseQuery} placeholder="Filter releases…" class="h-8 pl-8 text-[13px]" aria-label="Filter releases by name" /></div><div class="grid shrink-0 grid-cols-2 gap-2 sm:flex sm:items-center"><span class="sr-only" id="quality-filter-label">Filter by quality</span><Select.Root type="single" bind:value={quality} items={qualityFilters.map((option) => ({ value: option, label: option }))}><Select.Trigger aria-labelledby="quality-filter-label" class="flex h-8 w-full min-w-0 cursor-pointer items-center justify-between gap-1 rounded-md border border-border/50 px-2.5 text-[11px] font-medium text-foreground [&_[data-select-value]]:min-w-0 [&_[data-select-value]]:truncate outline-none transition-colors duration-75 hover:bg-foreground/5 focus:border-ring focus:ring-2 focus:ring-ring/30 sm:w-32"><Select.Value /><ChevronDown class="size-3.5 shrink-0 text-muted-foreground" /></Select.Trigger><Select.Portal><Select.Content class="z-50 min-w-[var(--bits-select-anchor-width)] overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl" sideOffset={4}><Select.Viewport>{#each qualityFilters as option}<Select.Item value={option} label={option} class="cursor-pointer rounded px-2 py-1.5 text-xs outline-none hover:bg-foreground/10 data-[highlighted]:bg-foreground/10">{option}</Select.Item>{/each}</Select.Viewport></Select.Content></Select.Portal></Select.Root><span class="sr-only" id="format-filter-label">Filter by format</span><Select.Root type="single" bind:value={releaseType} items={typeFilters.map((option) => ({ value: option, label: option }))}><Select.Trigger aria-labelledby="format-filter-label" class="flex h-8 w-full min-w-0 cursor-pointer items-center justify-between gap-1 rounded-md border border-border/50 px-2.5 text-[11px] font-medium text-foreground [&_[data-select-value]]:min-w-0 [&_[data-select-value]]:truncate outline-none transition-colors duration-75 hover:bg-foreground/5 focus:border-ring focus:ring-2 focus:ring-ring/30 sm:w-32"><Select.Value /><ChevronDown class="size-3.5 shrink-0 text-muted-foreground" /></Select.Trigger><Select.Portal><Select.Content class="z-50 min-w-[var(--bits-select-anchor-width)] overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl" sideOffset={4}><Select.Viewport>{#each typeFilters as option}<Select.Item value={option} label={option} class="cursor-pointer rounded px-2 py-1.5 text-xs outline-none hover:bg-foreground/10 data-[highlighted]:bg-foreground/10">{option}</Select.Item>{/each}</Select.Viewport></Select.Content></Select.Portal></Select.Root></div></div>
			{#if filteredReleases.length}
			{#each filteredReleases as release (release.info_hash)}
				<div class="group flex flex-col gap-2.5 rounded-md border border-border bg-card px-3 py-3 transition-colors duration-75 hover:border-foreground/25 sm:flex-row sm:items-center">
					<div class="grid size-8 shrink-0 place-items-center rounded-md bg-muted text-[11px] font-semibold text-muted-foreground">{release.source === 'Torrentio' ? 'TOR' : 'SRC'}</div><div class="w-full min-w-0 flex-1 overflow-hidden sm:w-0"><p class="w-full truncate text-sm font-semibold" title={release.title}>{release.title}</p><div class="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-muted-foreground"><span class="min-w-0 truncate" title={release.name || release.source}>{release.name || release.source}</span><span aria-hidden="true">·</span><span class="shrink-0 font-mono">{release.info_hash.slice(0, 8)}…</span></div></div>
					<div class="flex w-full shrink-0 gap-2 sm:w-auto"><Button class="h-8 min-w-0 flex-1 sm:flex-none" size="sm" variant="outline" title="Add to Real-Debrid" aria-label="Add to Real-Debrid" disabled={action !== null || added.has(release.info_hash)} onclick={() => addToRd(release)}>{#if added.has(release.info_hash)}<Check class="size-3.5" /><span>Added</span>{:else if action === `${release.info_hash}:rd`}<Loader2 class="size-3.5 animate-spin" /><span>Adding…</span>{:else}<Upload class="size-3.5" /><span>Add to RD</span>{/if}</Button><Button class="h-8 min-w-0 flex-1 sm:flex-none" size="sm" title="Download" aria-label="Download" disabled={action !== null} onclick={() => download(release)}>{#if action === `${release.info_hash}:download`}<Loader2 class="size-3.5 animate-spin" />{:else}<Download class="size-3.5" /><span>Download</span>{/if}</Button></div>
				</div>
			{/each}
			{:else}<div class="rounded-md border border-dashed border-border px-6 py-10 text-center"><p class="text-sm font-medium">No releases match those filters.</p><p class="mt-1 text-xs text-muted-foreground">Try clearing a filter or searching for a different release name.</p><Button variant="ghost" size="sm" class="mt-3 h-8" onclick={clearFilters}>Clear filters</Button></div>{/if}
		</section>
	{/if}
	{#if selected && loadingReleases}<div class="flex items-center justify-center gap-2 rounded-md border border-dashed border-border px-6 py-10 text-sm text-muted-foreground"><Loader2 class="size-4 animate-spin" /> Finding releases for {selected.title}…</div>{:else if selected && !releases.length && selected.media_type === 'movie'}<div class="rounded-md border border-dashed border-border px-6 py-10 text-center"><p class="text-sm font-medium">Ready to find releases for {selected.title}.</p><p class="mt-1 text-xs text-muted-foreground">Search results will appear here.</p></div>{/if}
	</div>
</main>

<Dialog.Root bind:open={selectionOpen} onOpenChange={(open) => { if (!open) selectionOpen = true; }}>
	<Dialog.Content showCloseButton={false} class="gap-4 p-6 sm:max-w-[560px]">
		<Dialog.Header>
			<Dialog.Title>Select files for {selectionTaskName}</Dialog.Title>
			<Dialog.Description>Choose at least one file before this torrent can start.</Dialog.Description>
		</Dialog.Header>
		<div class="max-h-[55vh] overflow-y-auto">
			{#if selectionLoading}
				<div class="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 class="size-4 animate-spin" /> Loading files…</div>
			{:else}
				<div class="grid gap-1">
					{#each selectionFiles as file}
						<label class="flex cursor-pointer items-center gap-3 rounded px-2 py-2 text-sm hover:bg-muted">
							<input type="checkbox" checked={file.id != null && selectedFileIds.includes(file.id)} onchange={() => { if (file.id == null) return; selectedFileIds = selectedFileIds.includes(file.id) ? selectedFileIds.filter((id) => id !== file.id) : [...selectedFileIds, file.id]; }} />
							<span class="min-w-0 flex-1 truncate" title={file.name}>{file.name}</span><span class="shrink-0 font-mono text-xs text-muted-foreground">{fileSize(file.size)}</span>
						</label>
					{/each}
				</div>
			{/if}
		</div>
		<Dialog.Footer><Button size="sm" disabled={selectionLoading || selectionSubmitting || !selectedFileIds.length} onclick={submitSelection}>{selectionSubmitting ? 'Starting…' : `Start with ${selectedFileIds.length} selected`}</Button></Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
