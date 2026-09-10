<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import { Toaster } from '$lib/components/ui/sonner';
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<a href="#main-content" class="skip-link">Skip to content</a>

<div id="main-content" tabindex="-1" class="flex min-h-dvh flex-col outline-none">
	<div class="flex-1">
		{@render children()}
	</div>
</div>
<Toaster position="bottom-right" closeButton />
