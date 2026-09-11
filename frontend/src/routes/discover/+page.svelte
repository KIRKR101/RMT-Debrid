<script lang="ts">
	import {
		ArrowCounterClockwise,
		Check,
		Download,
		FilmSlate,
		CircleNotch,
		MagnifyingGlass,
		Star,
		Television,
		Upload,
		X
	} from 'phosphor-svelte';
	import * as Alert from '$lib/components/ui/alert';
	import * as Select from '$lib/components/ui/select';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Button } from '$lib/components/ui/button';
	import {
		Card,
		CardContent,
		CardDescription,
		CardHeader,
		CardTitle
	} from '$lib/components/ui/card';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { toast } from 'svelte-sonner';
	import SiteHeader from '$lib/components/site-header.svelte';

	type Title = {
		imdb_id: string;
		title: string;
		year: string;
		media_type: 'movie' | 'series';
		poster?: string;
	};
	type TitleDetails = {
		name: string;
		genres: string[];
		runtime: string;
		description: string;
		rating: string;
		poster: string;
		year: string;
	};
	type Release = {
		info_hash: string;
		title: string;
		name: string;
		source: string;
		sources?: string[];
	};

	let query = $state('');
	let mediaType = $state<'movie' | 'series'>('movie');
	let titles = $state<Title[]>([]);
	let searched = $state(false);
	let selected = $state<Title | null>(null);
	let selectedDetails = $state<TitleDetails | null>(null);
	let detailsLoading = $state(false);
	let season = $state<number | undefined>(undefined);
	let episode = $state<number | undefined>(undefined);
	let releases = $state<Release[]>([]);
	let searching = $state(false);
	let titleSearchError = $state('');
	let loadingReleases = $state(false);
	let releaseError = $state('');
	let loadingMore = $state(false);
	let canLoadMore = $state(false);
	let action = $state<string | null>(null);
	let added = $state(new Set<string>());
	let selectionOpen = $state(false);
	let selectionLoading = $state(false);
	let selectionSubmitting = $state(false);
	let selectionTaskId = $state<string | null>(null);
	let selectionTaskName = $state('torrent');
	let selectionFiles = $state<
		Array<{ id?: number; name?: string; size?: number; selected?: number }>
	>([]);
	let selectedFileIds = $state<number[]>([]);
	let releaseQuery = $state('');
	let quality = $state('All quality');
	let releaseType = $state('All types');
	let releaseSource = $state('All sources');
	let sort = $state('Best match');
	let episodeError = $state('');

	const qualityFilters = ['All quality', '4K / UHD', '1080p', '720p'] as const;
	const typeFilters = ['All types', 'WEB-DL', 'BluRay', 'Remux', 'Encode'] as const;
	const sourceFilters = $derived([
		'All sources',
		...new Set(releases.flatMap((release) => release.sources ?? [release.source]))
	]);

	const filteredReleases = $derived(
		[...releases]
			.filter((release) => {
				const text = `${release.title} ${release.name}`.toLowerCase();
				const q = releaseQuery.trim().toLowerCase();
				const matchesQuery = !q || text.includes(q);
				const matchesQuality =
					quality === 'All quality' ||
					(quality === '4K / UHD' ? /\b(2160p|4k|uhd)\b/i.test(text) : text.includes(quality));
				const matchesType = releaseType === 'All types' || text.includes(releaseType.toLowerCase());
				const matchesSource =
					releaseSource === 'All sources' ||
					(release.sources ?? [release.source]).includes(releaseSource);
				return matchesQuery && matchesQuality && matchesType && matchesSource;
			})
			.sort((a, b) => (sort === 'Name A–Z' ? a.title.localeCompare(b.title) : 0))
	);
	const filtersActive = $derived(
		Boolean(
			releaseQuery.trim() ||
			quality !== 'All quality' ||
			releaseType !== 'All types' ||
			releaseSource !== 'All sources' ||
			sort !== 'Best match'
		)
	);
	const releaseCountLabel = $derived(
		filteredReleases.length === releases.length
			? `${releases.length}`
			: `${filteredReleases.length} of ${releases.length}`
	);
	const selectedMetaLine = $derived(
		selected
			? [
					selected.year || selectedDetails?.year || '',
					...(selectedDetails?.genres ?? []),
					selectedDetails?.runtime || '',
					selected.media_type === 'movie' ? '' : 'TV show'
				].filter(Boolean)
			: []
	);
	const selectedMetaLineShort = $derived(
		selected
			? [
					selected.year || selectedDetails?.year || '',
					...(selectedDetails?.genres ?? []).slice(0, 1)
				].filter(Boolean)
			: []
	);

	async function searchTitles() {
		if (query.trim().length < 2 || searching) return;
		searching = true;
		searched = true;
		titleSearchError = '';
		releaseError = '';
		titles = [];
		selected = null;
		selectedDetails = null;
		releases = [];
		try {
			const response = await fetch(
				`/api/discover/search?q=${encodeURIComponent(query.trim())}&type=${mediaType}`
			);
			const data = await response.json();
			if (!response.ok) throw new Error(data.detail || 'Search failed');
			titles = data.titles;
			if (!titles.length) toast.info('No matching titles found.');
		} catch (error) {
			titleSearchError = error instanceof Error ? error.message : 'Search failed';
		} finally {
			searching = false;
		}
	}

	async function chooseTitle(title: Title) {
		selected = title;
		mediaType = title.media_type;
		season = undefined;
		episode = undefined;
		episodeError = '';
		releases = [];
		releaseError = '';
		clearFilters();
		selectedDetails = null;
		void loadTitleDetails(title);
		if (title.media_type === 'movie') await loadReleases();
	}

	async function loadTitleDetails(title: Title) {
		detailsLoading = true;
		try {
			const response = await fetch(
				`/api/discover/${title.media_type}/${title.imdb_id}/details`
			);
			const data = await response.json();
			if (!response.ok) return;
			if (selected?.imdb_id !== title.imdb_id) return;
			selectedDetails = data as TitleDetails;
		} catch {
			// Details are enhancement-only; the card still works without them.
		} finally {
			if (selected?.imdb_id === title.imdb_id) detailsLoading = false;
		}
	}

	function clearSelection() {
		selected = null;
		selectedDetails = null;
		season = undefined;
		episode = undefined;
		episodeError = '';
		releases = [];
		releaseError = '';
		clearFilters();
	}

	async function loadReleases() {
		const item = selected;
		if (!item || loadingReleases) return;
		if (!validateEpisodeSelection()) return;
		loadingReleases = true;
		releaseError = '';
		releases = [];
		releaseSource = 'All sources';
		canLoadMore = false;
		const errors: unknown[] = [];
		try {
			const torrentioRequest = fetchReleases(item, 'Torrentio');
			const prowlarrRequest = fetchReleases(item, 'Prowlarr');
			try {
				const data = await torrentioRequest;
				releases = mergeReleases([], data.releases);
			} catch (error) {
				errors.push(error);
			}
			try {
				const data = await prowlarrRequest;
				releases = mergeReleases(releases, data.releases);
				canLoadMore = data.has_more;
			} catch (error) {
				errors.push(error);
			}
			if (!releases.length && errors.length) throw errors[0];
			if (!releases.length) toast.info('No releases found for that selection.');
		} catch (error) {
			releaseError = error instanceof Error ? error.message : 'Release search failed';
		} finally {
			loadingReleases = false;
		}
	}

	function mergeReleases(current: Release[], incoming: Release[]) {
		const merged = new Map(current.map((release) => [release.info_hash, release]));
		for (const release of incoming) {
			const existing = merged.get(release.info_hash);
			if (!existing) {
				merged.set(release.info_hash, release);
				continue;
			}
			existing.sources = [
				...new Set([
					...(existing.sources ?? [existing.source]),
					...(release.sources ?? [release.source])
				])
			];
		}
		return [...merged.values()];
	}

	async function fetchReleases(item: Title, source: string, limit?: number) {
		const params = new URLSearchParams();
		if (
			item.media_type === 'series' &&
			typeof season === 'number' &&
			Number.isInteger(season) &&
			season > 0
		)
			params.set('season', String(season));
		if (
			item.media_type === 'series' &&
			typeof episode === 'number' &&
			Number.isInteger(episode) &&
			episode > 0
		)
			params.set('episode', String(episode));
		params.set('title', item.title);
		if (item.year) params.set('year', item.year);
		params.set('source', source);
		if (limit) params.set('limit', String(limit));
		const suffix = params.toString() ? `?${params}` : '';
		const response = await fetch(`/api/discover/${item.media_type}/${item.imdb_id}${suffix}`);
		const data = await response.json();
		if (!response.ok) throw new Error(data.detail || 'Release search failed');
		return data as { releases: Release[]; has_more: boolean };
	}

	async function loadMore() {
		const item = selected;
		if (!item || loadingMore) return;
		loadingMore = true;
		try {
			const data = await fetchReleases(item, 'Prowlarr', 100);
			const previousCount = releases.length;
			releases = mergeReleases(releases, data.releases);
			canLoadMore = data.has_more;
			if (releases.length === previousCount) toast.info('No additional Prowlarr releases found.');
		} catch (error) {
			releaseError = error instanceof Error ? error.message : 'Could not load more releases';
		} finally {
			loadingMore = false;
		}
	}

	function clearFilters() {
		releaseQuery = '';
		quality = 'All quality';
		releaseType = 'All types';
		releaseSource = 'All sources';
		sort = 'Best match';
	}

	function validateEpisodeSelection() {
		episodeError = '';
		const seasonValue = season;
		const episodeValue = episode;
		const hasSeason = seasonValue != null;
		const hasEpisode = episodeValue != null;
		if (hasEpisode && !hasSeason) {
			episodeError = 'Enter a season before choosing an episode.';
			return false;
		}
		if (
			(hasSeason && (!Number.isInteger(seasonValue) || (seasonValue ?? 0) < 1)) ||
			(hasEpisode && (!Number.isInteger(episodeValue) || (episodeValue ?? 0) < 1))
		) {
			episodeError = 'Season and episode must be positive whole numbers.';
			return false;
		}
		return true;
	}

	async function addToRd(release: Release) {
		action = `${release.info_hash}:rd`;
		try {
			const response = await fetch('/api/discover/add-to-rd', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
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
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
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
			selectedFileIds = selectionFiles
				.filter((file) => file.selected)
				.map((file) => file.id)
				.filter((id): id is number => id != null);
			selectionOpen = true;
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Could not load file selection');
		} finally {
			selectionLoading = false;
		}
	}

	async function submitSelection() {
		if (!selectionTaskId || !selectedFileIds.length || selectionSubmitting) return;
		selectionSubmitting = true;
		try {
			const response = await fetch(`/api/download/${selectionTaskId}/files`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
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
	<meta
		name="description"
		content="Search for movies and shows, then add releases to Real-Debrid."
	/>
</svelte:head>

<main class="min-h-dvh bg-background text-foreground">
	<SiteHeader onLogout={() => (window.location.href = '/')} />

	<div class="page-shell">
		<div class="page-heading">
			<div>
				<h1 class="text-[22px] leading-7 font-semibold tracking-tight text-foreground">Discover</h1>
				<p class="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
					Search movies and shows, then send releases to Real-Debrid.
				</p>
			</div>
		</div>
		<div class="console-strip px-3 py-3 sm:px-5 sm:py-4">
			<div class="mb-3 flex items-center justify-between gap-3">
				<p class="text-sm font-semibold tracking-tight text-foreground">Find a release</p>
				<span class="shrink-0 font-mono text-[10px] tracking-wide text-muted-foreground"
					>MOVIE / TV</span
				>
			</div>
			<form
				class="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center"
				onsubmit={(event) => {
					event.preventDefault();
					searchTitles();
				}}
			>
				<span class="sr-only" id="media-type-label">Media type</span>
				<div class="w-full shrink-0 sm:w-32">
					<Select.Root type="single" bind:value={mediaType} name="media-type">
						<Select.Trigger aria-labelledby="media-type-label" class="h-8 w-full text-xs"
							><span data-slot="select-value">{mediaType === 'movie' ? 'Movie' : 'TV show'}</span
							></Select.Trigger
						>
						<Select.Content
							><Select.Item value="movie" label="Movie">Movie</Select.Item><Select.Item
								value="series"
								label="TV show">TV show</Select.Item
							></Select.Content
						>
					</Select.Root>
				</div>
				<label class="sr-only" for="title-search">Title</label>
				<div class="relative min-w-0 flex-1">
					<Input
						id="title-search"
						bind:value={query}
						placeholder="Search for a movie or show…"
						autocomplete="off"
						class="h-8 border-transparent bg-muted/60 pr-8 text-[13px] placeholder:text-[13px]"
					/>
					{#if query}
						<button
							type="button"
							onclick={() => (query = '')}
							aria-label="Clear title search"
							class="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
						>
							<X class="size-3.5" />
						</button>
					{/if}
				</div>
				<Button
					type="submit"
					class="h-8 w-full shrink-0 px-4 text-[13px] sm:w-auto"
					disabled={searching || query.trim().length < 2}
					>{#if searching}<CircleNotch class="size-3.5 animate-spin" />{:else}<MagnifyingGlass
							class="size-3.5"
						/>{/if} Search</Button
				>
			</form>
			<p class="mt-3 text-xs text-muted-foreground">
				Tip: search by exact title for the cleanest release list.
			</p>
		</div>
		{#if titleSearchError}
			<Alert.Root
				variant="destructive"
				class="flex items-center justify-between gap-3"
				role="alert"
			>
				<Alert.Description class="min-w-0 flex-1">{titleSearchError}</Alert.Description>
				<Button variant="outline" size="xs" class="h-7 shrink-0" onclick={() => void searchTitles()}
					>Retry search</Button
				>
			</Alert.Root>
		{/if}
		{#if searching}
			<section class="grid gap-3" aria-label="Loading title results" aria-busy="true">
				<div class="section-heading">
					<h2 class="text-sm font-semibold tracking-tight">Finding titles</h2>
				</div>
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
					{#each [0, 1, 2, 3, 4] as i (i)}
						<div class="overflow-hidden rounded-lg border border-border bg-card">
							<Skeleton class="aspect-[2/3] w-full rounded-none" />
							<div class="grid gap-2 p-3">
								<Skeleton class="h-3.5 w-3/4" /><Skeleton class="h-3 w-1/3" />
							</div>
						</div>
					{/each}
				</div>
			</section>
		{:else if searched && !titles.length}
			<div
				class="rounded-lg border border-dashed border-border px-6 py-10 text-center"
				role="status"
			>
				<p class="text-sm font-medium">No titles found</p>
				<p class="mt-1 text-xs text-muted-foreground">
					Try the full title, or switch between movies and TV shows.
				</p>
			</div>
		{/if}
		{#if titles.length}
			{#if selected}
				{@const poster = selected.poster || selectedDetails?.poster || ''}
				<section class="flex overflow-hidden rounded-lg border border-border bg-card" aria-label="Selected title">
					{#if poster}
						<img
							src={poster}
							alt={`Poster for ${selected.title}`}
							loading="lazy"
							referrerpolicy="no-referrer"
							class="w-20 shrink-0 self-stretch bg-muted object-cover sm:w-32"
						/>
					{:else}
						<span
							class="grid w-20 shrink-0 place-items-center self-stretch bg-muted text-muted-foreground sm:w-32"
							aria-hidden="true"
							>{#if selected.media_type === 'movie'}<FilmSlate class="size-6" />{:else}<Television
									class="size-6"
								/>{/if}</span
						>
					{/if}
					<div class="flex min-w-0 flex-1 flex-col gap-1.5 p-3 sm:gap-2 sm:p-5">
						<div class="min-w-0">
							<h3 class="truncate text-base leading-6 font-semibold tracking-tight sm:text-lg" title={selected.title}>{selected.title}</h3>
							<p class="mt-1 truncate font-mono text-xs tabular-nums text-muted-foreground sm:hidden">
								{selectedMetaLineShort.length ? selectedMetaLineShort.join(' · ') : 'Year unknown'}
							</p>
							<p class="mt-1 hidden font-mono text-xs tabular-nums text-muted-foreground sm:block">
								{selectedMetaLine.length ? selectedMetaLine.join(' · ') : 'Year unknown'}
							</p>
						</div>
						{#if detailsLoading}
							<div class="hidden gap-2 sm:grid" aria-hidden="true">
								<Skeleton class="h-3.5 w-full" /><Skeleton class="h-3.5 w-5/6" />
							</div>
						{:else if selectedDetails?.description}
							<p class="hidden max-w-[62ch] text-sm leading-6 text-muted-foreground sm:line-clamp-3">
								{selectedDetails.description}
							</p>
						{/if}
						<div class="mt-auto flex items-center justify-between gap-3 pt-1">
							{#if !detailsLoading && selectedDetails?.rating}
								<span class="flex items-center gap-1.5 font-mono text-xs tabular-nums text-muted-foreground">
									<Star weight="fill" class="size-3.5 text-amber-500" aria-hidden="true" />{selectedDetails.rating}
								</span>
							{:else}
								<span></span>
							{/if}
							<Button variant="ghost" size="xs" class="h-7 shrink-0 text-muted-foreground hover:text-foreground" onclick={clearSelection}>
								<ArrowCounterClockwise class="size-3.5" /><span class="sm:hidden">Change</span><span class="hidden sm:inline">Choose different</span>
							</Button>
						</div>
					</div>
				</section>
			{:else}
				<section class="grid gap-3" aria-label="Title results">
					<div class="section-heading">
						<h2 class="text-sm font-semibold tracking-tight">Choose a title</h2>
						<span class="shrink-0 font-mono text-xs font-normal text-muted-foreground"
							>{titles.length} matches</span
						>
					</div>
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
						{#each titles as title (title.imdb_id)}
							<button
								type="button"
								class="group min-w-0 cursor-pointer overflow-hidden rounded-lg border border-border bg-card text-left transition-colors duration-150 hover:bg-muted/40 focus-visible:outline-1 focus-visible:outline-offset-1 focus-visible:outline-ring"
								onclick={() => chooseTitle(title)}
								aria-label={`Select ${title.title}`}
							>
								<span class="block aspect-[2/3] w-full overflow-hidden bg-muted">
									{#if title.poster}
										<img
											src={title.poster}
											alt={`Poster for ${title.title}`}
											loading="lazy"
											referrerpolicy="no-referrer"
											class="size-full object-cover transition-transform duration-150 group-hover:scale-[1.02]"
										/>
									{:else}
										<span
											class="grid size-full place-items-center text-muted-foreground"
											aria-hidden="true"
											>{#if title.media_type === 'movie'}<FilmSlate class="size-6" />{:else}<Television
													class="size-6"
												/>{/if}</span
										>
									{/if}
								</span>
								<span class="block p-3">
									<span
										class="block truncate text-sm leading-5 font-medium tracking-tight"
										title={title.title}>{title.title}</span
									>
									<span
										class="mt-0.5 block font-mono text-xs tabular-nums text-muted-foreground"
										>{title.year || 'Year unknown'} ·
										{title.media_type === 'movie' ? 'Movie' : 'TV'}</span
									>
								</span>
							</button>
						{/each}
					</div>
				</section>
			{/if}
		{/if}

		{#if selected?.media_type === 'series'}
			<Card
				class="w-full gap-0 rounded-lg border-border py-0 sm:flex-row sm:items-center sm:rounded-r-none"
			>
				<CardHeader
					class="shrink-0 border-b border-border px-3 py-3 sm:w-52 sm:rounded-tr-none sm:border-r sm:border-b-0 sm:px-4"
					><CardTitle class="text-sm font-semibold">Which episode?</CardTitle><CardDescription
						class="text-xs">Leave both blank to search the whole show.</CardDescription
					></CardHeader
				>
				<CardContent
					class="flex min-w-0 flex-col gap-2 px-3 py-3 sm:flex-1 sm:flex-row sm:items-end sm:px-4"
				>
					<div class="grid grid-cols-2 gap-2 sm:contents">
						<label for="season-input" class="grid min-w-0 gap-1.5 text-xs font-medium"
							>Season<Input
								id="season-input"
								type="number"
								min="1"
								bind:value={season}
								placeholder="Any"
								class="h-8 w-full text-[13px] sm:w-24"
								aria-invalid={!!episodeError}
								aria-describedby="episode-help"
							/></label
						>
						<label for="episode-input" class="grid min-w-0 gap-1.5 text-xs font-medium"
							>Episode<Input
								id="episode-input"
								type="number"
								min="1"
								bind:value={episode}
								placeholder="Any"
								class="h-8 w-full text-[13px] sm:w-24"
								aria-invalid={!!episodeError}
								aria-describedby="episode-help"
							/></label
						>
					</div>
					<Button
						type="button"
						size="sm"
						class="h-8 w-full shrink-0 sm:w-auto"
						onclick={() => loadReleases()}
						disabled={loadingReleases}
						>{#if loadingReleases}<CircleNotch
								class="size-3.5 animate-spin"
							/>{:else}<MagnifyingGlass class="size-3.5" />{/if} Find releases</Button
					>
				</CardContent>
				{#if episodeError}<p
						id="episode-help"
						class="px-3 pb-3 text-xs text-destructive sm:px-4"
						role="alert"
					>
						{episodeError}
					</p>{/if}
			</Card>
		{/if}

		{#if releases.length}
			<section class="grid gap-3" aria-label="Torrent releases">
				<div class="section-heading flex-wrap">
					<h2 class="text-sm font-semibold tracking-tight">
						Available releases <span class="font-mono text-xs font-normal text-muted-foreground"
							>({releaseCountLabel})</span
						>
					</h2>
					<div class="flex shrink-0 items-center gap-2">
						<span class="hidden text-xs text-muted-foreground sm:block">Sort</span><span
							class="sr-only">Sort releases</span
						><Select.Root type="single" bind:value={sort}
							><Select.Trigger class="h-7 w-32 text-xs"
								><span data-slot="select-value">{sort}</span></Select.Trigger
							><Select.Content sideOffset={4}
								><Select.Item value="Best match" label="Best match">Best match</Select.Item
								><Select.Item value="Name A–Z" label="Name A–Z">Name A–Z</Select.Item
								></Select.Content
							></Select.Root
						>
					</div>
				</div>
				<div class="grid gap-3 rounded-lg border border-border bg-card p-2.5 sm:p-3">
					<div class="relative min-w-0">
						<MagnifyingGlass
							class="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"
						/>
						<Input
							bind:value={releaseQuery}
							placeholder="Filter releases…"
							class="h-8 border-transparent bg-muted/60 pr-8 pl-8 text-[13px] placeholder:text-[13px]"
							aria-label="Filter releases by name"
						/>
						{#if releaseQuery}
							<button
								type="button"
								onclick={() => (releaseQuery = '')}
								aria-label="Clear release filter"
								class="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 cursor-pointer place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
							>
								<X class="size-3.5" />
							</button>
						{/if}
					</div>
					<div class="grid grid-cols-1 gap-2 min-[480px]:grid-cols-3 sm:grid-cols-3">
						<label class="grid min-w-0 gap-1.5 text-[11px] font-medium text-muted-foreground">
							<span>Quality</span>
							<Select.Root type="single" bind:value={quality}>
								<Select.Trigger size="sm" aria-label="Filter by quality" class="h-8 w-full text-xs"
									><span data-slot="select-value">{quality}</span></Select.Trigger
								>
								<Select.Content sideOffset={4}
									>{#each qualityFilters as option}<Select.Item value={option} label={option}
											>{option}</Select.Item
										>{/each}</Select.Content
								>
							</Select.Root>
						</label>
						<label class="grid min-w-0 gap-1.5 text-[11px] font-medium text-muted-foreground">
							<span>Format</span>
							<Select.Root type="single" bind:value={releaseType}>
								<Select.Trigger size="sm" aria-label="Filter by format" class="h-8 w-full text-xs"
									><span data-slot="select-value">{releaseType}</span></Select.Trigger
								>
								<Select.Content sideOffset={4}
									>{#each typeFilters as option}<Select.Item value={option} label={option}
											>{option}</Select.Item
										>{/each}</Select.Content
								>
							</Select.Root>
						</label>
						<label class="grid min-w-0 gap-1.5 text-[11px] font-medium text-muted-foreground">
							<span>Source</span>
							<Select.Root type="single" bind:value={releaseSource}>
								<Select.Trigger size="sm" aria-label="Filter by source" class="h-8 w-full text-xs"
									><span data-slot="select-value">{releaseSource}</span></Select.Trigger
								>
								<Select.Content sideOffset={4}
									>{#each sourceFilters as option}<Select.Item value={option} label={option}
											>{option}</Select.Item
										>{/each}</Select.Content
								>
							</Select.Root>
						</label>
					</div>
					{#if filtersActive}
						<div class="flex items-center justify-between gap-3 border-t border-border/60 pt-2">
							<p class="text-xs text-muted-foreground">Filters are narrowing this list.</p>
							<Button variant="ghost" size="xs" class="h-7 shrink-0" onclick={clearFilters}
								>Clear filters</Button
							>
						</div>
					{/if}
				</div>
				{#if releaseError && !filteredReleases.length}
					<Alert.Root
						variant="destructive"
						class="flex items-center justify-between gap-3"
						role="alert"
					>
						<Alert.Description class="min-w-0 flex-1">{releaseError}</Alert.Description>
						<Button
							variant="outline"
							size="xs"
							class="h-7 shrink-0"
							onclick={() => void loadReleases()}>Retry releases</Button
						>
					</Alert.Root>
				{/if}
				{#if filteredReleases.length}
					<div class="ledger">
						{#each filteredReleases as release (release.info_hash)}
							<div
								class="ledger-row row-enter group flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4"
							>
								<div
									class="grid size-8 shrink-0 place-items-center rounded-md border border-border font-mono text-[10px] font-semibold tracking-wide text-muted-foreground"
									title={release.source}
									aria-label={`Source: ${release.source}`}
								>
									{release.source === 'Torrentio'
										? 'TOR'
										: release.source === 'Prowlarr'
											? 'PRO'
											: 'SRC'}
								</div>
								<div class="min-w-0 flex-1">
									<p
										class="line-clamp-2 break-words text-sm leading-5 font-medium tracking-tight"
										title={release.title}
									>
										{release.title}
									</p>
									<div
										class="mt-1 flex min-w-0 items-center gap-1.5 font-mono text-[11px] text-muted-foreground"
									>
										<span
											class="min-w-0 shrink line-clamp-2 break-words text-xs"
											title={release.name || release.source}>{release.name || release.source}</span
										>{#if (release.sources ?? []).length > 1}<span
												class="hidden shrink-0 rounded-full border border-border px-1.5 py-px text-[10px] sm:inline-block"
												>{(release.sources ?? []).join(' + ')}</span
											>{/if}<span class="shrink-0 tabular-nums"
											>{release.info_hash.slice(0, 8)}…</span
										>
									</div>
								</div>
								<div class="flex w-full shrink-0 gap-2 sm:w-auto">
									<Button
										class="h-7 min-w-0 flex-1 px-3 text-xs sm:flex-none"
										size="sm"
										variant="outline"
										title="Add to Real-Debrid"
										aria-label={`Add ${release.title} to Real-Debrid`}
										disabled={action !== null || added.has(release.info_hash)}
										onclick={() => addToRd(release)}
										>{#if added.has(release.info_hash)}<Check class="size-3.5" /><span>Added</span
											>{:else if action === `${release.info_hash}:rd`}<CircleNotch
												class="size-3.5 animate-spin"
											/><span>Adding…</span>{:else}<Upload class="size-3.5" /><span>Add to RD</span
											>{/if}</Button
									><Button
										class="h-7 min-w-0 flex-1 px-3 text-xs sm:flex-none"
										size="sm"
										title="Download to server"
										aria-label={`Download ${release.title} to server`}
										disabled={action !== null}
										onclick={() => download(release)}
										>{#if action === `${release.info_hash}:download`}<CircleNotch
												class="size-3.5 animate-spin"
											/><span>Adding…</span>{:else}<Download class="size-3.5" /><span>Download</span
											>{/if}</Button
									>
								</div>
							</div>
						{/each}
					</div>
				{:else}<div class="rounded-md border border-dashed border-border px-6 py-10 text-center">
						<p class="text-sm font-medium">No releases match those filters.</p>
						<p class="mt-1 text-xs text-muted-foreground">
							Try clearing a filter or searching for a different release name.
						</p>
						<Button variant="ghost" size="sm" class="mt-3 h-8" onclick={clearFilters}
							>Clear filters</Button
						>
					</div>{/if}
			</section>
			{#if canLoadMore}
				<div class="flex justify-center">
					<Button variant="outline" size="sm" class="h-8" onclick={loadMore} disabled={loadingMore}
						>{#if loadingMore}<CircleNotch class="size-3.5 animate-spin" /> Loading more…{:else}Load
							more Prowlarr results{/if}</Button
					>
				</div>
			{/if}
		{/if}
		{#if selected && loadingReleases}<div
				class="flex items-center justify-center gap-2 rounded-md border border-dashed border-border px-6 py-10 text-sm text-muted-foreground"
				role="status"
			>
				<CircleNotch class="size-4 animate-spin" /> Finding releases for {selected.title}…
			</div>{:else if selected && releaseError && !releases.length}<Alert.Root
				variant="destructive"
				class="flex items-center justify-between gap-3"
				role="alert"
				><Alert.Description class="min-w-0 flex-1">{releaseError}</Alert.Description><Button
					variant="outline"
					size="xs"
					class="h-7 shrink-0"
					onclick={() => void loadReleases()}>Retry releases</Button
				></Alert.Root
			>{:else if selected && !releases.length && selected.media_type === 'movie'}<div
				class="rounded-md border border-dashed border-border px-6 py-10 text-center"
				role="status"
			>
				<p class="text-sm font-medium">No releases found</p>
				<p class="mt-1 text-xs text-muted-foreground">Try another title or search again later.</p>
				<Button variant="outline" size="sm" class="mt-3 h-8" onclick={() => void loadReleases()}
					>Search again</Button
				>
			</div>{/if}
	</div>
</main>

<Dialog.Root bind:open={selectionOpen}>
	<Dialog.Content showCloseButton={true} class="gap-3 p-4 sm:max-w-[520px]">
		<Dialog.Header>
			<Dialog.Title>Select files for {selectionTaskName}</Dialog.Title>
			<Dialog.Description
				>Choose at least one file before this torrent can start.</Dialog.Description
			>
		</Dialog.Header>
		<div class="max-h-[55vh] overflow-y-auto">
			{#if selectionLoading}
				<div class="flex items-center justify-center gap-2 py-8 text-[13px] text-muted-foreground">
					<CircleNotch class="size-3.5 animate-spin" /> Loading files…
				</div>
			{:else}
				<div class="grid gap-1">
					{#each selectionFiles as file}
						{@const checked = file.id != null && selectedFileIds.includes(file.id)}
						<button
							type="button"
							role="checkbox"
							aria-checked={checked}
							onclick={() => {
								if (file.id == null) return;
								selectedFileIds = selectedFileIds.includes(file.id)
									? selectedFileIds.filter((id) => id !== file.id)
									: [...selectedFileIds, file.id];
							}}
							class="flex cursor-pointer items-center gap-3 rounded px-2 py-2 text-left text-[13px] hover:bg-muted"
						>
							<Checkbox {checked} tabindex={-1} class="pointer-events-none" aria-hidden="true" />
							<span class="min-w-0 flex-1 truncate" title={file.name}>{file.name}</span><span
								class="shrink-0 font-mono text-xs text-muted-foreground">{fileSize(file.size)}</span
							>
						</button>
					{/each}
				</div>
			{/if}
		</div>
		<Dialog.Footer class="flex-row justify-between"
			><Button variant="outline" size="sm" onclick={() => (selectionOpen = false)}
				>Choose later</Button
			><Button
				size="sm"
				disabled={selectionLoading || selectionSubmitting || !selectedFileIds.length}
				onclick={submitSelection}
				>{selectionSubmitting
					? 'Starting…'
					: `Start with ${selectedFileIds.length} selected`}</Button
			></Dialog.Footer
		>
	</Dialog.Content>
</Dialog.Root>
