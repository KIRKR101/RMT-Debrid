<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { statusKind, statusLabel, type StatusKind } from '$lib/status';
	import { cn } from '$lib/utils';

	let { status, class: className = '' }: { status: string; class?: string } = $props();

	const kind: StatusKind = $derived(statusKind(status));

	const dot: Record<StatusKind, string> = {
		success: 'bg-foreground',
		info: 'bg-muted-foreground',
		warning: 'bg-muted-foreground',
		destructive: 'bg-destructive',
		muted: 'bg-muted-foreground/60'
	};

	const tone: Record<StatusKind, string> = {
		success: 'border-border bg-muted/60 text-foreground',
		info: 'border-border bg-transparent text-muted-foreground',
		warning: 'border-border bg-transparent text-muted-foreground',
		destructive: 'border-destructive/40 bg-destructive/10 text-destructive',
		muted: 'border-border bg-transparent text-muted-foreground'
	};
</script>

<Badge
	variant="outline"
	class={cn(
		'gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium tracking-tight whitespace-nowrap normal-case tabular-nums',
		tone[kind],
		className
	)}
>
	<span class={cn('size-1.5 rounded-full', dot[kind])} aria-hidden="true"></span>
	{statusLabel(status)}
</Badge>
