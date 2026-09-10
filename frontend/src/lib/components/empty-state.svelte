<script lang="ts">
	import type { Component } from 'svelte';
	import { Button } from '$lib/components/ui/button';

	let {
		icon: Icon,
		title,
		hint = '',
		actionLabel = '',
		onAction
	}: {
		icon: Component;
		title: string;
		hint?: string;
		actionLabel?: string;
		onAction?: () => void;
	} = $props();
</script>

<div class="flex flex-col items-center px-6 py-8 text-center" role="status">
	<span class="grid size-9 place-items-center rounded-full border border-border">
		<Icon class="size-3.5 text-muted-foreground" aria-hidden="true" />
	</span>
	<p class="mt-3 text-[13px] font-semibold tracking-tight text-foreground">{title}</p>
	{#if hint}
		<p class="mt-1 max-w-xs text-[13px] leading-relaxed text-muted-foreground">{hint}</p>
	{/if}
	{#if actionLabel && onAction}
		<Button variant="outline" size="sm" class="mt-4 h-8" onclick={onAction}>{actionLabel}</Button>
	{/if}
</div>
