<script lang="ts" module>
	type Account = {
		username: string;
		type: string;
		expiration?: string;
		points: number;
	};

	let cachedAccount: Account | null = null;
</script>

<script lang="ts">
	import { onMount } from 'svelte';
	import {
		Box,
		Database,
		HardDrive,
		Loader2,
		RefreshCw,
		Save,
		Server,
		Settings,
		Check,
		CircleAlert
	} from '@lucide/svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Input } from '$lib/components/ui/input';
	import { toast } from 'svelte-sonner';
	import SiteNav from '$lib/components/site-nav.svelte';

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

	let { onLogout }: { onLogout: () => void } = $props();

	// Seed from the module-level cache so switching pages doesn't flicker
	// through an empty account state; refreshed in the background on mount.
	let account = $state<Account | null>(cachedAccount);
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

	let saving = $state(false);
	let detailsDialogOpen = $state(false);
	let storageDialogOpen = $state(false);

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

	function date(value?: string) {
		return value ? new Date(value).toLocaleDateString() : 'N/A';
	}

	async function request(path: string, init: RequestInit = {}) {
		const response = await fetch(path, init);
		const data = await response.json().catch(() => ({}));
		if (!response.ok) {
			if (response.status === 401) onLogout();
			throw new Error(data.detail || 'Request failed');
		}
		return data;
	}

	async function logout() {
		await request('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
		accountMenuOpen = false;
		onLogout();
	}

	async function fetchAccount() {
		try {
			const data = await request('/api/account/info');
			if (!data.user || typeof data.user.username !== 'string') throw new Error('Invalid account response');
			cachedAccount = data.user;
			account = data.user;
			accountError = '';
		} catch {
			// Keep the cached profile instead of flickering to an error state.
			if (!cachedAccount) {
				account = null;
				accountError = 'Account unavailable';
			}
		}
	}

	async function fetchSettings() {
		try {
			settings = await request('/api/settings');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : 'Settings unavailable');
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

	function openDetails() {
		apiKey = '';
		settingsMessage = null;
		detailsDialogOpen = true;
		fetchSettings();
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
			toast.success('Settings saved.');
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
		fetchAccount();
		fetchSettings();
		timer = setInterval(fetchAccount, 300000);
		return () => {
			if (timer) clearInterval(timer);
			document.removeEventListener('pointerdown', closeAccountMenuOnOutsideClick);
		};
	});
</script>

<header class="border-b border-border">
	<div class="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-2 px-3 sm:gap-4 sm:px-8">
		<SiteNav />

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
