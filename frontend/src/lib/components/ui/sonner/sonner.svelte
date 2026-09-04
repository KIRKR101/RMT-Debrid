<script lang="ts">
	import { Toaster as Sonner, type ToasterProps } from "svelte-sonner";

	let { ...restProps }: ToasterProps = $props();
</script>

<Sonner
	theme="system"
	class="toaster group"
	style="--normal-bg: var(--popover); --normal-text: var(--popover-foreground); --normal-border: var(--border);"
	{...restProps}
/>
