<script lang="ts">
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { Card, CardContent, CardHeader, CardTitle } from '$lib/components/ui/card';

	const isNotFound = $derived(page.status === 404);
</script>

<svelte:head>
	<title>{page.status} — RMT-Debrid</title>
	<meta name="description" content="RMT-Debrid error page." />
</svelte:head>

<main class="grid min-h-dvh place-items-center px-4 py-12 sm:py-16">
	<a
		href="/"
		class="fixed top-5 left-5 flex items-center gap-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
		aria-label="RMT-Debrid home"
	>
		<span
			class="grid size-7 place-items-center rounded-md bg-primary text-[11px] font-bold text-primary-foreground"
			>R</span
		>
		<span>RMT-Debrid</span>
	</a>
	<Card class="w-full max-w-sm">
		<CardHeader class="space-y-2 pb-5">
			<div class="flex items-center gap-2.5">
				<span
					class="grid size-9 shrink-0 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground"
					>R</span
				>
				<div class="min-w-0">
					<CardTitle class="tracking-tight">
						{#if isNotFound}Page not found{:else}Something went wrong{/if}
					</CardTitle>
					<p class="mt-0.5 font-mono text-xs text-muted-foreground tabular-nums">
						Error {page.status}
					</p>
				</div>
			</div>
		</CardHeader>
		<CardContent class="grid gap-4">
			<p class="text-[13px] leading-relaxed text-muted-foreground">
				{#if isNotFound}
					This address does not match anything on this server. Check the URL or head back.
				{:else}
					{page.error?.message ?? 'The server hit an unexpected problem. Try again or go back.'}
				{/if}
			</p>
			<div class="flex gap-2">
				<Button href="/" class="h-9 flex-1">Back to downloads</Button>
				<Button variant="outline" class="h-9 flex-1" onclick={() => window.history.back()}
					>Go back</Button
				>
			</div>
		</CardContent>
	</Card>
</main>
