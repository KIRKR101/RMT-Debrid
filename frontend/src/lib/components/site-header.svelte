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
		Package,
		Database,
		HardDrive,
		CircleNotch,
		ArrowClockwise,
		FloppyDisk,
		HardDrives,
		Gear,
		Check,
		WarningCircle,
		List,
		SignOut
	} from 'phosphor-svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import * as Dialog from '$lib/components/ui/dialog';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Input } from '$lib/components/ui/input';
	import { formatBytes, formatDateShort } from '$lib/format';
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
	let settingsLoading = $state(false);
	let settingsLoadError = $state('');
	let storage = $state<StorageData | null>(null);
	let storageError = $state('');
	let refreshingStorage = $state(false);

	let saving = $state(false);
	let detailsDialogOpen = $state(false);
	let storageDialogOpen = $state(false);
	let discardSettingsDialogOpen = $state(false);
	let settingsSnapshot = $state('');
	let settingsBaseline = $state<SettingsData | null>(null);

	function settingsFingerprint(value: SettingsData = settings) {
		return JSON.stringify({
			download_folder: value.download_folder,
			max_concurrent_downloads: Number(value.max_concurrent_downloads),
			webhook_url: value.webhook_url,
			webhook_events: [...value.webhook_events].sort()
		});
	}

	const settingsDirty = $derived(
		(settingsSnapshot !== '' && settingsSnapshot !== settingsFingerprint()) ||
			!!apiKey ||
			!!webhookToken
	);

	function date(value?: string) {
		return formatDateShort(value);
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
		onLogout();
	}

	async function fetchAccount() {
		try {
			const data = await request('/api/account/info');
			if (!data.user || typeof data.user.username !== 'string')
				throw new Error('Invalid account response');
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
		settingsLoading = true;
		settingsLoadError = '';
		try {
			settings = await request('/api/settings');
			settingsBaseline = {
				...settings,
				webhook_events: [...settings.webhook_events]
			};
			settingsSnapshot = settingsFingerprint();
		} catch (error) {
			settingsLoadError = error instanceof Error ? error.message : 'Settings unavailable';
		} finally {
			settingsLoading = false;
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
		webhookToken = '';
		settingsMessage = null;
		detailsDialogOpen = true;
		void fetchSettings();
	}

	function handleSettingsOpenChange(open: boolean) {
		if (open) {
			detailsDialogOpen = true;
			return;
		}
		if (settingsDirty && !saving) {
			discardSettingsDialogOpen = true;
			return;
		}
		detailsDialogOpen = false;
	}

	function discardSettingsChanges() {
		if (settingsBaseline)
			settings = { ...settingsBaseline, webhook_events: [...settingsBaseline.webhook_events] };
		apiKey = '';
		webhookToken = '';
		settingsMessage = null;
		discardSettingsDialogOpen = false;
		detailsDialogOpen = false;
	}

	async function saveSettings() {
		if (saving || settingsLoading || settingsLoadError) return;
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
			settingsBaseline = {
				...settings,
				webhook_events: [...settings.webhook_events]
			};
			settingsSnapshot = settingsFingerprint();
			apiKey = '';
			webhookToken = '';
			detailsDialogOpen = false;
			toast.success('Settings saved.');
			fetchAccount();
		} catch (error) {
			settingsMessage = {
				type: 'error',
				text: error instanceof Error ? error.message : 'Failed to save settings.'
			};
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		let timer: ReturnType<typeof setInterval> | undefined;
		fetchAccount();
		fetchSettings();
		timer = setInterval(fetchAccount, 300000);
		return () => {
			if (timer) clearInterval(timer);
		};
	});
</script>

<Tooltip.Provider>
	<header class="sticky top-0 z-40 border-b border-border bg-background">
		<div
			class="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4 sm:gap-5 sm:px-8"
		>
			<div class="flex min-w-0 flex-1 items-center gap-1 sm:gap-2">
				<a href="/" class="flex shrink-0 items-center no-underline" aria-label="RMT-Debrid home">
					<span class="text-xs font-medium tracking-normal text-muted-foreground">RMT-Debrid</span>
				</a>
				<span class="mx-1 hidden h-4 w-px bg-border sm:block" aria-hidden="true"></span>
				<SiteNav />
			</div>

			<div class="hidden shrink-0 items-center gap-0.5 sm:gap-1.5 min-[640px]:flex">
				{#if account}
					<DropdownMenu.Root>
						<DropdownMenu.Trigger
							class="flex h-8 cursor-pointer items-center gap-1.5 rounded-[min(var(--radius-md),10px)] px-1.5 py-1 text-left transition hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground max-[419px]:hidden sm:px-2 dark:hover:bg-muted/50"
							aria-label="Open account menu"
						>
							<span class="hidden text-right leading-tight lg:block">
								<span class="block text-xs font-semibold text-foreground capitalize"
									>{account.type}</span
								>
								<span class="mt-0.5 block text-[11px] tabular-nums text-muted-foreground"
									>expires {date(account.expiration)}</span
								>
							</span>
							<span
								class="grid size-7 place-items-center rounded-sm border border-border bg-muted font-mono text-[10px] font-semibold text-foreground"
								title={account.username}
							>
								{account.username.slice(0, 2).toUpperCase()}
							</span>
						</DropdownMenu.Trigger>
						<DropdownMenu.Content align="end" class="min-w-44">
							<DropdownMenu.Label class="font-mono text-[11px] text-muted-foreground"
								>{account.username}</DropdownMenu.Label
							>
							<DropdownMenu.Separator />
							<DropdownMenu.Item onclick={logout}><SignOut class="size-3.5" />Sign out</DropdownMenu.Item>
						</DropdownMenu.Content>
					</DropdownMenu.Root>
				{:else if accountError}
					<span class="hidden text-xs text-muted-foreground sm:block">{accountError}</span>
				{/if}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							<Button
								{...props}
								variant="ghost"
								size="icon-sm"
								aria-label="Open storage diagnostics"
								onclick={openStorage}
								class="size-7 text-muted-foreground max-[359px]:hidden"
							>
								<HardDrives class="size-3.5" />
							</Button>
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>Storage</Tooltip.Content>
				</Tooltip.Root>
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							<Button
								{...props}
								variant="ghost"
								size="icon-sm"
								aria-label="Open settings"
								onclick={() => openDetails()}
								class="size-7 text-muted-foreground"
							>
								<Gear class="size-3.5" />
							</Button>
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>Settings</Tooltip.Content>
				</Tooltip.Root>
			</div>
			<div class="min-[640px]:hidden">
				<DropdownMenu.Root>
					<DropdownMenu.Trigger
						class="grid size-9 place-items-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground aria-expanded:bg-muted"
						aria-label="Open account and app menu"
					>
						<List class="size-4" />
					</DropdownMenu.Trigger>
					<DropdownMenu.Content align="end" class="min-w-48">
						<DropdownMenu.Label class="font-mono text-[11px] text-muted-foreground"
							>{account?.username ?? 'RMT-Debrid'}</DropdownMenu.Label
						>
						<DropdownMenu.Separator />
						<DropdownMenu.Item onclick={openStorage}><HardDrives class="size-3.5" />Storage</DropdownMenu.Item>
						<DropdownMenu.Item onclick={openDetails}><Gear class="size-3.5" />Settings</DropdownMenu.Item>
						<DropdownMenu.Separator />
						<DropdownMenu.Item onclick={logout}><SignOut class="size-3.5" />Sign out</DropdownMenu.Item>
					</DropdownMenu.Content>
				</DropdownMenu.Root>
			</div>
		</div>
	</header>
</Tooltip.Provider>

<Dialog.Root bind:open={storageDialogOpen}>
	<Dialog.Content class="gap-0 p-0 sm:max-w-[480px]">
		<div class="border-b border-border px-4 pt-4 pr-14 pb-3 sm:px-5">
			<Dialog.Header class="gap-1">
				<div class="flex items-center gap-2">
					<Dialog.Title>Storage</Dialog.Title><Button
						variant="ghost"
						size="icon-xs"
						class="size-5 shrink-0"
						onclick={() => loadStorage(true)}
						disabled={refreshingStorage}
						aria-label="Refresh storage details"
						><ArrowClockwise class={`size-3 ${refreshingStorage ? 'animate-spin' : ''}`} /></Button
					>
				</div>
				<p class="text-xs text-muted-foreground">Disk usage for the download volumes.</p>
			</Dialog.Header>
		</div>

		<div class="max-h-[70vh] overflow-y-auto bg-muted/20 px-3 py-2.5">
			{#if storageError}
				<Alert.Root variant="destructive"
					><Alert.Description>{storageError}</Alert.Description></Alert.Root
				>
			{:else if storage}
				<div class="grid gap-3">
					<div
						class="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4"
					>
						<div class="bg-card px-2.5 py-2 text-center">
							<strong class="block text-sm font-semibold tabular-nums"
								>{storage.used_percent}%</strong
							><span class="mt-0.5 block text-[11px] text-muted-foreground">Used</span>
						</div>
						<div class="bg-card px-2.5 py-2 text-center">
							<strong class="block text-sm font-semibold tabular-nums"
								>{storage.volumes.length}</strong
							><span class="mt-0.5 block text-[11px] text-muted-foreground">Volumes</span>
						</div>
						<div class="bg-card px-2.5 py-2 text-center">
							<strong class="block text-sm font-semibold tabular-nums"
								>{formatBytes(storage.total_bytes)}</strong
							><span class="mt-0.5 block text-[11px] text-muted-foreground">Total</span>
						</div>
						<div class="bg-card px-2.5 py-2 text-center">
							<strong class="block text-sm font-semibold tabular-nums"
								>{formatBytes(storage.free_bytes)}</strong
							><span class="mt-0.5 block text-[11px] text-muted-foreground">Free</span>
						</div>
					</div>
					{#each storage.volumes as volume}
						<div class="rounded-xl border border-border bg-card p-3">
							<div class="mb-2.5 flex items-center gap-2.5">
								<span class="grid size-8 shrink-0 place-items-center rounded-lg bg-muted">
									{#if volume.total_bytes < 1024 ** 4}<Package
											class="size-3.5 text-muted-foreground"
										/>
									{:else if volume.total_bytes < 4 * 1024 ** 4}<HardDrive
											class="size-3.5 text-muted-foreground"
										/>
									{:else}<Database class="size-3.5 text-muted-foreground" />{/if}
								</span>
								<div class="min-w-0 flex-1">
									<strong class="block truncate text-[13px] font-medium tracking-tight"
										>{volume.name}</strong
									><span class="mt-0.5 block truncate font-mono text-xs text-muted-foreground"
										>{volume.path} · {volume.filesystem}</span
									>
								</div>
								<span class="shrink-0 font-mono text-xs font-medium tabular-nums text-foreground"
									>{volume.used_percent}%</span
								>
							</div>
							<div
								class="h-1 overflow-hidden rounded-full bg-muted"
								role="progressbar"
								aria-label={`${volume.name} storage used`}
								aria-valuemin="0"
								aria-valuemax="100"
								aria-valuenow={volume.used_percent}
								aria-valuetext={`${volume.used_percent}% used, ${formatBytes(volume.free_bytes)} free`}
							>
								<div
									class="h-full rounded-full bg-foreground transition-[width] duration-500"
									style={`width: ${Math.min(volume.used_percent, 100)}%`}
								></div>
							</div>
							<div class="mt-2 flex justify-between gap-2 font-mono text-xs text-muted-foreground">
								<span>{formatBytes(volume.used_bytes)} used</span><span
									>{formatBytes(volume.free_bytes)} free</span
								>
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div
					class="flex items-center justify-center gap-2 rounded-lg border border-border bg-background px-4 py-8 text-[13px] text-muted-foreground"
				>
					<CircleNotch class="size-3.5 animate-spin" /> Loading storage…
				</div>
			{/if}
		</div>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={detailsDialogOpen} onOpenChange={handleSettingsOpenChange}>
	<Dialog.Content class="max-h-[75dvh] gap-0 p-0 sm:max-w-[440px]">
		<div class="border-b border-border px-5 pt-5 pr-14 pb-4 sm:px-6">
			<Dialog.Header class="gap-1">
				<Dialog.Title>Settings</Dialog.Title>
				<p class="text-xs text-muted-foreground">
					Account, download preferences and notifications.
				</p>
			</Dialog.Header>
		</div>

		<div
			class="max-h-[calc(75dvh-9rem)] overflow-y-auto px-4 py-4 sm:px-5"
			aria-busy={settingsLoading}
		>
			{#if settingsLoading}
				<div
					class="flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-8 text-[13px] text-muted-foreground"
					role="status"
				>
					<CircleNotch class="size-4 animate-spin" /> Loading latest settings…
				</div>
			{:else if settingsLoadError}
				<Alert.Root variant="destructive" class="flex items-center justify-between gap-3">
					<Alert.Description class="min-w-0 flex-1">{settingsLoadError}</Alert.Description>
					<Button
						variant="outline"
						size="xs"
						class="h-7 shrink-0"
						onclick={() => void fetchSettings()}>Retry</Button
					>
				</Alert.Root>
			{:else}
				<div class="grid gap-6">
					<section aria-labelledby="settings-account-heading" class="grid gap-2.5">
						<h3 id="settings-account-heading" class="text-[13px] font-medium text-foreground">
							Account
						</h3>
						{#if account}
							<dl
								class="divide-y divide-border overflow-hidden rounded-lg border border-border bg-muted/30 text-[13px] leading-5"
							>
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
								<Alert.Description class="text-[13px]"
									>{accountError}. Check your API key below.</Alert.Description
								>
							</Alert.Root>
						{:else}
							<div
								class="flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-6 text-[13px] text-muted-foreground"
							>
								<CircleNotch class="size-4 animate-spin" /> Loading account…
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
						<h3
							id="settings-preferences-heading"
							class="mb-2 text-[13px] font-medium text-foreground"
						>
							Preferences
						</h3>
						<div class="grid gap-5">
							<div class="grid gap-2">
								<label for="api-key" class="text-[13px] leading-none font-medium"
									>Real-Debrid API key</label
								>
								<Input
									id="api-key"
									type="password"
									bind:value={apiKey}
									disabled={saving}
									placeholder="Leave blank to keep current"
									autocomplete="new-password"
									aria-describedby="api-key-hint"
									class="h-8 font-mono text-[13px]"
								/>
								<p
									id="api-key-hint"
									class="flex items-center gap-1.5 text-xs leading-4 text-muted-foreground"
								>
									{#if settings.rd_api_key_set}
										<span
											>Key set: <span class="font-mono"
												>•••{settings.rd_api_key_hint.slice(-4)}</span
											></span
										>
									{:else}
										<span>No key configured yet</span>
									{/if}
								</p>
							</div>
							<div class="grid gap-2">
								<label for="download-folder" class="text-[13px] leading-none font-medium"
									>Download folder</label
								>
								<Input
									id="download-folder"
									bind:value={settings.download_folder}
									disabled={saving}
									required
									autocomplete="off"
									spellcheck="false"
									placeholder="/downloads"
									class="h-8 font-mono text-[13px]"
								/>
							</div>
							<div class="grid gap-2">
								<label for="max-concurrent" class="text-[13px] leading-none font-medium"
									>Concurrent downloads</label
								>
								<Input
									id="max-concurrent"
									type="number"
									min="1"
									max="20"
									inputmode="numeric"
									bind:value={settings.max_concurrent_downloads}
									disabled={saving}
									required
									class="h-8 w-24 tabular-nums"
								/>
								<p class="text-xs leading-4 text-muted-foreground">
									1–20 downloads can run at the same time.
								</p>
							</div>
							<div class="grid gap-2">
								<label for="webhook-url" class="text-[13px] leading-none font-medium"
									>Completion webhook</label
								>
								<Input
									id="webhook-url"
									bind:value={settings.webhook_url}
									disabled={saving}
									type="url"
									placeholder="https://ntfy.example.com/downloads"
									autocomplete="off"
									class="h-8 font-mono text-[13px]"
								/>
								<p class="text-xs leading-4 text-muted-foreground">
									POSTs when a download completes.
								</p>
							</div>
							<div class="grid gap-2">
								<label for="webhook-token" class="text-[13px] leading-none font-medium"
									>Webhook bearer token</label
								>
								<Input
									id="webhook-token"
									type="password"
									bind:value={webhookToken}
									disabled={saving}
									placeholder={settings.webhook_token_set
										? 'Leave blank to keep current'
										: 'Optional'}
									autocomplete="new-password"
									class="h-8 font-mono text-[13px]"
								/>
							</div>
							<fieldset class="grid gap-2">
								<legend class="pb-2 text-[13px] leading-none font-medium">Notify me about</legend>
								<div class="grid gap-2 rounded-lg border border-border bg-muted/30 p-3">
									{#each webhookEventOptions as [event, label]}
										{@const checked = settings.webhook_events.includes(event)}
										<button
											type="button"
											role="checkbox"
											aria-checked={checked}
											disabled={saving}
											onclick={() => {
												const events = new Set(settings.webhook_events);
												if (checked) events.delete(event);
												else events.add(event);
												settings.webhook_events = [...events];
											}}
											class="flex cursor-pointer items-center gap-2 text-left text-[13px] disabled:cursor-not-allowed disabled:opacity-50"
										>
											<Checkbox
												{checked}
												tabindex={-1}
												class="pointer-events-none"
												aria-hidden="true"
											/>
											{label}
										</button>
									{/each}
								</div>
								<p class="text-xs leading-4 text-muted-foreground">
									Leave all unchecked to disable notifications.
								</p>
							</fieldset>
						</div>
					</form>
				</div>
			{/if}
		</div>

		<div class="flex min-h-12 items-center gap-3 border-t border-border bg-muted/30 px-4 py-3">
			<div class="min-w-0 flex-1">
				{#if settingsMessage}
					<p
						class="flex items-center gap-1.5 text-xs leading-4 {settingsMessage.type === 'success'
							? 'text-success'
							: 'text-destructive'}"
						role={settingsMessage.type === 'error' ? 'alert' : 'status'}
						aria-live={settingsMessage.type === 'error' ? 'assertive' : 'polite'}
					>
						{#if settingsMessage.type === 'success'}
							<Check class="size-3.5 shrink-0" />
						{:else}
							<WarningCircle class="size-3.5 shrink-0" />
						{/if}
						<span class="truncate">{settingsMessage.text}</span>
					</p>
				{/if}
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<Dialog.Close>
					{#snippet child({ props })}
						<Button variant="outline" size="sm" class="h-8" {...props}>Cancel</Button>
					{/snippet}
				</Dialog.Close>
				<Button
					type="submit"
					form="settings-form"
					size="sm"
					class="h-8 min-w-28"
					disabled={saving || settingsLoading || !!settingsLoadError || !settingsDirty}
				>
					{#if saving}<CircleNotch class="size-3.5 animate-spin" /> Saving…{:else}<FloppyDisk
							class="size-3.5"
						/> Save changes{/if}
				</Button>
			</div>
		</div>
	</Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={discardSettingsDialogOpen}>
	<Dialog.Content class="sm:max-w-[380px]">
		<div class="px-5 pt-5 pr-12 pb-4">
			<Dialog.Header>
				<Dialog.Title>Discard unsaved changes?</Dialog.Title>
				<Dialog.Description>Your settings have changed but have not been saved.</Dialog.Description>
			</Dialog.Header>
		</div>
		<Dialog.Footer class="border-t border-border/60 bg-muted/20 px-5 py-3.5">
			<Dialog.Close>
				{#snippet child({ props })}
					<Button variant="outline" size="sm" class="h-8" {...props}>Keep editing</Button>
				{/snippet}
			</Dialog.Close>
			<Button variant="destructive" size="sm" class="h-8" onclick={discardSettingsChanges}
				>Discard changes</Button
			>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
